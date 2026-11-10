"""Reviewed product delivery. Creation is never automatically retried.

Shopify Admin GraphQL 2026-10 productSet / publishablePublish and Wix Catalog
V3 products-with-inventory. Unknown outcomes require reconciliation in the store.
"""
from __future__ import annotations

import html
import json
import re
import time
import integration_layer as integrations
import integration_v14 as providers
import launch_studio as studio
import marketing as m
import media_store
import runtime_config as rc


def stores():
    return [c for c in integrations.connections() if c['connector_key'] in {'shopify','wix'}]


def graphql(c, query, variables=None):
    shop=re.sub(r'^https?://','',str(c['config'].get('store_domain','')).strip()).strip('/')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com',shop):
        raise ValueError('Reconnect Shopify with a valid store address.')
    token=providers.access_token(c['id'],'shopify') if m.one('SELECT 1 FROM v14_token_metadata WHERE connection_id=?',(c['id'],)) else integrations.load_secret(c['id'],'access_token')
    if not token: raise ValueError('Reconnect Shopify before publishing.')
    out=integrations.api_json(c['id'],'Launch product',f'https://{shop}/admin/api/2026-10/graphql.json','POST',
        {'X-Shopify-Access-Token':token},{'query':query,'variables':variables or {}},timeout=90,retries=0)
    if out.get('errors'):raise ValueError('Shopify: '+'; '.join(x.get('message','Request failed') for x in out['errors'])[:800])
    return out.get('data',{})


def resources(cid):
    c=integrations.connection(cid)
    if c['connector_key']!='shopify':return {}
    return graphql(c,'query { shop { currencyCode } locations(first:100) { nodes { id name } } publications(first:100) { nodes { id name } } }')


def media(d):
    result=[]
    for im in sorted(d['images'],key=lambda x:x['id']!=d['cover_id']):
        url=media_store.public_url(im['selected'])
        if not url: raise ValueError('Connect public image hosting in Settings before sending photos to your store. You can download the listing kit now.')
        result.append({'id':im['id'],'url':studio.safe_url(url),'alt':im['alt'],'colour':im['colour'],
                       'filename':studio.slug(d['title']+'-'+im['colour'])+'-'+im['id'][:8]+'.jpg'})
    return result


def shopify_payload(d, images, location):
    if not re.fullmatch(r'gid://shopify/Location/\d+',location):raise ValueError('Choose a Shopify stock location.')
    files=[{'originalSource':x['url'],'alt':x['alt'],'filename':x['filename'],'contentType':'IMAGE'} for x in images]
    options=active_options(d) or [{'name':'Title','values':['Default Title']}]
    variants=[]
    for v in d['variants']:
        if not v['enabled']:continue
        choices=v['choices'] or {'Title':'Default Title'}
        image=next((i for i,x in enumerate(images) if x['colour']==choices.get('Colour','')),0)
        variants.append({'sku':v['sku'],'price':v['price'] or d['price'],
                         'optionValues':[{'optionName':k,'name':val} for k,val in choices.items()],
                         'inventoryItem':{'tracked':True},'inventoryPolicy':'DENY',
                         'inventoryQuantities':[{'locationId':location,'name':'available','quantity':v['stock']}],
                         'file':files[image]})
    return {'title':d['title'],'descriptionHtml':'<p>'+html.escape(d['description']).replace('\n','<br>')+'</p>',
            'status':'DRAFT','productType':d['category'],'vendor':d['brand']['name'],'tags':d['tags'],
            'seo':{'title':d['seo_title'] or d['title'],'description':d['meta_description']},
            'productOptions':[{'name':o['name'],'position':i+1,'values':[{'name':v} for v in o['values']]} for i,o in enumerate(options)],
            'files':files,'variants':variants}


def wix_payload(d, images):
    if len(d['title'])>80:raise ValueError('Wix product names need 80 characters or fewer. Shorten the title before approving again.')
    def image(x):return {'url':x['url'],'altText':x['alt'],'displayName':x['filename'][:80]}
    options=[]
    for o in active_options(d):
        choices=[]
        for val in o['values']:
            choice={'name':val,'choiceType':'CHOICE_TEXT'}
            if o['name']=='Colour':choice['linkedMedia']=[image(x) for x in images if x['colour']==val]
            choices.append(choice)
        options.append({'name':o['name'],'optionRenderType':'TEXT_CHOICES','choicesSettings':{'choices':choices}})
    variants=[{'sku':v['sku'],'price':{'actualPrice':{'amount':v['price'] or d['price']}},'physicalProperties':{},
               'inventoryItem':{'quantity':v['stock']},
               'choices':[{'optionChoiceNames':{'optionName':k,'choiceName':val,'renderType':'TEXT_CHOICES'}} for k,val in v['choices'].items()]}
              for v in d['variants'] if v['enabled']]
    return {'product':{'name':d['title'],'slug':studio.slug(d['title'])+'-'+d['id'][:8],'productType':'PHYSICAL',
            'physicalProperties':{},'plainDescription':'<p>'+html.escape(d['description']).replace('\n','<br>')+'</p>',
            'visible':False,'visibleInPos':False,'media':{'itemsInfo':{'items':[image(x) for x in images]}},
            'options':options,'variantsInfo':{'variants':variants},
            'seoData':{'tags':[{'type':'title','children':d['seo_title'] or d['title']},
                              {'type':'meta','props':{'name':'description','content':d['meta_description']}}]}}}


def active_options(d):
    return [{'name':o['name'],'values':[value for value in o['values'] if any(v['enabled'] and v['choices'].get(o['name'])==value for v in d['variants'])]} for o in d['options']]


def wix(c, endpoint, method, payload):
    import wix_v50
    token=wix_v50.access_token(c['id'],providers.provider_app('wix'),providers.provider_secret('wix','client_secret'))['access_token']
    return integrations.api_json(c['id'],'Launch product','https://www.wixapis.com'+endpoint,method,
        {'Authorization':token},payload,timeout=90,retries=0)


def errors(result):
    if result.get('userErrors'):raise ValueError('; '.join(x.get('message','Store rejected product') for x in result['userErrors'])[:900])


def ready_shopify_images(c,external_id,expected):
    for attempt in range(8):
        result=graphql(c,'query($id:ID!){ product(id:$id){ media(first:20){ nodes { status } } } }',{'id':external_id})
        photos=(result.get('product') or {}).get('media',{}).get('nodes',[])
        if len(photos)==expected and all(p.get('status')=='READY' for p in photos):return
        if any(p.get('status')=='FAILED' for p in photos):raise ValueError('Shopify could not process a product image. Review the hidden store draft before publishing.')
        if attempt<7:time.sleep(3)
    raise ValueError('Shopify is still processing the photos. The store draft is saved; retry publishing after the images are ready.')


def receipt(d,cid,status,data,error=''):
    with m.connect() as con:
        con.execute('UPDATE launch_deliveries SET status=?,receipt=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE draft_id=? AND connection_id=?',
                    (status,json.dumps(data),error[:1000],d['id'],cid))


def deliver(d,params):
    studio.require_approved(d)
    rc.require_external_write_allowed('Publish a reviewed product')
    cid=params.get('connection_id','');c=integrations.connection(cid)
    if c['connector_key'] not in {'shopify','wix'}:raise ValueError('Choose a connected Shopify or Wix store.')
    if params.get('confirm')!='1':raise ValueError('Confirm the destination and listing before publishing.')
    live=params.get('visibility')=='live'
    signature=studio.fingerprint(d)
    old=m.one('SELECT * FROM launch_deliveries WHERE draft_id=? AND connection_id=?',(d['id'],cid))
    saved=json.loads(old['receipt']) if old else {}
    if old:
        if saved.get('basis')!=signature:raise ValueError('This product already has a store delivery. Review changes in the store before updating it; a duplicate will not be created.')
        if old['status'] in {'Sending','Unknown','Inventory needs review'}:raise ValueError('Check the previous delivery in your store before trying again. Its outcome needs review.')
        if old['status']=='Published' or (old['status']=='Store draft' and not live):return saved
        if not saved.get('external_id'):raise ValueError('Check the existing delivery in the store before trying again.')
    # Preflight has no product mutations. Check destination before allocating a delivery.
    if c['connector_key']=='shopify':
        r=resources(cid)
        if r.get('shop',{}).get('currencyCode')!=d['currency']:raise ValueError('The listing currency must match your Shopify store currency.')
        if params.get('location_id') not in {x['id'] for x in r.get('locations',{}).get('nodes',[])}:raise ValueError('Load and choose a current Shopify stock location.')
        if live and params.get('publication_id') not in {x['id'] for x in r.get('publications',{}).get('nodes',[])}:raise ValueError('Load and choose the Shopify sales channel for this product.')
    elif params.get('store_currency')!=d['currency']:
        raise ValueError('Confirm that the Wix store currency matches this listing before sending it.')
    payload=None
    if not saved.get('external_id'):
        images=media(d)
        payload=shopify_payload(d,images,params.get('location_id','')) if c['connector_key']=='shopify' else wix_payload(d,images)
    saved.update({'basis':signature,'provider':c['connector_key'],'destination':c.get('label',''),'currency':d['currency']})
    with m.connect() as con:
        if not old:
            con.execute('INSERT INTO launch_deliveries(draft_id,connection_id,revision,status,receipt) VALUES(?,?,?,?,?)',
                        (d['id'],cid,d['revision'],'Sending',json.dumps(saved)))
        else:
            changed=con.execute("UPDATE launch_deliveries SET status='Sending' WHERE draft_id=? AND connection_id=? AND status=?",(d['id'],cid,old['status']))
            if changed.rowcount!=1:raise ValueError('A delivery is already in progress.')
    try:
        if not saved.get('external_id'):
            if c['connector_key']=='shopify':
                out=graphql(c,'mutation($input:ProductSetInput!){ productSet(input:$input,synchronous:true){ product { id } userErrors { field message } } }',{'input':payload}).get('productSet',{})
                errors(out);product=out.get('product') or {}
            else:
                out=wix(c,'/stores/v3/products-with-inventory','POST',payload);product=out.get('product') or {}
            if not product.get('id'):raise ValueError('The store did not confirm a product ID. Check the store before retrying.')
            saved.update({'external_id':product['id'],'remote_revision':product.get('revision'),'created_at':studio.now()})
            receipt(d,cid,'Store draft',saved)
            inventory=out.get('inventoryResults',{})
            if inventory.get('error') or inventory.get('bulkActionMetadata',{}).get('totalFailures',0):
                receipt(d,cid,'Inventory needs review',saved,'The hidden product was created, but inventory was not fully confirmed.')
                raise ValueError('The hidden product was created, but inventory needs review in Wix before publishing.')
            integrations._external_upsert(cid,'product',product['id'],product,'product',d['product_id'])
        if live:
            if c['connector_key']=='shopify':
                ready_shopify_images(c,saved['external_id'],len(d['images']))
                out=graphql(c,'mutation($product:ProductUpdateInput!){ productUpdate(product:$product){ product { id status } userErrors { field message } } }',{'product':{'id':saved['external_id'],'status':'ACTIVE'}}).get('productUpdate',{})
                errors(out)
                out=graphql(c,'mutation($id:ID!,$publication:ID!){ publishablePublish(id:$id,input:[{publicationId:$publication}]){ publishable { publishedOnPublication(publicationId:$publication) } userErrors { field message } } }',{'id':saved['external_id'],'publication':params['publication_id']}).get('publishablePublish',{})
                errors(out)
                if not out.get('publishable',{}).get('publishedOnPublication'):raise ValueError('Shopify has not confirmed publication to this channel.')
            else:
                out=wix(c,'/stores/v3/products-with-inventory/'+saved['external_id'],'PATCH',{'product':{'id':saved['external_id'],'revision':saved['remote_revision'],'visible':True}})
                if not out.get('product',{}).get('visible'):raise ValueError('Wix has not confirmed product visibility.')
                saved['remote_revision']=out['product'].get('revision')
            saved['published_at']=studio.now()
        receipt(d,cid,'Published' if live else 'Store draft',saved)
        if live:
            with m.connect() as con:
                con.execute("UPDATE products SET status='Active',published_at=CURRENT_TIMESTAMP WHERE product_id=? AND status<>'Archived'",(d['product_id'],))
        return saved
    except Exception as exc:
        current=m.one('SELECT status FROM launch_deliveries WHERE draft_id=? AND connection_id=?',(d['id'],cid))
        if current['status']!='Inventory needs review':
            receipt(d,cid,'Publication needs review' if saved.get('external_id') else 'Unknown',saved,str(exc))
        raise
