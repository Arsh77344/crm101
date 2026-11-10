from __future__ import annotations
import datetime as dt
import json
import os
import socket
import time
import traceback
import uuid

import marketing as m
import runtime_config as rc
import observability

SCHEMA='''
CREATE TABLE IF NOT EXISTS v12_worker_jobs(
 id TEXT PRIMARY KEY,
 job_type TEXT NOT NULL,
 payload_json TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'Queued',
 priority INTEGER NOT NULL DEFAULT 100,
 attempts INTEGER NOT NULL DEFAULT 0,
 max_attempts INTEGER NOT NULL DEFAULT 5,
 available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 lease_owner TEXT DEFAULT '',
 lease_until TEXT,
 last_error TEXT DEFAULT '',
 idempotency_key TEXT UNIQUE,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS v12_worker_jobs_due ON v12_worker_jobs(status,available_at,priority,created_at);
'''

def uid():return 'JOB-'+uuid.uuid4().hex[:16].upper()

def initialise():
    with m.connect() as con:con.executescript(SCHEMA)

def enqueue(job_type:str,payload:dict|None=None,priority:int=100,max_attempts:int=5,idempotency_key:str='',delay_seconds:int=0)->str:
    initialise();jid=uid();delay=max(0,int(delay_seconds or 0));available=(_now()+dt.timedelta(seconds=delay)).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    try:
        with m.connect() as con:
            con.execute('''INSERT INTO v12_worker_jobs(id,job_type,payload_json,priority,max_attempts,idempotency_key,available_at)
                           VALUES(?,?,?,?,?,?,?)''',(jid,job_type,json.dumps(payload or {}),int(priority),int(max_attempts),idempotency_key or None,available))
        return jid
    except Exception:
        if idempotency_key:
            row=m.one('SELECT id FROM v12_worker_jobs WHERE idempotency_key=?',(idempotency_key,))
            if row:return row['id']
        raise

def _now()->dt.datetime:return dt.datetime.now(dt.UTC)

def claim(owner:str,lease_seconds:int=120):
    initialise();now=_now();until=(now+dt.timedelta(seconds=lease_seconds)).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    # Claim optimistically. PostgreSQL deployments can run several workers because the update condition is atomic.
    candidates=m.rows("SELECT id,job_type FROM v12_worker_jobs WHERE ((status IN ('Queued','Retry') AND available_at<=CURRENT_TIMESTAMP) OR (status='Running' AND lease_until IS NOT NULL AND lease_until<CURRENT_TIMESTAMP)) ORDER BY priority,created_at LIMIT 10")
    for row in candidates:
        duration=max(lease_seconds,21600 if row['job_type']=='launch.photoshoot' else 1200) if row['job_type'].startswith('launch.') else lease_seconds
        until=(_now()+dt.timedelta(seconds=duration)).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        with m.connect() as con:
            cur=con.execute("UPDATE v12_worker_jobs SET status='Running',lease_owner=?,lease_until=?,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND (((status IN ('Queued','Retry')) AND available_at<=CURRENT_TIMESTAMP AND (lease_until IS NULL OR lease_until<CURRENT_TIMESTAMP)) OR (status='Running' AND lease_until IS NOT NULL AND lease_until<CURRENT_TIMESTAMP))",(owner,until,row['id']))
            changed=getattr(cur,'rowcount',0)
        if changed:
            return m.one('SELECT * FROM v12_worker_jobs WHERE id=?',(row['id'],))
    return None

def complete(job_id:str):
    with m.connect() as con:con.execute("UPDATE v12_worker_jobs SET status='Completed',lease_owner='',lease_until=NULL,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(job_id,))

def fail(job:dict,exc:Exception):
    attempts=int(job.get('attempts') or 1);max_attempts=int(job.get('max_attempts') or 5)
    status='DeadLetter' if attempts>=max_attempts else 'Retry';delay=min(60,2**min(attempts,6))
    available=(_now()+dt.timedelta(minutes=delay)).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    with m.connect() as con:con.execute("UPDATE v12_worker_jobs SET status=?,available_at=?,lease_owner='',lease_until=NULL,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,available,str(exc)[:4000],job['id']))
    if job.get('job_type')=='integration.webhook.sync':
        try:
            payload=json.loads(job.get('payload_json') or '{}');rid=payload.get('receipt_id')
            if rid:
                with m.connect() as con:con.execute('UPDATE v9_webhook_receipts SET status=? WHERE id=?',('DeadLetter' if status=='DeadLetter' else 'Retry',rid))
        except Exception as webhook_exc:
            observability.log('worker.webhook_receipt_update_failed',job_id=job.get('id'),error=str(webhook_exc))
    if status=='DeadLetter':
        # A terminal job failure is a business exception, not merely a log line.
        # Keep the incident detail non-secret and point the owner to recovery.
        try:
            import operating_core as oc
            oc.incident('durable_worker','Error','Background job failed after all retries',
                        f"{job.get('job_type') or 'Background job'} / {type(exc).__name__}",
                        'Open System health, fix the underlying issue, then retry or repeat the affected operation.',
                        'worker_job',str(job.get('id') or ''))
        except Exception as incident_exc:
            observability.log('worker.incident_create_failed',job_id=job.get('id'),error=str(incident_exc))
        observability.log('worker.dead_lettered',job_id=job.get('id'),job_type=job.get('job_type'),attempts=attempts)

def _execute(job:dict):
    payload=json.loads(job.get('payload_json') or '{}');typ=job['job_type']
    if typ in {'launch.prepare','launch.photoshoot'}:
        import launch_studio as launch
        pending=m.one('SELECT * FROM launch_jobs WHERE id=?',(payload['launch_job_id'],))
        if not pending:return
        if pending['status']=='Running':
            # Never replay a paid image job or uncertain store creation after a crash.
            with m.connect() as con:
                con.execute("UPDATE launch_jobs SET status='Failed',message='Preparation was interrupted. Review the draft and any store delivery before retrying.',finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='Running'",(pending['id'],))
            return
        launch.run_job(pending)
        return
    if typ=='scheduler.tick':
        import platform_core as pc;pc.run_due_schedules();return
    if typ=='business.jobs':
        import business_os as bos;bos.process_jobs();return
    if typ=='growth.recommendations':
        import business_os as bos;bos.generate_recommendations();return
    if typ=='product.inbox':
        import product_engine as pe;pe.process_inbox_once();return
    if typ=='creative.queue':
        import creative_engine as ce;ce.process_queue_once();return
    if typ=='integration.sync':
        import integration_v14 as int14;int14.initialise();int14.patch_legacy();int14.sync_connection(payload['connection_id']);return
    if typ=='integration.webhook.sync':
        import integration_v14 as int14;int14.initialise();int14.patch_legacy();int14.sync_connection(payload['connection_id'])
        if payload.get('receipt_id'):
            with m.connect() as con:con.execute("UPDATE v9_webhook_receipts SET status='Processed' WHERE id=?",(payload['receipt_id'],))
        return
    if typ=='media.sync':
        import media_store;media_store.sync_tree();return
    if typ=='v13.event.dispatch':
        import operating_core as oc;oc.dispatch_event(payload['event_id']);return
    if typ=='v13.product.pipeline':
        import operating_core as oc;oc.launch_product_pipeline(payload['product_id'],payload.get('channels'),payload.get('automation_level'));return
    if typ=='v13.rule.action':
        import operating_core as oc;oc.execute_delayed_rule(payload['rule_id'],payload['event_id']);return
    if typ=='v17.process.advance':
        import process_orchestrator as po;po.refresh_process(payload['process_id']);return
    if typ=='v17.operations.refresh':
        import process_orchestrator as po;po.refresh_all(int(payload.get('limit') or 100));return
    raise ValueError('Unknown worker job type: '+typ)

def work_once(owner:str='') -> bool:
    owner=owner or (socket.gethostname()+':'+str(os.getpid()))
    job=claim(owner)
    if not job:return False
    try:
        _execute(job);complete(job['id']);observability.log('worker.completed',job_id=job['id'],job_type=job['job_type']);return True
    except Exception as exc:
        fail(job,exc);observability.log('worker.failed',job_id=job['id'],job_type=job['job_type'],error=str(exc));return True

def run_local(stop_event, poll_seconds:float=2.0):
    """Run the durable queue inside the local desktop app only.

    Production uses the separate worker service. This local loop keeps the owner's
    upload -> event -> preparation workflow automatic without requiring a second
    Terminal window, while preserving the same persistent queue semantics.
    """
    initialise();import integration_v14 as int14;int14.initialise();int14.patch_legacy();owner=socket.gethostname()+':local:'+str(os.getpid());last_maintenance=0.0;last_health=0.0
    while not stop_event.is_set():
        worked=False
        try:
            for _ in range(8):
                if not work_once(owner):break
                worked=True
            now=time.monotonic()
            if now-last_maintenance>=30:
                try:
                    import operating_core as oc, business_os as bos
                    oc.process_pending_events(50);oc.scan_inventory_events();bos.generate_recommendations()
                    import process_orchestrator as po
                    po.refresh_all(60)
                except Exception as exc:observability.log('local_worker.maintenance_failed',error=str(exc))
                last_maintenance=now
            if now-last_health>=900:
                try:int14.run_health_checks(active=True)
                except Exception as exc:observability.log('local_worker.health_failed',error=str(exc))
                last_health=now
        except Exception as exc:observability.log('local_worker.failed',error=str(exc))
        stop_event.wait(0.2 if worked else poll_seconds)

def run_forever():
    initialise();import integration_v14 as int14;int14.initialise();int14.patch_legacy();owner=socket.gethostname()+':'+str(os.getpid());observability.log('worker.started',owner=owner)
    next_tick=0.0;next_health=0.0
    while True:
        now=time.monotonic()
        if now>=next_tick:
            try:
                import platform_core as pc, business_os as bos, creative_engine as ce, operating_core as oc
                pc.run_due_schedules();bos.process_jobs();oc.process_pending_events(30);oc.scan_inventory_events();ce.process_queue_once(3)
                bos.generate_recommendations()
                import process_orchestrator as po
                po.refresh_all(100)
            except Exception as exc:
                observability.log('worker.periodic_failed',error=str(exc))
            next_tick=now+30.0
        if now>=next_health:
            try:int14.run_health_checks(active=True)
            except Exception as exc:observability.log('worker.health_failed',error=str(exc))
            next_health=now+900.0
        if not work_once(owner):time.sleep(rc.WORKER_POLL_SECONDS)

if __name__=='__main__':run_forever()
