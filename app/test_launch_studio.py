"""Isolated acceptance tests: no network, live stores, or user database writes.

Run from the project root: .venv/bin/python -m unittest discover -s app -p test_launch_studio.py -v
"""
from __future__ import annotations
import copy
import base64
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import contextlib
import http.client
import re
import threading
import unittest
from unittest.mock import patch
import zipfile
from urllib.parse import urlencode, urlparse
from http.server import ThreadingHTTPServer

_scratch=tempfile.TemporaryDirectory(prefix='commerce-launch-test-')
_root=Path(_scratch.name)
_app=Path(__file__).resolve().parent
shutil.copy2(_app.parent/'data/sample_test_database.sqlite',_root/'test.sqlite')
for name in ('static','config','logs','diagnostics','backups','product_inbox'):(_root/name).mkdir()
os.environ.update({'CRM_DATA_ROOT':str(_root),'CRM_DB_PATH':str(_root/'test.sqlite'),'CRM_STATIC_ROOT':str(_root/'static'),
    'CRM_CONFIG_DIR':str(_root/'config'),'CRM_LOG_DIR':str(_root/'logs'),'CRM_DIAGNOSTICS_DIR':str(_root/'diagnostics'),
    'CRM_SECRET_PATH':str(_root/'config/ai.json'),'CRM_INTEGRATION_KEY_PATH':str(_root/'config/integration.key'),
    'CRM_AUTH_KEY_PATH':str(_root/'config/auth.key'),'BACKUP_DIR':str(_root/'backups'),
    'CRM_TEAM_TEST':'1','CRM_ALLOW_EXTERNAL_WRITES':'0','APP_ENV':'local'})

import app
import launch_studio as ls
import launch_publish as pub
import marketing as m
import platform_core as pc
from launch_ui import LaunchPages
from PIL import Image


class LaunchAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.initialise()
        b=io.BytesIO();Image.new('RGB',(900,1200),'#365f93').save(b,'JPEG');cls.photo=b.getvalue()

    def setUp(self):
        self.ai=patch.object(m,'secret',return_value='');self.ai.start();self.addCleanup(self.ai.stop)

    def draft(self):
        return ls.create({'title':'Everyday blue shirt','facts':'A blue shirt with a button front.'},[(self.photo,'phone.jpg')])

    def ready(self,colours=False):
        d=self.draft()
        raw={'price':'999','market':'India','currency':'INR'}
        if colours:raw.update({'colours':'Blue, Cream','sizes':'S, M'})
        d=ls.edit(d,raw)
        if colours:ls.add_images(d,[(self.photo,'cream.jpg')]);d=ls.save(d,'More photos')
        for v in d['variants']:v['stock']=3
        for i,im in enumerate(d['images']):im.update({'approved':True,'alt':'Button-front shirt in '+('blue' if i==0 else 'cream'),'colour':('Blue' if i==0 else 'Cream') if colours else ''})
        return ls.save(d,'Review fixture')

    def test_phone_upload_and_web_optimisation_preserve_original(self):
        d=self.draft();original=d['images'][0]['source']
        d=ls.prepare(d)
        self.assertEqual(d['images'][0]['source'],original)
        self.assertNotEqual(d['images'][0]['selected'],original)
        self.assertFalse(d['images'][0]['approved'])
        self.assertTrue(ls.path(original).is_file())

    def test_upload_immediately_creates_linked_product_draft_and_photos(self):
        d=self.draft();pid=d['product_id']
        product=m.one('SELECT * FROM products WHERE product_id=?',(pid,))
        self.assertEqual(product['status'],'Draft')
        self.assertEqual(product['public_product_name'],d['title'])
        self.assertIsNone(product['retail_price'])
        self.assertEqual(product['stock_qty'],0)
        self.assertEqual(len(m.rows('SELECT * FROM product_images WHERE product_id=?',(pid,))),1)
        self.assertIsNone(m.one('SELECT 1 FROM launch_product_variants WHERE product_id=?',(pid,)))
        self.assertIsNone(m.one('SELECT 1 FROM launch_deliveries WHERE draft_id=?',(d['id'],)))
        d=ls.prepare(d)
        photo=m.one('SELECT relative_path FROM product_images WHERE product_id=?',(pid,))
        self.assertEqual(photo['relative_path'],d['images'][0]['selected'])

    def test_initial_draft_edits_sync_same_product_without_applying_stock(self):
        d=self.ready(True);pid=d['product_id']
        d=ls.edit(d,{'title':'Updated draft shirt','price':'1250','description':'Updated description'})
        p=m.one('SELECT * FROM products WHERE product_id=?',(pid,))
        self.assertEqual(p['public_product_name'],'Updated draft shirt')
        self.assertEqual(float(p['retail_price']),1250)
        self.assertEqual(p['stock_qty'],0)
        self.assertEqual(len(m.rows('SELECT * FROM product_images WHERE product_id=?',(pid,))),2)
        d=ls.approve(d)
        self.assertEqual(d['product_id'],pid)
        self.assertEqual(m.one('SELECT stock_qty FROM products WHERE product_id=?',(pid,))['stock_qty'],12)

    def test_previously_approved_product_keeps_reviewed_snapshot_until_reapproval(self):
        d=ls.approve(self.ready());pid=d['product_id'];title=d['title']
        d=ls.edit(d,{'title':'Unreviewed new title'})
        self.assertEqual(m.one('SELECT public_product_name FROM products WHERE product_id=?',(pid,))['public_product_name'],title)
        ls.approve(d)
        self.assertEqual(m.one('SELECT public_product_name FROM products WHERE product_id=?',(pid,))['public_product_name'],'Unreviewed new title')

    def test_legacy_upload_is_backfilled_once_without_losing_images_or_facts(self):
        d=self.draft();pid=d['product_id'];d['product_id']=''
        with m.connect() as con:
            con.execute('DELETE FROM product_images WHERE product_id=?',(pid,))
            con.execute('DELETE FROM products WHERE product_id=?',(pid,))
            con.execute('UPDATE launch_drafts SET document=? WHERE id=?',(json.dumps(d),d['id']))
        ls.initialise();repaired=ls.get(d['id']);ls.initialise()
        self.assertEqual(repaired['product_id'],pid)
        self.assertEqual(ls.get(d['id'])['revision'],repaired['revision'])
        self.assertEqual(repaired['images'],d['images'])
        self.assertEqual(repaired['facts'],d['facts'])
        self.assertEqual(m.one('SELECT COUNT(*) AS n FROM products WHERE product_id=?',(pid,))['n'],1)

    def test_failed_catalogue_write_rolls_back_uploaded_draft(self):
        before=m.one('SELECT COUNT(*) AS n FROM launch_drafts')['n']
        with patch.object(ls,'sync_catalogue_draft',side_effect=ValueError('Simulated database failure')):
            with self.assertRaisesRegex(ValueError,'Simulated'):self.draft()
        self.assertEqual(m.one('SELECT COUNT(*) AS n FROM launch_drafts')['n'],before)

    def test_invalid_images_and_path_traversal_rejected(self):
        with self.assertRaises(ValueError):ls.create({},[(b'not a photo','test.jpg')])
        with self.assertRaises(ValueError):ls.path('../config/ai.json')

    def test_variant_quantities_preserved_when_options_expand(self):
        d=ls.edit(self.draft(),{'colours':'Blue','sizes':'S, M'})
        d['variants'][0]['stock']=4;d['variants'][0]['price']='1200.00';d=ls.save(d,'Stock')
        d=ls.edit(d,{'colours':'Blue, Cream','sizes':'S, M'})
        self.assertEqual(len(d['variants']),4)
        self.assertEqual(d['variants'][0]['stock'],4)
        self.assertEqual(d['variants'][0]['price'],'1200.00')
        self.assertIsNone(d['variants'][2]['stock'])

    def test_invalid_options_prices_stock_and_duplicate_skus(self):
        for val in ('-1','NaN','Infinity','not money'):
            with self.assertRaises(ValueError):ls.money(val)
        with self.assertRaises(ValueError):ls.stock('1.5')
        with self.assertRaises(ValueError):ls.parse_options({'colours':'Blue, blue'})
        with self.assertRaises(ValueError):ls.parse_options({'colours':','.join(map(str,range(11))),'sizes':','.join(map(str,range(10)))})
        d=self.ready(True);raw={'variants_form':'1'}
        for v in d['variants']:raw.update({'enabled_'+v['id']:'1','sku_'+v['id']:'SAME','stock_'+v['id']:'1'})
        with self.assertRaisesRegex(ValueError,'different SKU'):ls.edit(d,raw)

    def test_missing_stock_colour_and_photo_review_block_approval(self):
        d=self.ready(True);d['images'][1]['colour']='';d['variants'][0]['stock']=None;d['images'][0]['approved']=False
        issues=' '.join(ls.blockers(d));self.assertIn('stock',issues);self.assertIn('real photo',issues);self.assertIn('Review each photo',issues)
        with self.assertRaises(ValueError):ls.approve(d)

    def test_one_parent_with_four_variants_and_opening_inventory(self):
        d=ls.approve(self.ready(True));pid=d['product_id']
        self.assertTrue(m.one('SELECT 1 FROM products WHERE product_id=?',(pid,)))
        self.assertEqual(len(m.rows('SELECT * FROM launch_product_variants WHERE product_id=?',(pid,))),4)
        self.assertEqual(m.one('SELECT on_hand FROM v9_inventory WHERE product_id=?',(pid,))['on_hand'],12)
        d=ls.approve(ls.get(d['id']))
        self.assertEqual(len(m.rows('SELECT * FROM v35_inventory_movements WHERE product_id=?',(pid,))),1)

    def test_existing_sales_inventory_is_not_reset_by_reapproval(self):
        d=ls.approve(self.ready());pid=d['product_id']
        with m.connect() as c:c.execute('UPDATE v9_inventory SET on_hand=2 WHERE product_id=?',(pid,))
        d=ls.edit(d,{'description':'Updated description'})
        with self.assertRaisesRegex(ValueError,'Inventory has changed'):ls.approve(d)
        self.assertEqual(m.one('SELECT on_hand FROM v9_inventory WHERE product_id=?',(pid,))['on_hand'],2)
        d['variants'][0]['stock']=10;d=ls.save(d,'Change opening stock')
        with self.assertRaisesRegex(ValueError,'Inventory has changed'):ls.approve(d)
        self.assertNotEqual(ls.get(d['id']).get('approved_revision'),ls.get(d['id'])['revision'])
        d=ls.get(d['id']);d['variants'][0]['stock']=2;d=ls.approve(ls.save(d,'Reconcile stock'))
        self.assertEqual(m.one('SELECT on_hand FROM v9_inventory WHERE product_id=?',(pid,))['on_hand'],2)

    def test_stale_forms_and_queued_jobs_cannot_overwrite(self):
        d=self.draft();old=copy.deepcopy(d);d=ls.edit(d,{'title':'New title'})
        with self.assertRaises(ValueError):ls.edit(old,{'title':'Stale'})
        jid=ls.enqueue(d,'prepare')
        with self.assertRaises(ValueError):ls.edit(d,{'title':'During processing'})
        with self.assertRaises(ValueError):ls.enqueue(d,'prepare')
        ls.run_job(m.one('SELECT * FROM launch_jobs WHERE id=?',(jid,)))
        self.assertEqual(m.one('SELECT status FROM launch_jobs WHERE id=?',(jid,))['status'],'Done')

    def test_approval_invalidated_and_restore_keeps_parent_identity(self):
        d=ls.approve(self.ready());revision=d['revision'];pid=d['product_id']
        d=ls.edit(d,{'price':'888'})
        with self.assertRaises(ValueError):ls.export_kit(d)
        d=ls.restore(d,revision);self.assertEqual(d['product_id'],pid);self.assertIsNone(d['approved_revision'])

    def test_research_accepts_only_tool_sources_matching_currency(self):
        d=self.ready()
        rows=[{'title':'Shirt','price':n,'currency':'INR','url':'https://store.example/'+str(n),'reason':'Similar shirt'} for n in (800,900,1000)]
        rows+=[{'price':1,'currency':'INR','url':'https://invented.example/fake'},{'price':5,'currency':'USD','url':'https://store.example/usd'}]
        response={'output':[{'type':'web_search_call','action':{'sources':[{'url':x['url']} for x in rows[:3]]}},
            {'type':'message','content':[{'type':'output_text','text':json.dumps({'comparables':rows})}]}]}
        with patch.object(ls,'ai_request',return_value=response):d=ls.research(d)
        self.assertEqual(ls.pricing(d)['count'],3);self.assertEqual(ls.pricing(d)['suggested'],'900.00')
        d=ls.edit(d,{'cost':'700','extra_cost':'70','margin':'30'})
        self.assertEqual(ls.pricing(d)['suggested'],'1100.00')
        d=ls.edit(d,{'material':'Cotton'})
        self.assertEqual(ls.pricing(d)['suggested'],'');self.assertTrue(ls.pricing(d)['stale'])

    def test_insufficient_or_old_research_never_invents_price(self):
        d=self.ready();d['research']={'checked_at':'2020-01-01T00:00:00+00:00','comparables':[{'price':'1','currency':'INR'}]*3}
        self.assertEqual(ls.pricing(d)['suggested'],'')

    def test_social_uses_only_available_variants_and_requires_review_for_export(self):
        d=self.ready(True);d['variants'][2]['stock']=0;d['variants'][3]['stock']=0;d=ls.approve(ls.save(d,'Stock'))
        d=ls.social(d);self.assertNotIn('Cream',d['social']['captions']['WhatsApp']);self.assertEqual(len(d['social']['assets']),3)
        ls.require_approved(d)
        with zipfile.ZipFile(io.BytesIO(ls.export_kit(d))) as z:self.assertFalse(any(n.startswith('social/') for n in z.namelist()))
        d['social']['approved']=True;d=ls.save(d,'Social review',invalidate=ls.preserve_approval(d))
        with zipfile.ZipFile(io.BytesIO(ls.export_kit(d))) as z:
            self.assertIn('social/instagram.txt',z.namelist());self.assertNotIn('cost',json.loads(z.read('product.json')))
        d=ls.approve(ls.edit(d,{'price':'777'}))
        with zipfile.ZipFile(io.BytesIO(ls.export_kit(d))) as z:self.assertNotIn('social/instagram.txt',z.namelist())

    def test_out_of_stock_social_blocked(self):
        d=self.ready();d['variants'][0]['stock']=0;d=ls.approve(ls.save(d,'Sold out'))
        with self.assertRaisesRegex(ValueError,'out of stock'):ls.social(d)

    def test_social_cover_does_not_promote_a_sold_out_colour(self):
        d=self.ready(True)
        for v in d['variants']:
            if v['choices']['Colour']=='Blue':v['stock']=0
        d=ls.social(ls.approve(ls.save(d,'Blue sold out')))
        self.assertIn('cream',d['social']['assets'][0]['alt'])
        self.assertNotIn('Colours: Blue',d['social']['captions']['WhatsApp'])

    def test_store_options_omit_choices_with_no_enabled_variant(self):
        d=self.ready(True)
        for v in d['variants']:
            if v['choices']['Colour']=='Cream':v['enabled']=False
        self.assertEqual(pub.active_options(d)[0]['values'],['Blue'])

    def test_store_payloads_share_photos_by_colour_and_exclude_disabled_variants(self):
        d=self.ready(True);d['variants'][1]['enabled']=False
        images=[{'id':im['id'],'url':'https://media.example/'+im['id']+'.jpg','alt':im['alt'],'colour':im['colour'],'filename':im['id']+'.jpg'} for im in d['images']]
        p=pub.shopify_payload(d,images,'gid://shopify/Location/1')
        self.assertEqual(len(p['variants']),3);self.assertEqual(p['status'],'DRAFT')
        self.assertEqual(p['variants'][1]['file'],p['variants'][2]['file'])
        self.assertNotEqual(p['variants'][0]['file'],p['variants'][1]['file'])
        w=pub.wix_payload(d,images)['product'];self.assertFalse(w['visible']);self.assertEqual(len(w['variantsInfo']['variants']),3)
        self.assertEqual(w['options'][0]['choicesSettings']['choices'][1]['linkedMedia'][0]['altText'],images[1]['alt'])

    def test_test_mode_blocks_store_jobs_and_role_routes_are_scoped(self):
        d=ls.approve(self.ready())
        with self.assertRaises(ValueError):ls.enqueue(d,'deliver',{'confirm':'1'})
        self.assertEqual(pc.permission_for_path('/launch/deliver','POST'),'integrations.manage')
        self.assertEqual(pc.permission_for_path('/launch/brand','POST'),'settings.manage')
        self.assertEqual(pc.permission_for_path('/launch/social-save','POST'),'marketing.manage')
        self.assertEqual(pc.permission_for_path('/launch/edit','POST'),'products.manage')

    def test_unknown_delivery_never_creates_another_product(self):
        d=ls.approve(self.ready());cid='test-store'
        with m.connect() as con:
            con.execute('INSERT INTO launch_deliveries(draft_id,connection_id,revision,status,receipt) VALUES(?,?,?,?,?)',
                (d['id'],cid,d['revision'],'Unknown',json.dumps({'basis':ls.fingerprint(d)})))
        with patch.object(pub.rc,'require_external_write_allowed'),patch.object(pub.integrations,'connection',return_value={'id':cid,'connector_key':'shopify'}),patch.object(pub,'graphql') as call:
            with self.assertRaisesRegex(ValueError,'previous delivery'):pub.deliver(d,{'connection_id':cid,'confirm':'1'})
            call.assert_not_called()

    def test_every_screen_renders_escaped_content_and_scoped_forms(self):
        d=self.ready();d=ls.edit(d,{'title':'<script>alert(1)</script>'});d=ls.approve(d)
        handler=LaunchPages()
        for step in ('details','photos','review','social'):
            page=handler.launch_detail(d,{'step':[step]})
            self.assertNotIn('<script>alert(1)',page)
            self.assertIn('name="revision"',page)
            self.assertIn('/launch/',page)

    def test_wix_inventory_failure_stays_hidden_and_cannot_be_replayed(self):
        d=ls.approve(self.ready());cid='wix-partial-'+d['id'];c={'id':cid,'connector_key':'wix','label':'Test Wix'}
        params={'connection_id':cid,'store_currency':'INR','visibility':'live','confirm':'1'}
        images=[{'id':'photo','url':'https://media.example/test.jpg','alt':'Blue shirt','colour':'','filename':'shirt.jpg'}]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(pub.rc,'require_external_write_allowed'))
            stack.enter_context(patch.object(pub.integrations,'connection',return_value=c))
            stack.enter_context(patch.object(pub,'media',return_value=images))
            call=stack.enter_context(patch.object(pub,'wix',return_value={'product':{'id':'remote-1','revision':'1'},'inventoryResults':{'bulkActionMetadata':{'totalFailures':1}}}))
            with self.assertRaisesRegex(ValueError,'inventory needs review'):pub.deliver(d,params)
            self.assertEqual(call.call_count,1)
            delivery=m.one('SELECT * FROM launch_deliveries WHERE draft_id=?',(d['id'],))
            self.assertEqual(delivery['status'],'Inventory needs review');self.assertEqual(json.loads(delivery['receipt'])['external_id'],'remote-1')
            with self.assertRaises(ValueError):pub.deliver(d,params)
            self.assertEqual(call.call_count,1)

    def test_shopify_draft_then_publish_reuses_same_product(self):
        d=ls.approve(self.ready());cid='shopify-'+d['id'];c={'id':cid,'connector_key':'shopify','label':'Test Shopify'}
        location='gid://shopify/Location/1';channel='gid://shopify/Publication/2'
        params={'connection_id':cid,'confirm':'1','location_id':location,'publication_id':channel,'visibility':'draft'}
        resources={'shop':{'currencyCode':'INR'},'locations':{'nodes':[{'id':location}]},'publications':{'nodes':[{'id':channel}]}}
        images=[{'id':'photo','url':'https://media.example/test.jpg','alt':'Blue shirt','colour':'','filename':'shirt.jpg'}]
        calls=[]
        def graph(_c,query,variables):
            calls.append(query)
            if 'productSet' in query:return {'productSet':{'product':{'id':'gid://shopify/Product/42'},'userErrors':[]}}
            if 'productUpdate' in query:return {'productUpdate':{'product':{'id':'gid://shopify/Product/42','status':'ACTIVE'},'userErrors':[]}}
            if 'media(first' in query:return {'product':{'media':{'nodes':[{'status':'READY'}]}}}
            return {'publishablePublish':{'publishable':{'publishedOnPublication':True},'userErrors':[]}}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(pub.rc,'require_external_write_allowed'))
            stack.enter_context(patch.object(pub.integrations,'connection',return_value=c))
            stack.enter_context(patch.object(pub.integrations,'_external_upsert'))
            stack.enter_context(patch.object(pub,'resources',return_value=resources))
            stack.enter_context(patch.object(pub,'media',return_value=images))
            stack.enter_context(patch.object(pub,'graphql',side_effect=graph))
            pub.deliver(d,params)
            self.assertEqual(m.one('SELECT status FROM launch_deliveries WHERE draft_id=?',(d['id'],))['status'],'Store draft')
            params['visibility']='live';pub.deliver(d,params);pub.deliver(d,params)
        self.assertEqual(sum('productSet' in q for q in calls),1)
        self.assertEqual(m.one('SELECT status FROM launch_deliveries WHERE draft_id=?',(d['id'],))['status'],'Published')

    def test_shopify_images_must_be_ready_before_publication(self):
        with patch.object(pub,'graphql',return_value={'product':{'media':{'nodes':[{'status':'FAILED'}]}}}):
            with self.assertRaisesRegex(ValueError,'could not process'):pub.ready_shopify_images({},'product',1)

    def test_production_jobs_use_durable_queue_and_interrupted_work_is_not_replayed(self):
        import durable_worker as worker
        d=self.draft()
        with patch.object(ls.rc,'IS_PRODUCTION',True):jid=ls.enqueue(d,'prepare')
        queued=m.one('SELECT * FROM v12_worker_jobs WHERE id=?',('LAUNCH-'+jid,))
        self.assertEqual(queued['max_attempts'],1)
        with m.connect() as con:con.execute("UPDATE launch_jobs SET status='Running' WHERE id=?",(jid,))
        with patch.object(ls,'prepare') as prepare:
            worker._execute(queued);prepare.assert_not_called()
        self.assertEqual(m.one('SELECT status FROM launch_jobs WHERE id=?',(jid,))['status'],'Failed')

    def test_archived_parent_cannot_be_exported_or_used_for_social(self):
        d=ls.approve(self.ready())
        with m.connect() as con:con.execute("UPDATE products SET status='Archived' WHERE product_id=?",(d['product_id'],))
        with self.assertRaisesRegex(ValueError,'archived'):ls.export_kit(d)
        with self.assertRaisesRegex(ValueError,'archived'):ls.social(d)

    def test_batch_shoot_keeps_completed_studio_edit_when_model_fails(self):
        d=self.draft();d['shoot']='model';d=ls.save(d,'Choose model')
        def generate(d,iid,kind):
            if kind=='model':raise ValueError('Simulated provider failure')
            d['images'][0]['variants'].append({'kind':'AI studio','path':d['images'][0]['source']})
            return ls.save(d,'Studio complete',worker=True)
        with patch.object(ls,'enhance',side_effect=generate):
            with self.assertRaisesRegex(ValueError,'Simulated'):ls.photoshoot(d)
        self.assertEqual(ls.get(d['id'])['images'][0]['variants'][0]['kind'],'AI studio')

    def test_generate_runs_copy_studio_and_model_with_progress_and_saved_previews(self):
        import ai_router
        import operating_core
        for fail_model in (False,True):
            with self.subTest(fail_model=fail_model):
                d=ls.edit(self.draft(),{'shoot':'model'});requests=[];previews=[]
                def provider(task,body,**kwargs):
                    requests.append((task,body))
                    self.assertEqual(len(body['safety_identifier']),64)
                    if task=='product_understanding':
                        result={'title':'AI blue shirt','description':'A blue button-front shirt.','images':[{'id':d['images'][0]['id'],'alt':'Blue shirt, front view'}]}
                        return {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(result)}]}]},1,10
                    current=ls.get(d['id']);previews.append(LaunchPages().launch_detail(current,{'step':['photos']}))
                    self.assertIn('AI blue shirt',previews[-1])
                    self.assertIn('data-job-message',previews[-1])
                    self.assertNotIn('<form',previews[-1])
                    if len(requests)==3 and fail_model:raise ValueError('Simulated image service failure')
                    return {'output':[{'type':'image_generation_call','result':base64.b64encode(self.photo).decode()}]},1,10
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch.object(m,'secret',return_value='test-only-key'))
                    stack.enter_context(patch.object(ai_router,'preflight',side_effect=lambda task,**kw:{'model':'test-'+task}))
                    stack.enter_context(patch.object(ai_router,'request_json',side_effect=provider))
                    stack.enter_context(patch.object(ai_router,'record_success'))
                    stack.enter_context(patch.object(operating_core,'guard_ai_call'))
                    jid=ls.enqueue(d,'generate');ls.run_job(ls.busy(d['id']))
                result=ls.get(d['id']);job=m.one('SELECT * FROM launch_jobs WHERE id=?',(jid,))
                self.assertEqual(job['status'],'Failed' if fail_model else 'Done')
                self.assertEqual([r[0] for r in requests],['product_understanding','image_generation','image_generation'])
                self.assertEqual(requests[1][1]['tool_choice'],{'type':'image_generation'})
                model_inputs=[i for i in requests[2][1]['input'][0]['content'] if i['type']=='input_image']
                studio=result['images'][0]['variants'][1]['path']
                self.assertEqual(model_inputs[0]['image_url'],'data:image/jpeg;base64,'+base64.b64encode(ls.path(studio).read_bytes()).decode())
                self.assertEqual(len(model_inputs),2)
                self.assertIn('AI studio',previews[-1])
                self.assertEqual(result['title'],'AI blue shirt')
                self.assertFalse(result['images'][0]['approved'])
                kinds=[v['kind'] for v in result['images'][0]['variants']]
                self.assertIn('AI studio',kinds)
                self.assertEqual('AI model' in kinds,not fail_model)
                self.assertEqual(m.one('SELECT public_product_name FROM products WHERE product_id=?',(d['product_id'],))['public_product_name'],'AI blue shirt')
                self.assertIsNone(m.one('SELECT 1 FROM launch_deliveries WHERE draft_id=?',(d['id'],)))

    def test_generation_requires_key_and_local_preparation_is_labeled(self):
        d=self.draft()
        with self.assertRaisesRegex(ValueError,'Connect your OpenAI'):ls.enqueue(d,'generate')
        jid=ls.enqueue(d,'prepare');ls.run_job(ls.busy(d['id']))
        result=ls.get(d['id'])
        self.assertEqual(result['content_engine'],'Your details')
        self.assertIn('resized locally',m.one('SELECT message FROM launch_jobs WHERE id=?',(jid,))['message'])
        with patch.object(m,'secret',return_value='test-only-key'):jid=ls.enqueue(result,'generate')
        ls.run_job(ls.busy(d['id']))
        self.assertEqual(m.one('SELECT status FROM launch_jobs WHERE id=?',(jid,))['status'],'Failed')

    def test_ai_setup_keeps_secret_out_of_page_and_stored_check(self):
        import ai_router
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}),patch.object(m,'save_secret') as save_secret,patch.object(m,'secret',return_value='test-only-key'),patch.object(ai_router,'validate_capability',return_value={'ready':True,'model':'test-model','detail':'Access verified.'}) as validate:
            result=ls.check_ai_connection('test-only-key')
            save_secret.assert_called_once_with('test-only-key')
            self.assertEqual(validate.call_count,3)
            self.assertTrue(all(c['ready'] for c in result['checks']))
            page=LaunchPages().launch_ai_setup({})
            self.assertIn('type="password"',page)
            self.assertNotIn('test-only-key',page)
            self.assertNotIn('test-only-key',m.settings()['launch_ai_connection_check'])
        self.assertEqual(pc.permission_for_path('/launch/ai'),'settings.manage')
        self.assertEqual(pc.permission_for_path('/launch/ai-connect','POST'),'settings.manage')

    def test_ai_validation_cache_reuses_validated_fallback(self):
        import ai_router
        route=ai_router.route('product_understanding')
        with patch.object(m,'secret',return_value='test-only-key'),patch.object(ai_router,'_models',return_value=({route['fallback_model']},{})) as models:
            live=ai_router.validate_capability('product_understanding',force=True)
            cached=ai_router.validate_capability('product_understanding')
            self.assertEqual(models.call_count,1)
            self.assertTrue(live['ready']);self.assertTrue(cached['using_fallback'])
            self.assertEqual(cached['model'],route['fallback_model'])

    def test_http_upload_csrf_forms_and_preview_routes(self):
        class QuietApp(app.App):
            def log_message(self,*args):pass
        pc.set_sec('auth_enabled','0')
        server=ThreadingHTTPServer(('127.0.0.1',0),QuietApp)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(method,path,body=None,headers=None):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
            try:
                conn.request(method,path,body=body,headers=headers or {});response=conn.getresponse()
                return response.status,dict(response.getheaders()),response.read()
            finally:conn.close()
        try:
            code,headers,page=request('GET','/launch');self.assertEqual(code,200)
            csrf=re.search(rb'name="_csrf" value="([^"]+)"',page).group(1).decode()
            boundary='LaunchAcceptanceBoundary'
            parts=[]
            for k,v in {'_csrf':csrf,'title':'HTTP test shirt','facts':'Plain blue shirt','shoot':'product'}.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="product_images"; filename="shirt.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()+self.photo+b'\r\n')
            parts.append(f'--{boundary}--\r\n'.encode())
            code,headers,_=request('POST','/launch/upload',b''.join(parts),{'Content-Type':'multipart/form-data; boundary='+boundary})
            self.assertEqual(code,303);did=urlparse(headers['Location']).path.split('/')[-1]
            d=ls.get(did);self.assertEqual(d['title'],'HTTP test shirt')
            code,_,product_page=request('GET','/products/'+d['product_id'])
            self.assertEqual(code,200);self.assertIn(b'HTTP test shirt',product_page)
            self.assertIn(b'Continue preparing product',product_page)
            code,_,product_list=request('GET','/products')
            self.assertEqual(code,200);self.assertIn(b'HTTP test shirt',product_list)
            job=ls.busy(did);ls.run_job(job);d=ls.get(did)
            invalid=urlencode({'id':did,'revision':d['revision'],'title':'FORGED','_csrf':'invalid'})
            request('POST','/launch/edit',invalid,{'Content-Type':'application/x-www-form-urlencoded'})
            self.assertEqual(ls.get(did)['title'],'HTTP test shirt')
            valid=urlencode({'id':did,'revision':d['revision'],'title':'Saved title','_csrf':csrf})
            code,_,_=request('POST','/launch/edit',valid,{'Content-Type':'application/x-www-form-urlencoded'});self.assertEqual(code,303)
            self.assertEqual(ls.get(did)['title'],'Saved title')
            for step in ('details','photos','review','social'):
                code,_,page=request('GET','/launch/'+did+'?step='+step);self.assertEqual(code,200);self.assertIn(b'Saved title',page)
            for asset in ('launch.css','launch.js'):
                self.assertEqual(request('GET','/ui/'+asset)[0],200)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':unittest.main()
