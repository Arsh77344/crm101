from __future__ import annotations

"""Current Wix commerce adapter for the reconstructed V50 branch.

The adapter follows Wix's current self-managed app OAuth model: a verified app
instance ID is exchanged for a four-hour access token with client_credentials.
It deliberately maps Wix data into the CRM's canonical objects instead of
creating a parallel Wix business model.
"""

import base64
import hashlib
import hmac
import json
import re
from typing import Any

import marketing as m
import integration_layer as legacy
import v35_truth as truth


def _b64url_decode(value: str) -> bytes:
    value=str(value or '').strip()
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def decode_signed_instance(signed_instance: str, app_secret: str) -> dict[str,Any]:
    """Verify and decode Wix's signedInstance/app-instance parameter."""
    raw=str(signed_instance or '').strip()
    if not raw or '.' not in raw: raise ValueError('Wix did not return a valid signed app instance.')
    sig,data=raw.split('.',1)
    expected=hmac.new(app_secret.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).digest()
    try: actual=_b64url_decode(sig)
    except Exception: raise ValueError('Wix app-instance signature could not be decoded.') from None
    if not hmac.compare_digest(actual, expected):
        raise ValueError('Wix app-instance signature did not verify. Start Connect Wix again.')
    try: payload=json.loads(_b64url_decode(data).decode('utf-8'))
    except Exception: raise ValueError('Wix app-instance data could not be decoded.') from None
    instance=str(payload.get('instanceId') or payload.get('instance_id') or '').strip()
    if not instance: raise ValueError('Wix did not return an app instance ID.')
    payload['instanceId']=instance
    return payload


def access_token(connection_id: str, provider_app: dict, provider_secret: str) -> dict:
    c=legacy.connection(connection_id); instance=str(c.get('config',{}).get('instance_id') or '').strip()
    if not instance: raise ValueError('Wix installation is incomplete. Reconnect Wix.')
    if not provider_app.get('client_id') or not provider_secret:
        raise ValueError('Wix application credentials are not configured by the administrator.')
    payload={'grant_type':'client_credentials','client_id':provider_app['client_id'],'client_secret':provider_secret,'instance_id':instance}
    out=legacy.api_json(connection_id,'Wix OAuth access token','https://www.wixapis.com/oauth2/token','POST',{'Content-Type':'application/json'},payload,retries=1)
    token=str((out or {}).get('access_token') or '').strip()
    if not token: raise ValueError('Wix did not issue an access token. Reconnect the Wix site.')
    return {'access_token':token,'expires_in':int((out or {}).get('expires_in') or 14400),'token_type':str((out or {}).get('token_type') or 'Bearer')}


def api(connection_id: str, provider_app: dict, provider_secret: str, operation: str, endpoint: str, method='GET', payload=None) -> Any:
    token=access_token(connection_id,provider_app,provider_secret)['access_token']
    return legacy.api_json(connection_id,operation,'https://www.wixapis.com'+endpoint,method,{'Authorization':token,'Content-Type':'application/json'},payload,retries=2)


def token_info(connection_id: str, provider_app: dict, provider_secret: str) -> dict:
    token=access_token(connection_id,provider_app,provider_secret)['access_token']
    return legacy.api_json(connection_id,'Validate Wix app instance','https://www.wixapis.com/oauth2/token-info','POST',{'Content-Type':'application/json'},{'token':token},retries=1)


def _cursor(response: dict) -> str:
    meta=(response or {}).get('pagingMetadata') or (response or {}).get('metadata') or {}
    curs=(meta.get('cursors') or {}) if isinstance(meta,dict) else {}
    return str(curs.get('next') or meta.get('nextCursor') or '')


def _iter_query(connection_id: str, provider_app: dict, provider_secret: str, endpoint: str, key: str, operation: str, limit=100):
    cursor=''; pages=0
    while pages<200:
        q={'cursorPaging':{'limit':limit}}
        if cursor:q['cursorPaging']['cursor']=cursor
        body={'query':q} if '/contacts/' in endpoint or '/products/' in endpoint or '/inventory-items/' in endpoint else {'search':q}
        out=api(connection_id,provider_app,provider_secret,operation,endpoint,'POST',body) or {}
        for item in out.get(key) or []: yield item
        pages+=1; nxt=_cursor(out)
        if not nxt or nxt==cursor: break
        cursor=nxt


def _first_variant(product: dict) -> dict:
    return (((product.get('variantsInfo') or {}).get('variants')) or [{}])[0] or {}


def _variant_sku(product: dict) -> str:
    v=_first_variant(product)
    return str(v.get('sku') or (v.get('physicalProperties') or {}).get('sku') or '').strip()


def _external_mapping(connection_id: str, object_type: str, external_id: str) -> str:
    r=m.one('SELECT local_id FROM v10_external_objects WHERE connection_id=? AND object_type=? AND external_id=? LIMIT 1',(connection_id,object_type,external_id)) or {}
    return str(r.get('local_id') or '')


def _canonical_product(connection_id: str, product: dict) -> tuple[str,bool]:
    ext=str(product.get('id') or product.get('_id') or '').strip()
    if not ext:return '',False
    mapped=_external_mapping(connection_id,'product',ext)
    if mapped and m.one('SELECT 1 FROM products WHERE product_id=?',(mapped,)):return mapped,False
    sku=_variant_sku(product)
    if sku:
        r=m.one('SELECT product_id FROM products WHERE internal_sku=? OR product_code=? LIMIT 1',(sku,sku)) or {}
        if r.get('product_id'):
            legacy._external_upsert(connection_id,'product',ext,product,'product',r['product_id']);return r['product_id'],False
    # Provider content may create a missing draft identity, but never overwrite an
    # existing CRM-mastered product. Imported records remain Draft/Needs Review.
    import product_engine as pe
    name=str(product.get('name') or 'Imported Wix product').strip()[:180]
    pid=pe.make_product_record(name,{'category':'Wix import'})
    with m.connect() as con:
        con.execute("UPDATE products SET status='Draft',source_product_name=? WHERE product_id=?",(name,pid))
    legacy._external_upsert(connection_id,'product',ext,product,'product',pid)
    return pid,True


def _canonical_contact(connection_id: str, contact: dict) -> tuple[str,bool]:
    ext=str(contact.get('id') or contact.get('_id') or '').strip()
    mapped=_external_mapping(connection_id,'customer',ext) if ext else ''
    if mapped and m.one('SELECT 1 FROM contacts WHERE contact_id=?',(mapped,)):return mapped,False
    email=str(((contact.get('email') or {}).get('email') if isinstance(contact.get('email'),dict) else contact.get('email')) or '').strip()
    phone=str(((contact.get('phone') or {}).get('phone') if isinstance(contact.get('phone'),dict) else contact.get('phone')) or '').strip()
    cid=legacy._match_contact(email,phone)
    created=False
    if not cid:
        import contact_tools as ct
        name=contact.get('name') or {}; first=str(name.get('first') or name.get('firstName') or '').strip(); last=str(name.get('last') or name.get('lastName') or '').strip(); full=str(name.get('full') or ' '.join(x for x in (first,last) if x)).strip()
        raw={'full_name':full,'first_name':first,'last_name':last,'contact_type':'B2C','email':email,'phone_number':phone,'source_name':'Wix','source_reference':ext,'country':'','language':'','username':'','website':'','business_category':'Customer','tags':'Wix'}
        cid=ct.save_contact(raw);created=True
    if ext:legacy._external_upsert(connection_id,'customer',ext,contact,'contact',cid)
    return cid,created


def _order_contact(connection_id: str, order: dict) -> tuple[str,bool]:
    buyer=order.get('buyerInfo') or {}; ext=str(buyer.get('contactId') or '').strip()
    if ext:
        mapped=_external_mapping(connection_id,'customer',ext)
        if mapped:return mapped,False
    email=str(buyer.get('email') or '').strip(); details=((order.get('billingInfo') or {}).get('contactDetails') or {}); phone=str(details.get('phone') or '').strip()
    cid=legacy._match_contact(email,phone)
    if cid:
        if ext:legacy._external_upsert(connection_id,'customer',ext,{'id':ext,'email':{'email':email},'phone':{'phone':phone}},'contact',cid)
        return cid,False
    contact={'id':ext,'email':{'email':email},'phone':{'phone':phone},'name':{'first':details.get('firstName') or '', 'last':details.get('lastName') or ''}}
    return _canonical_contact(connection_id,contact)


def _order_lines(connection_id: str, order: dict) -> list[dict]:
    out=[]
    for line in order.get('lineItems') or []:
        ref=line.get('catalogReference') or {}; ext=str(ref.get('catalogItemId') or '').strip(); pid=_external_mapping(connection_id,'product',ext) if ext else ''
        sku=str((line.get('physicalProperties') or {}).get('sku') or line.get('sku') or '').strip()
        if not pid and sku:
            r=m.one('SELECT product_id FROM products WHERE internal_sku=? OR product_code=? LIMIT 1',(sku,sku)) or {};pid=str(r.get('product_id') or '')
        price=(line.get('price') or line.get('priceData') or line.get('totalPriceAfterTax') or {})
        amount=price.get('amount') if isinstance(price,dict) else price
        try:unit=float(amount or 0)
        except Exception:unit=0.0
        out.append({'product_id':pid,'sku':sku,'external_product_id':ext,'quantity':int(line.get('quantity') or 0),'unit_price':unit})
    return out


def _money(order: dict) -> tuple[float,str]:
    ps=order.get('priceSummary') or {}; total=ps.get('total') or {}; curr=str(order.get('currency') or total.get('currency') or '').strip()
    try:value=float(total.get('amount') or order.get('total') or 0)
    except Exception:value=0.0
    return value,curr


def sync_all(connection_id: str, provider_app: dict, provider_secret: str) -> dict:
    import integration_v14 as v14
    import crm_workspace as cw
    truth.initialise();run=legacy.begin_sync(connection_id,'wix_full');summary={'records_seen':0,'records_created':0,'records_updated':0,'records_skipped':0,'errors':0,'warnings':0,'products':0,'customers':0,'orders':0,'inventory':0,'authority_blocked':0}
    try:
        # Products
        for product in _iter_query(connection_id,provider_app,provider_secret,'/stores/v3/products/query','products','Wix products'):
            summary['records_seen']+=1;summary['products']+=1
            pid,created=_canonical_product(connection_id,product);summary['records_created' if created else 'records_updated']+=1
            legacy._external_upsert(connection_id,'product',str(product.get('id') or product.get('_id') or ''),product,'product',pid)
        # Contacts
        for contact in _iter_query(connection_id,provider_app,provider_secret,'/contacts/v5/contacts/query','contacts','Wix contacts'):
            summary['records_seen']+=1;summary['customers']+=1
            cid,created=_canonical_contact(connection_id,contact);summary['records_created' if created else 'records_updated']+=1
            legacy._external_upsert(connection_id,'customer',str(contact.get('id') or contact.get('_id') or ''),contact,'contact',cid)
        # Inventory items. Apply only when this exact connection is authority and the
        # local product has one unambiguous location.
        for item in _iter_query(connection_id,provider_app,provider_secret,'/stores/v3/inventory-items/query','inventoryItems','Wix inventory',1000):
            summary['records_seen']+=1;summary['inventory']+=1;ext_product=str(item.get('productId') or '')
            pid=_external_mapping(connection_id,'product',ext_product)
            if not pid:summary['records_skipped']+=1;continue
            import record_lifecycle as lifecycle
            if not lifecycle.is_operationally_active_product(pid):
                summary['records_skipped']+=1
                continue
            dec=v14.authority_decision('inventory','Wix',connection_id,'stock_qty',pid)
            if not dec['allowed']:summary['authority_blocked']+=1;continue
            if not bool(item.get('trackQuantity')):summary['records_skipped']+=1;continue
            try:qty=int(item.get('quantity') or 0)
            except Exception:summary['records_skipped']+=1;continue
            reconciled=truth.reconcile_provider_aggregate_stock(pid,qty,'Wix',str(item.get('id') or item.get('_id') or ''))
            if not reconciled.get('applied'):
                summary['authority_blocked']+=1;continue
            summary['records_updated']+=1
        # Orders last, after product/customer mappings.
        for order in _iter_query(connection_id,provider_app,provider_secret,'/ecom/v1/orders/search','orders','Wix orders'):
            summary['records_seen']+=1;summary['orders']+=1;ext=str(order.get('id') or order.get('_id') or '')
            dec=v14.authority_decision('online_order','Wix',connection_id,'order',ext)
            if not dec['allowed']:summary['authority_blocked']+=1;continue
            cid,_=_order_contact(connection_id,order);total,currency=_money(order);payment=str(order.get('paymentStatus') or '');fulfil=str(order.get('fulfillmentStatus') or '');external_ref='Wix:'+ext
            synced=cw.sync_external_order('Wix',connection_id,external_ref,contact_id=cid,total=total,currency=currency,financial_status=payment,fulfilment_status=fulfil,ordered_at=str(order.get('createdDate') or order.get('_createdDate') or ''),lines=_order_lines(connection_id,order))
            oid=synced['order_id'];summary['records_created' if synced.get('created') else 'records_updated']+=1
            legacy._external_upsert(connection_id,'order',ext,order,'order',oid)
            if cid:
                try:
                    import business_os as bos;bos.record_touchpoint(cid,'order.synced','Website','Wix','commerce',value=total,currency=currency,metadata={'external_order_id':ext})
                except Exception as exc:
                    summary['warnings']+=1
                    from operational_guard import record_side_effect_failure
                    record_side_effect_failure('wix_sync','Wix order synced but Customer 360 touchpoint failed',exc,recovery='Retry the Wix sync after reviewing System health. The canonical order was preserved.',entity_type='contact',entity_id=cid,severity='Error')
            if payment.upper() in {'PAID','PARTIALLY_PAID','PARTIALLY_REFUNDED'}:
                try:
                    import operating_core as oc
                    oc.emit_event('ORDER_PLACED','order',oid,{'contact_id':cid,'source':'Wix','external_order_id':ext,'status':payment,'total':total,'currency':currency},dedupe_key='wix-order:'+ext+':'+payment.upper())
                except Exception as exc:
                    summary['warnings']+=1
                    from operational_guard import record_side_effect_failure
                    record_side_effect_failure('wix_sync','Wix order synced but automation event failed',exc,recovery='Retry the Wix sync after reviewing System health. The canonical order was preserved.',entity_type='order',entity_id=oid,severity='Error')
        try:
            import business_os as bos;bos.rebuild_identity_index()
        except Exception as exc:
            summary['warnings']+=1
            from operational_guard import record_side_effect_failure
            record_side_effect_failure('wix_sync','Wix sync completed but identity index rebuild failed',exc,recovery='Open System health and retry the Wix sync. Canonical records were preserved; identity matching needs repair.',severity='Error')
        return legacy.finish_sync(run,summary)
    except Exception as exc:
        summary['errors']+=1;legacy.finish_sync(run,summary,str(exc));raise


def create_product_draft(connection_id: str, provider_app: dict, provider_secret: str, product_id: str) -> dict:
    import record_lifecycle as lifecycle
    p=lifecycle.require_operationally_active_product(product_id)
    price=p.get('retail_price') if p.get('retail_price') not in (None,'') else p.get('price')
    try:price=float(price or 0)
    except Exception:price=0.0
    payload={'product':{'name':str(p.get('public_product_name') or p.get('source_product_name') or p.get('internal_sku') or 'Product')[:180],'productType':'PHYSICAL','physicalProperties':{},'visible':False,'variantsInfo':{'variants':[{'choices':[],'price':{'actualPrice':{'amount':f'{price:.2f}'}},'sku':str(p.get('internal_sku') or p.get('product_code') or '')[:40],'physicalProperties':{}}]}}}
    out=api(connection_id,provider_app,provider_secret,'Create Wix hidden product draft','/stores/v3/products','POST',payload) or {}
    created=out.get('product') or {};ext=str(created.get('id') or created.get('_id') or '')
    if not ext:raise ValueError('Wix did not return the created product ID.')
    legacy._external_upsert(connection_id,'product',ext,created,'product',product_id)
    return {'ok':True,'external_id':ext,'visible':bool(created.get('visible',False)),'status':'Draft created in Wix'}
