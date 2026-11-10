from __future__ import annotations

"""Idempotent migration/repair steps for V54 operational truth.

These repairs only close stale symptoms of defects that V54 fixes in code. They do
not delete business history or infer customer/commercial facts.
"""
import marketing as m
import operating_core as oc
import business_os as bos


def initialise() -> dict:
    # Direct upgrades from V52 are supported. Ensure additive V53/V54 columns
    # exist before this repair code references last_seen/latest_error.
    oc.initialise()
    bos.initialise()
    repaired={'stale_recommendation_incidents':0,'lead_consent_steps':0,'lead_processes':0}
    # Historical V52/V53 automation incidents caused specifically by the old
    # recommendation UNIQUE-constraint bug are no longer actionable after the
    # atomic recommendation upsert fix. Preserve them as resolved history.
    if m.table_exists('v13_incidents'):
        with m.connect() as con:
            cur=con.execute("""UPDATE v13_incidents
                SET status='Resolved',resolved_at=coalesce(resolved_at,CURRENT_TIMESTAMP),last_seen=coalesce(last_seen,CURRENT_TIMESTAMP)
                WHERE status='Open' AND title IN ('Automation rule failed','Delayed automation rule failed')
                  AND (coalesce(detail,'') LIKE '%v9_recommendations.dedupe_key%'
                       OR coalesce(latest_error,'') LIKE '%v9_recommendations.dedupe_key%')""")
            repaired['stale_recommendation_incidents']=max(0,int(cur.rowcount or 0))
    # V52 treated missing positive marketing permission as a process failure. It is
    # a normal waiting business state. Normalize only that exact step/state.
    if m.table_exists('v17_process_steps') and m.table_exists('v17_processes'):
        with m.connect() as con:
            cur=con.execute("""UPDATE v17_process_steps SET status='Waiting',
                    detail='No positive marketing permission is recorded. Marketing outreach stays blocked until a permitted route or verified permission exists.',
                    updated_at=CURRENT_TIMESTAMP
                WHERE step_key='consent' AND status='Needs attention'
                  AND process_id IN (SELECT id FROM v17_processes WHERE process_type='lead_to_sale')""")
            repaired['lead_consent_steps']=max(0,int(cur.rowcount or 0))
            cur=con.execute("""UPDATE v17_processes SET status='Running',current_step='consent',updated_at=CURRENT_TIMESTAMP
                WHERE process_type='lead_to_sale' AND status='Needs attention'
                  AND NOT EXISTS (SELECT 1 FROM v17_process_steps s WHERE s.process_id=v17_processes.id AND s.status IN ('Blocked','Needs attention'))""")
            repaired['lead_processes']=max(0,int(cur.rowcount or 0))
    return repaired
