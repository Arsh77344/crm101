from __future__ import annotations

"""V42 capability-aware AI routing, pre-flight validation and failure truth.

This module is intentionally provider-facing rather than page-facing.  Business
workflows ask for a capability; the router resolves the configured provider/model,
validates that the capability is usable, classifies failures and decides whether a
retry or approved fallback is safe.  A failed pre-flight never creates business data.
"""

import datetime as dt
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

CAPABILITY_ROUTES: dict[str,str] = {
    'creative_master':'image_preserve',
    'image_generation':'image_preserve',
    'image_fidelity':'product_understanding',
    'product_understanding':'product_understanding',
    'product_copy':'product_copy',
    'marketing_copy':'marketing_copy',
    'seo':'seo_strategy',
    'seo_strategy':'seo_strategy',
    'crm_intelligence':'crm_intelligence',
    'sales_recommendations':'crm_intelligence',
    'business_analytics':'business_analytics',
    'translation':'translation',
    'customer_service':'customer_service',
    'voiceover':'voiceover',
    'video_generation':'video_generation',
}

RETRYABLE_CATEGORIES={'timeout','network','rate_limit','provider_unavailable'}
NON_RETRYABLE_CATEGORIES={'missing_credentials','authentication','invalid_model','invalid_request','unsupported_capability','quota','file_missing','persistence'}


def _m():
    import marketing
    return marketing


def _bos():
    import business_os
    return business_os


def _oc():
    import operating_core
    return operating_core


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')


def initialise() -> None:
    m=_m()
    with m.connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS v42_ai_validation(
          task_key TEXT PRIMARY KEY,
          route_key TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          status TEXT NOT NULL,
          detail TEXT DEFAULT '',
          available_models_json TEXT NOT NULL DEFAULT '[]',
          checked_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS v42_ai_failure_groups(
          signature TEXT PRIMARY KEY,
          task_key TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT DEFAULT '',
          error_category TEXT NOT NULL,
          failure_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
          last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
          latest_usage_id TEXT DEFAULT '',
          resolved INTEGER NOT NULL DEFAULT 0
        );
        ''')
        # Existing databases need richer usage evidence without replacing the ledger.
        try:
            import db_layer
            if db_layer.USING_POSTGRES:
                cols={r['column_name'] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='v13_ai_usage'")}
            else:
                cols={r['name'] for r in con.execute('PRAGMA table_info(v13_ai_usage)')}
        except Exception:
            cols=set()
        additions={
            'error_category':'TEXT DEFAULT \'\'', 'retryable':'INTEGER DEFAULT 0',
            'attempts':'INTEGER DEFAULT 1', 'provider_request_id':'TEXT DEFAULT \'\'',
            'duration_ms':'INTEGER DEFAULT 0', 'related_url':'TEXT DEFAULT \'\'',
            'failure_signature':'TEXT DEFAULT \'\''
        }
        for name,decl in additions.items():
            if name not in cols:
                try: con.execute(f'ALTER TABLE v13_ai_usage ADD COLUMN {name} {decl}')
                except Exception: pass


def route_key(task_key: str) -> str:
    return CAPABILITY_ROUTES.get(str(task_key or '').strip(),str(task_key or '').strip())


def route(task_key: str, default_model: str='') -> dict[str,Any]:
    key=route_key(task_key)
    try:r=_bos().model_route(key) or {}
    except Exception:r={}
    return {
        'task_key':task_key,'route_key':key,
        'provider':str(r.get('provider') or 'OpenAI'),
        'model':str(r.get('model') or default_model),
        'fallback_model':str(r.get('fallback_model') or ''),
        'enabled':bool(int(r.get('enabled',1) or 0)) if str(r.get('enabled',1)).isdigit() else bool(r.get('enabled',True)),
    }


def classify_failure(*,http_code: int|None=None, detail: str='', exc: Exception|None=None) -> dict[str,Any]:
    raw=(detail or str(exc or '') or '').strip()
    lower=raw.lower()
    category='provider_error'; retryable=False; owner='AI request failed.'
    if http_code in {401,403} or re.search(r'\b(unauthori[sz]ed|invalid api key|authentication|permission denied)\b',lower):
        category='authentication';owner='The AI connection was rejected. Reconnect or correct the provider credentials.'
    elif http_code==404 or re.search(r'\b(model.*(not found|does not exist|unavailable)|invalid model)\b',lower):
        category='invalid_model';owner='The selected AI model is unavailable for this account. Choose a validated model or fallback.'
    elif http_code==429 and re.search(r'quota|billing|insufficient',lower):
        category='quota';owner='The AI account has no usable quota/billing capacity for this request.'
    elif http_code==429:
        category='rate_limit';retryable=True;owner='The AI provider is temporarily rate limiting requests. Retry later or use an approved fallback.'
    elif http_code and 500 <= http_code <= 599:
        category='provider_unavailable';retryable=True;owner='The AI provider is temporarily unavailable.'
    elif http_code in {400,405,409,415,422} or re.search(r'unsupported|invalid request|invalid parameter|bad request',lower):
        category='invalid_request';owner='The AI request is not valid for the selected model/capability. It will not be retried unchanged.'
    elif isinstance(exc,TimeoutError) or re.search(r'timeout|timed out',lower):
        category='timeout';retryable=True;owner='The AI request timed out before completion.'
    elif isinstance(exc,OSError) or re.search(r'network|connection reset|name or service|temporary failure',lower):
        category='network';retryable=True;owner='The AI provider could not be reached.'
    elif re.search(r'credential|api key.*missing|not connected',lower):
        category='missing_credentials';owner='AI is not connected for this installation.'
    elif re.search(r'file.*(missing|not found)|input.*file',lower):
        category='file_missing';owner='One or more AI input files are unavailable.'
    retryable=retryable and category not in NON_RETRYABLE_CATEGORIES
    return {'category':category,'retryable':retryable,'owner_message':owner,'technical_detail':raw[:4000]}


def _sync_marketing_health(task_key: str, info: dict, model: str='') -> None:
    """Synchronise provider/account failures into the shared owner-facing AI health.

    The historic function name is retained for compatibility. Provider-wide failures
    (auth, quota, rate limits, outages, network and missing credentials) affect every
    AI capability and therefore must surface regardless of which workflow discovered
    them. Model-unavailable is only promoted to the shared marketing-model status when
    the marketing capability itself is affected.
    """
    category=info.get('category')
    mapping={
        'authentication':'Needs attention',
        'quota':'Billing / quota issue',
        'rate_limit':'Rate limited',
        'provider_unavailable':'Provider unavailable',
        'timeout':'Provider unavailable',
        'network':'Needs attention',
        'missing_credentials':'Not connected',
    }
    if category=='invalid_model' and task_key=='marketing_copy':
        status='Model unavailable'
    elif category in mapping:
        status=mapping[category]
    elif task_key=='marketing_copy':
        status='Needs attention'
    else:
        return
    try:
        _m().set_ai_health(status,info.get('owner_message','AI request failed.'),model)
    except Exception:
        pass


def _signature(task_key: str, provider: str, model: str, category: str, detail: str) -> str:
    normalized=re.sub(r'\b[0-9a-f]{8,}\b','<id>',(detail or '').lower())
    normalized=re.sub(r'\d+','<n>',normalized)[:600]
    return hashlib.sha256('|'.join([task_key,provider,model,category,normalized]).encode()).hexdigest()


def record_failure(task_key: str, provider: str, model: str, *, error: str, http_code: int|None=None,
                   object_type: str='', object_id: str='', attempts: int=1, duration_ms: int=0,
                   provider_request_id: str='', related_url: str='') -> str:
    initialise();info=classify_failure(http_code=http_code,detail=error);sig=_signature(task_key,provider,model,info['category'],error)
    aid=_oc().record_ai_usage(task_key,provider,model,'Failed',object_type,object_id,error=error,
                              error_category=info['category'],retryable=info['retryable'],attempts=attempts,
                              provider_request_id=provider_request_id,duration_ms=duration_ms,related_url=related_url,
                              failure_signature=sig)
    m=_m()
    with m.connect() as con:
        con.execute('''INSERT INTO v42_ai_failure_groups(signature,task_key,provider,model,error_category,failure_count,latest_usage_id,resolved)
                       VALUES(?,?,?,?,?,1,?,0)
                       ON CONFLICT(signature) DO UPDATE SET failure_count=failure_count+1,last_seen_at=CURRENT_TIMESTAMP,latest_usage_id=excluded.latest_usage_id,resolved=0''',
                    (sig,task_key,provider,model,info['category'],aid))
    try:
        _bos().recommendation('AI','AI '+task_key.replace('_',' ')+' unavailable',info['owner_message'],'High','/ai-governance',
                              dedupe_key='v42-ai-failure:'+task_key+':'+info['category'])
    except Exception as exc:
        from operational_guard import record_side_effect_failure
        record_side_effect_failure('ai_router','AI failure was recorded but owner recommendation could not be created',exc,recovery='Open AI Governance and System health to inspect the recorded AI failure.',entity_type=object_type,entity_id=object_id,severity='Error',action_url='/ai-governance')
    return aid


def record_success(task_key: str, provider: str, model: str, *, object_type: str='', object_id: str='',
                   input_units: int=0, output_units: int=0, image_count: int=0, video_seconds: float=0,
                   estimated_cost: float=0, duration_ms: int=0, provider_request_id: str='', related_url: str='', attempts: int=1) -> str:
    initialise()
    return _oc().record_ai_usage(task_key,provider,model,'Completed',object_type,object_id,input_units,output_units,
                                 image_count,video_seconds,estimated_cost,'',error_category='',retryable=False,attempts=attempts,
                                 provider_request_id=provider_request_id,duration_ms=duration_ms,related_url=related_url)


def _models(key: str, timeout: int=20) -> tuple[set[str],str]:
    req=urllib.request.Request('https://api.openai.com/v1/models',headers={'Authorization':'Bearer '+key},method='GET')
    with urllib.request.urlopen(req,timeout=timeout) as res:
        data=json.load(res)
    return {str(x.get('id') or '') for x in (data.get('data') or []) if isinstance(x,dict)},str(getattr(res,'headers',{}).get('x-request-id',''))


def validate_capability(task_key: str, *, force: bool=False, default_model: str='') -> dict[str,Any]:
    initialise();r=route(task_key,default_model);m=_m();key=m.secret()
    result={**r,'status':'Configuration required','detail':'','ready':False,'checked_at':'','fallback_ready':False}
    if not r['enabled']:
        result['detail']='This AI capability is disabled in Advanced AI routing.';return result
    if r['provider'].lower()!='openai':
        result['detail']='This release has no validated execution adapter for '+r['provider']+'.';return result
    if not key:
        result['detail']='No OpenAI API key is configured.';return result
    # A successful owner-triggered marketing AI connection test is already a live
    # provider/model validation. Reuse that recent proof rather than making a second
    # /models request before every paid generation. This keeps pre-flight truthful
    # while avoiding a duplicated network dependency immediately before execution.
    if task_key=='marketing_copy' and not force:
        try:
            health=m.ai_health(False,r['model'])
            checked=str(health.get('checked_at') or '')
            age=999999
            if checked:
                age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(checked.replace('Z','+00:00'))).total_seconds()
            if health.get('status')=='Connected' and health.get('model')==r['model'] and age < 900:
                return {**result,'model':r['model'],'preferred_model':r['model'],'using_fallback':False,
                        'status':'Ready','detail':'Recent live connection test verified provider credentials and model access.',
                        'ready':True,'checked_at':checked,'fallback_ready':False}
        except Exception:
            pass
    cached=m.one('SELECT * FROM v42_ai_validation WHERE task_key=?',(task_key,))
    if cached and not force:
        try:
            checked=dt.datetime.fromisoformat(str(cached['checked_at']).replace('Z','+00:00'))
            if checked.tzinfo is None:checked=checked.replace(tzinfo=dt.timezone.utc)
            age=(dt.datetime.now(dt.timezone.utc)-checked).total_seconds()
            available=set(json.loads(cached.get('available_models_json') or '[]'))
        except (ValueError,TypeError):age=999999
        if age < 900 and cached.get('model')==r['model']:
            fallback_ready=bool(r['fallback_model'] and r['fallback_model'] in available)
            using_fallback=bool(r['model'] not in available and fallback_ready)
            effective_model=r['fallback_model'] if using_fallback else r['model']
            return {**result,'model':effective_model,'preferred_model':r['model'],'using_fallback':using_fallback,
                    'status':cached['status'],'detail':cached['detail'],'ready':cached['status']=='Ready',
                    'checked_at':cached['checked_at'],'fallback_ready':fallback_ready}
    try:
        ids,_=_models(key)
        fallback_ready=bool(r['fallback_model'] and r['fallback_model'] in ids)
        effective_model=r['model']
        using_fallback=False
        if not r['model']:
            status='Configuration required';detail='No model is configured for this capability.'
        elif r['model'] not in ids and fallback_ready:
            status='Ready';effective_model=r['fallback_model'];using_fallback=True;detail='Preferred model '+r['model']+' is unavailable; validated fallback '+effective_model+' will be used.'
        elif r['model'] not in ids:
            status='Configuration required';detail='Configured model '+r['model']+' was not returned for this API account.'
        else:
            status='Ready';detail='Provider credentials and model availability were validated.'
        with m.connect() as con:
            con.execute('''INSERT INTO v42_ai_validation(task_key,route_key,provider,model,status,detail,available_models_json,checked_at)
                           VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                           ON CONFLICT(task_key) DO UPDATE SET route_key=excluded.route_key,provider=excluded.provider,model=excluded.model,status=excluded.status,detail=excluded.detail,available_models_json=excluded.available_models_json,checked_at=CURRENT_TIMESTAMP''',
                        (task_key,r['route_key'],r['provider'],r['model'],status,detail,json.dumps(sorted(ids)[:500])))
        return {**result,'model':effective_model,'preferred_model':r['model'],'using_fallback':using_fallback,'status':status,'detail':detail,'ready':status=='Ready','checked_at':_utc(),'fallback_ready':fallback_ready}
    except urllib.error.HTTPError as exc:
        try:payload=exc.read(8192).decode('utf-8','replace')
        except Exception:payload=''
        info=classify_failure(http_code=exc.code,detail=payload)
        _sync_marketing_health(task_key,info,r.get('model',''))
        status='Temporarily unavailable' if info['retryable'] else 'Configuration required'
        return {**result,'status':status,'detail':info['owner_message'],'ready':False,'checked_at':_utc(),'error_category':info['category']}
    except Exception as exc:
        info=classify_failure(exc=exc,detail=str(exc));_sync_marketing_health(task_key,info,r.get('model',''));status='Temporarily unavailable' if info['retryable'] else 'Configuration required'
        return {**result,'status':status,'detail':info['owner_message'],'ready':False,'checked_at':_utc(),'error_category':info['category']}


def preflight(task_key: str, *, object_type: str='', object_id: str='', input_paths: list[str]|None=None,
              force_validation: bool=False, default_model: str='') -> dict[str,Any]:
    input_paths=input_paths or []
    import os
    missing=[p for p in input_paths if p and not os.path.exists(p)]
    if missing:
        raise ValueError('AI pre-flight failed: '+str(len(missing))+' required input file(s) are missing. Nothing was queued.')
    state=validate_capability(task_key,force=force_validation,default_model=default_model)
    if not state['ready']:
        raise ValueError('AI pre-flight failed: '+state['detail']+' Nothing was queued.')
    return state


def fallback_for(task_key: str) -> str:
    r=route(task_key);return r.get('fallback_model') or ''


def retry_decision(task_key: str, *, http_code: int|None=None, error: str='', attempt: int=1, max_attempts: int=3) -> dict[str,Any]:
    info=classify_failure(http_code=http_code,detail=error)
    retry=bool(info['retryable'] and attempt < max_attempts)
    delay=min(30,2 ** max(0,attempt-1)) if retry else 0
    fb=fallback_for(task_key) if not retry else ''
    return {**info,'retry':retry,'delay_seconds':delay,'fallback_model':fb}


def request_json(task_key: str, body: dict, *, timeout: int=90, object_type: str='', object_id: str='', max_attempts: int=3) -> tuple[dict,int,int]:
    """Execute one OpenAI Responses request with classified bounded retries.

    Permanent configuration/request failures stop immediately. Transient provider,
    network, timeout and rate-limit failures use bounded exponential backoff. The
    returned tuple is (response, attempts, duration_ms).
    """
    key=_m().secret()
    if not key:raise ValueError('AI is not connected. Nothing was queued.')
    model=str(body.get('model') or ((body.get('tools') or [{}])[0].get('model') if body.get('tools') else ''))
    start=time.monotonic();last=''
    for attempt in range(1,max(1,max_attempts)+1):
        req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(body).encode('utf-8'),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=timeout) as res:
                out=json.load(res)
            return out,attempt,int((time.monotonic()-start)*1000)
        except urllib.error.HTTPError as exc:
            try:payload=exc.read(8192).decode('utf-8','replace')
            except Exception:payload=''
            last='HTTP '+str(exc.code)+': '+payload
            decision=retry_decision(task_key,http_code=exc.code,error=payload,attempt=attempt,max_attempts=max_attempts)
            _sync_marketing_health(task_key,decision,model)
            if decision['retry']:
                time.sleep(decision['delay_seconds']);continue
            duration=int((time.monotonic()-start)*1000)
            record_failure(task_key,'OpenAI',model,error=last,http_code=exc.code,object_type=object_type,object_id=object_id,attempts=attempt,duration_ms=duration)
            raise ValueError(decision['owner_message']+' No business data was changed.') from None
        except (OSError,TimeoutError) as exc:
            last=str(exc) or exc.__class__.__name__;decision=retry_decision(task_key,error=last,attempt=attempt,max_attempts=max_attempts)
            _sync_marketing_health(task_key,decision,model)
            if decision['retry']:
                time.sleep(decision['delay_seconds']);continue
            duration=int((time.monotonic()-start)*1000)
            record_failure(task_key,'OpenAI',model,error=last,object_type=object_type,object_id=object_id,attempts=attempt,duration_ms=duration)
            raise ValueError(decision['owner_message']+' No business data was changed.') from None
    duration=int((time.monotonic()-start)*1000)
    record_failure(task_key,'OpenAI',model,error=last or 'Unknown provider failure',object_type=object_type,object_id=object_id,attempts=max_attempts,duration_ms=duration)
    raise ValueError('AI request failed after bounded retries. No business data was changed.')


def capability_matrix(force: bool=False) -> list[dict[str,Any]]:
    keys=['product_understanding','marketing_copy','seo_strategy','image_preserve','crm_intelligence','translation']
    return [validate_capability(k,force=force) for k in keys]


def provider_preflight(task_key: str, provider: str, model: str, *, credential_present: bool, object_type: str='', object_id: str='') -> dict[str,Any]:
    """Fail-fast configuration preflight for non-OpenAI/provider-specific adapters.

    This does not claim live readiness. Live readiness is established only by a
    successful provider operation and recorded usage/health evidence.
    """
    provider=str(provider or '').strip();model=str(model or '').strip()
    if not credential_present:
        info={'category':'missing_credentials','retryable':False,'owner_message':provider+' AI is not connected.','technical_detail':'Missing provider credential'}
        return {'ready':False,'status':'Configuration required','provider':provider,'model':model,**info}
    if not model:
        info={'category':'invalid_model','retryable':False,'owner_message':'No model is configured for this AI capability.','technical_detail':'Empty model'}
        return {'ready':False,'status':'Configuration required','provider':provider,'model':model,**info}
    return {'ready':True,'status':'Configured — live validation required','provider':provider,'model':model,'task_key':task_key,
            'detail':'Credentials and model are configured. A real provider operation is still required before this capability is treated as operational.'}


def request_provider_json(task_key: str, provider: str, model: str, url: str, *, method: str='POST', headers: dict|None=None,
                          payload: dict|None=None, timeout: int=90, object_type: str='', object_id: str='', max_attempts: int=3) -> tuple[dict,int,int]:
    """Provider-neutral JSON request with the same failure taxonomy and bounded retry."""
    start=time.monotonic();last='';headers=headers or {}
    data=None if payload is None else json.dumps(payload).encode('utf-8')
    for attempt in range(1,max(1,max_attempts)+1):
        req=urllib.request.Request(url,data=data,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=timeout) as res:
                out=json.load(res)
            return out,attempt,int((time.monotonic()-start)*1000)
        except urllib.error.HTTPError as exc:
            try:body=exc.read(8192).decode('utf-8','replace')
            except Exception:body=''
            last='HTTP '+str(exc.code)+': '+body
            decision=retry_decision(task_key,http_code=exc.code,error=body,attempt=attempt,max_attempts=max_attempts)
            if decision['retry']:
                time.sleep(decision['delay_seconds']);continue
            duration=int((time.monotonic()-start)*1000)
            record_failure(task_key,provider,model,error=last,http_code=exc.code,object_type=object_type,object_id=object_id,attempts=attempt,duration_ms=duration)
            raise ValueError(decision['owner_message']+' No business data was changed.') from None
        except (OSError,TimeoutError) as exc:
            last=str(exc) or exc.__class__.__name__
            decision=retry_decision(task_key,error=last,attempt=attempt,max_attempts=max_attempts)
            if decision['retry']:
                time.sleep(decision['delay_seconds']);continue
            duration=int((time.monotonic()-start)*1000)
            record_failure(task_key,provider,model,error=last,object_type=object_type,object_id=object_id,attempts=attempt,duration_ms=duration)
            raise ValueError(decision['owner_message']+' No business data was changed.') from None
    duration=int((time.monotonic()-start)*1000)
    record_failure(task_key,provider,model,error=last or 'Unknown provider failure',object_type=object_type,object_id=object_id,attempts=max_attempts,duration_ms=duration)
    raise ValueError('AI provider request failed after bounded retries. No business data was changed.')


def request_provider_bytes(task_key: str, provider: str, model: str, url: str, *, method: str='POST', headers: dict|None=None,
                           payload: dict|None=None, timeout: int=90, object_type: str='', object_id: str='', max_attempts: int=3) -> tuple[bytes,int,int]:
    """Provider-neutral binary request used by speech/video downloads."""
    start=time.monotonic();last='';headers=headers or {}
    data=None if payload is None else json.dumps(payload).encode('utf-8')
    for attempt in range(1,max(1,max_attempts)+1):
        req=urllib.request.Request(url,data=data,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=timeout) as res:
                raw=res.read()
            return raw,attempt,int((time.monotonic()-start)*1000)
        except urllib.error.HTTPError as exc:
            try:body=exc.read(8192).decode('utf-8','replace')
            except Exception:body=''
            last='HTTP '+str(exc.code)+': '+body
            decision=retry_decision(task_key,http_code=exc.code,error=body,attempt=attempt,max_attempts=max_attempts)
            if decision['retry']:
                time.sleep(decision['delay_seconds']);continue
            duration=int((time.monotonic()-start)*1000)
            record_failure(task_key,provider,model,error=last,http_code=exc.code,object_type=object_type,object_id=object_id,attempts=attempt,duration_ms=duration)
            raise ValueError(decision['owner_message']+' No business data was changed.') from None
        except (OSError,TimeoutError) as exc:
            last=str(exc) or exc.__class__.__name__
            decision=retry_decision(task_key,error=last,attempt=attempt,max_attempts=max_attempts)
            if decision['retry']:
                time.sleep(decision['delay_seconds']);continue
            duration=int((time.monotonic()-start)*1000)
            record_failure(task_key,provider,model,error=last,object_type=object_type,object_id=object_id,attempts=attempt,duration_ms=duration)
            raise ValueError(decision['owner_message']+' No business data was changed.') from None
    duration=int((time.monotonic()-start)*1000)
    record_failure(task_key,provider,model,error=last or 'Unknown provider failure',object_type=object_type,object_id=object_id,attempts=max_attempts,duration_ms=duration)
    raise ValueError('AI provider request failed after bounded retries. No business data was changed.')
