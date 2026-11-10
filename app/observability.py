from __future__ import annotations
import datetime as dt
import json
import logging
import os
import sys
import uuid

_LEVEL=os.environ.get('LOG_LEVEL','INFO').upper()
logging.basicConfig(level=getattr(logging,_LEVEL,logging.INFO),stream=sys.stdout,format='%(message)s')
logger=logging.getLogger('commerce_crm')

def log(event:str,**fields):
    payload={'ts':dt.datetime.now(dt.UTC).isoformat().replace('+00:00','Z'),'event':event,**fields}
    logger.info(json.dumps(payload,ensure_ascii=False,default=str))

def request_id()->str:return 'REQ-'+uuid.uuid4().hex[:16].upper()
