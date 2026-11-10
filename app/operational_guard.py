from __future__ import annotations

"""Reliability helpers for secondary handoff failures.

A completed primary transaction must not be rolled back because a secondary
notification/touchpoint/event failed.  At the same time the secondary failure must
never disappear.  V54 records one canonical owner incident first and falls back to
the legacy failure store only if the canonical incident store itself is unavailable.
"""

import hashlib


def _dedupe_key(source: str, title: str, entity_type: str, entity_id: str) -> str:
    raw='|'.join([str(source or ''),str(entity_type or ''),str(entity_id or ''),str(title or '')])
    return 'side-effect:'+hashlib.sha256(raw.encode()).hexdigest()


def record_side_effect_failure(source: str, title: str, exc: Exception | str, *,
                               recovery: str='', entity_type: str='', entity_id: str='',
                               severity: str='Warning', action_url: str='/system-health') -> None:
    detail=str(exc)[:4000]
    stable=_dedupe_key(source,title,entity_type,entity_id)
    try:
        import operating_core as oc
        oc.incident(source,severity,title,detail,recovery,entity_type,entity_id,dedupe_key=stable)
        return
    except Exception:
        # Fall through to the legacy failure ledger only when the canonical incident
        # store cannot be written.  Writing both stores would double-count one fault.
        pass
    try:
        import business_os as bos
        bos.failure(source,detail,recovery,entity_type,entity_id,
                    'Error' if severity in {'Error','Critical'} else 'Warning',dedupe_key=stable)
        return
    except Exception:
        pass
    try:
        import marketing as m
        m.audit('side_effect.failure',entity_id,(source+' | '+title+' | '+detail)[:1800])
    except Exception:
        # Last-resort logging cannot mask the already-completed primary transaction.
        pass
