from __future__ import annotations
import json,re
import marketing as m
import creative_engine as ce

class CreativePages:
    def v7_get(self,path,q):
        if path=='/creative':self.creative_home(q)
        elif re.fullmatch(r'/creative/products/[^/]+',path):self.creative_product(path.split('/')[3],q)
        else:return False
        return True

    def v7_post(self,path,f):
        v=lambda k,d='':f.get(k,[d])[0]
        if path=='/creative/settings':ce.save_settings({k:x[0] for k,x in f.items()});return self.redirect('/creative?saved=1')
        if path=='/creative/brand-logo':
            upload=getattr(self,'_brand_logo_upload',None)
            if not upload:raise ValueError('Choose a logo image first.')
            ce.save_brand_logo(*upload);return self.redirect('/creative?logo=1')
        if path=='/creative/queue-pack':
            pid=v('product_id');ce.queue_default_pack(pid,'owner action');return self.redirect('/creative/products/'+pid+'?queued=1')
        if path=='/creative/queue-all':
            count=0
            for p in m.products(): ce.queue_default_pack(p['product_id'],'existing catalogue');count+=1
            return self.redirect('/creative?queued_all='+str(count))
        if path=='/creative/generate':
            jid=v('job_id');a=ce.generate_visual(jid);return self.redirect('/creative/products/'+m.one('SELECT product_id FROM v7_creative_jobs WHERE id=?',(jid,))['product_id']+'?generated='+a)
        if path=='/creative/fidelity':
            aid=v('asset_id');a=m.one('SELECT product_id FROM v7_creative_assets WHERE id=?',(aid,));ce.fidelity_check(aid);return self.redirect('/creative/products/'+a['product_id']+'?fidelity=1')
        if path=='/creative/approve':
            aid=v('asset_id');a=m.one('SELECT product_id FROM v7_creative_assets WHERE id=?',(aid,));ce.approve_asset(aid,v('decision','approve')=='approve');return self.redirect('/creative/products/'+a['product_id']+'?approved=1')
        if path=='/creative/channel-pack':
            pid=v('product_id');ce.create_channel_pack(pid,force=v('force')=='1');return self.redirect('/creative/products/'+pid+'?pack=1')
        if path=='/creative/reel':
            pid=v('product_id');ce.create_reel_package(pid);return self.redirect('/creative/products/'+pid+'?reel=1')
        if path=='/creative/process-queue':
            ce.process_queue_once(3);return self.redirect('/creative?processed=1')
        return False

    def creative_home(self,q):
        import app
        ce.initialise();products=m.products()
        queued=m.one("SELECT count(*) n FROM v7_creative_jobs WHERE status='Queued'")['n']; generated=m.one("SELECT count(*) n FROM v7_creative_assets WHERE source_kind='AI generated'")['n']; approved=m.one("SELECT count(*) n FROM v7_creative_assets WHERE status='Approved'")['n'];pub=m.one('SELECT count(*) n FROM v7_publish_queue')['n']
        body=app.pagehead('Creative automation','Turn product photography into model/mannequin visuals, social creatives, ad assets and reel packages.',app.button('AI product engine','/product-engine','secondary')+'<form method="post" action="/creative/queue-all" style="display:inline"><button class="btn secondary">Queue packs for catalogue</button></form>')
        for key,msg in [('saved','Creative automation defaults saved.'),('logo','Brand logo saved for generated marketing assets.'),('processed','Queued AI jobs processed where AI was connected and auto-generation was enabled.')]:
            if q.get(key):body+=app.notice(msg,'success')
        if q.get('queued_all'):body+=app.notice(q['queued_all'][0]+' catalogue product(s) checked and standard creative packs queued where needed. No paid call was made.','success')
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{queued}</span><strong>AI visuals queued</strong><span class="helper">Waiting or ready to run</span></div><div class="card stat-card"><span class="stat-label">{generated}</span><strong>AI garment visuals</strong><span class="helper">Model / mannequin outputs</span></div><div class="card stat-card"><span class="stat-label">{approved}</span><strong>Approved creatives</strong><span class="helper">Ready for controlled use</span></div><div class="card stat-card"><span class="stat-label">{pub}</span><strong>Channel handoffs</strong><span class="helper">Prepared, not published</span></div></div>'''
        body+='<div class="two section"><div><div class="section-head"><h2>Products</h2><span class="tiny muted">Create a standard visual pack in one place</span></div><div class="product-grid">'
        for p in products:
            s=ce.pack_status(p['product_id']);ai=sum(1 for a in s['assets'] if a['source_kind']=='AI generated'); ch=sum(1 for a in s['assets'] if a['source_kind']!='AI generated')
            img=p.get('img') or ''
            body+=f'<article class="product"><a href="/creative/products/{app.e(p["product_id"])}"><img src="/{app.e(img)}" alt="Product"></a><div class="pbody"><span class="tiny muted">{app.e(p["product_code"] or p["internal_sku"])}</span><h3>{app.e(p["public_product_name"])}</h3><p>{ai} AI visual(s) · {ch} channel asset(s)</p><div class="section">{app.button("Open creative workspace","/creative/products/"+p["product_id"],"secondary small")}</div></div></article>'
        if not products:body+='<div class="card empty">Add product photography in the AI Product Engine first.</div>'
        body+='</div></div><div><div class="card"><div class="eyebrow">Automation policy</div><h2>How much should happen automatically?</h2><form method="post" action="/creative/settings">'
        body+=app.field('Image model','<input name="creative_image_model" value="'+app.e(ce.setting('creative_image_model'))+'">','High-fidelity reference editing model. API usage can incur charges.')
        body+=app.field('Controller / fidelity model','<input name="creative_controller_model" value="'+app.e(ce.setting('creative_controller_model'))+'">')
        body+=app.field('Fidelity threshold','<input name="creative_fidelity_threshold" type="number" min="50" max="100" value="'+app.e(ce.setting('creative_fidelity_threshold','85'))+'">','AI comparison is a guardrail, not proof. Generated garment visuals still remain labelled AI-generated.')
        body+=app.field('Default CTA','<input name="creative_cta" value="'+app.e(ce.setting('creative_cta','Explore the collection'))+'">')
        body+=app.field('Brand primary colour','<input name="creative_brand_primary" value="'+app.e(ce.setting('creative_brand_primary','#17131B'))+'">','Used for deterministic marketing overlays.')
        body+=app.field('Brand accent colour','<input name="creative_brand_accent" value="'+app.e(ce.setting('creative_brand_accent','#A27654'))+'">','Stored for future creative templates and publishing integrations.')
        for name,label,checked in [('creative_auto_queue','Queue ecommerce + mannequin + model jobs after product intake',ce.setting('creative_auto_queue','1')=='1'),('creative_auto_generate','Automatically run queued paid AI image jobs while the CRM is open',ce.setting('creative_auto_generate','0')=='1'),('creative_auto_fidelity','Automatically compare each AI visual with the raw reference images',ce.setting('creative_auto_fidelity','1')=='1'),('creative_auto_channel_assets','Prepare deterministic ecommerce/social/ad crops after approval',ce.setting('creative_auto_channel_assets','1')=='1'),('creative_auto_approve','Zero-touch mode: auto-approve only AI visuals scoring 95+ and marked acceptable by the fidelity check',ce.setting('creative_auto_approve','0')=='1')]:
            body+=f'<p><label class="checkline"><input type="checkbox" name="{name}" value="1" {"checked" if checked else ""}>{label}</label></p>'
        body+='<button class="btn">Save creative automation</button></form><div class="divider"></div><h3>Brand logo</h3><p class="helper">Optional. Used only on deterministic marketing creatives; ecommerce product crops stay clean and text-free.</p><form method="post" action="/creative/brand-logo" enctype="multipart/form-data"><input type="file" name="brand_logo" accept="image/png,image/jpeg,image/webp" required><button class="btn secondary section">Upload logo</button></form><div class="divider"></div><p class="helper">Recommended for testing: queue automatically, keep paid AI generation review-controlled, and run fidelity checks automatically. After representative products consistently preserve colour/pattern/border/pallu details, you may enable paid auto-generation. Zero-touch auto-approval is intentionally off by default and requires a 95+ fidelity result.</p>'
        if m.secret():body+='<form method="post" action="/creative/process-queue" class="section"><button class="btn secondary">Process up to 3 queued AI jobs now</button></form>'
        else:body+=app.notice('AI is not connected. Product crops and reel frames still work; model/mannequin generation requires the API key in Settings & AI.')
        body+='</div></div></div>'
        self.send_html(app.layout('Creative automation',body,'creative'))

    def creative_product(self,pid,q):
        import app
        p=ce.product(pid);s=ce.pack_status(pid);src=m.rows('SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC,image_role',(pid,))
        body=app.pagehead('Creative workspace',p['public_product_name'],app.button('Product engine review','/product-engine/products/'+pid,'secondary')+app.button('All creative work','/creative','secondary'))
        for key,msg in [('queued','Standard mannequin + model jobs queued.'),('fidelity','Fidelity review completed.'),('approved','Creative approval updated.'),('pack','Channel creative pack prepared.'),('reel','Promotional reel package prepared.')]:
            if q.get(key):body+=app.notice(msg,'success')
        if q.get('generated'):body+=app.notice('AI visual generated. Review the fidelity result before approving it.','success')
        body+='<div class="two section"><div class="card"><div class="eyebrow">1. Product source of truth</div><h2>Original product photography</h2><div class="gallery">'
        for im in src[:6]:body+=f'<figure style="margin:0"><img src="/{app.e(im["relative_path"])}" alt="{app.e(im["image_role"])}"><figcaption class="tiny muted">{app.e(im["image_role"])} · original</figcaption></figure>'
        body+='</div><p class="helper section">Original photography remains the authoritative representation of the product. AI model/mannequin visuals are supplemental marketing assets and are never allowed to silently replace the source images.</p></div><div class="card"><div class="eyebrow">2. One-click standard pack</div><h2>Ecommerce + mannequin + model + channel creatives + reel</h2><p class="helper">Queue three high-fidelity AI visual jobs, then approve good outputs. Channel formats use deterministic crops so the garment is not regenerated repeatedly for every placement.</p><form method="post" action="/creative/queue-pack"><input type="hidden" name="product_id" value="'+app.e(pid)+'"><button class="btn" style="width:100%">Queue standard AI visual pack</button></form><form method="post" action="/creative/channel-pack" class="section"><input type="hidden" name="product_id" value="'+app.e(pid)+'"><button class="btn secondary" style="width:100%">Create / refresh social & ad pack</button></form><form method="post" action="/creative/reel" class="section"><input type="hidden" name="product_id" value="'+app.e(pid)+'"><button class="btn secondary" style="width:100%">Create promotional reel package</button></form></div></div>'
        body+='<div class="section-head"><h2>AI garment visuals</h2><span class="tiny muted">Model and mannequin generation uses product references</span></div>'
        jobs=s['jobs']
        if not jobs:body+='<div class="card empty">No AI visual jobs yet. Queue the standard pack above.</div>'
        for j in jobs:
            assets=[a for a in s['assets'] if a.get('job_id')==j['id']]
            body+='<div class="card section"><div class="message-top"><div><span class="pill purple">'+app.e(j['status'])+'</span><h3>'+app.e(ce.PRESETS.get(j['preset'],{}).get('label',j['preset']))+'</h3></div><span class="tiny muted">Attempt '+str(j['attempt'])+'</span></div>'
            if not assets and j['status'] in {'Queued','Failed'}:
                if m.secret(): body+='<form method="post" action="/creative/generate"><input type="hidden" name="job_id" value="'+app.e(j['id'])+'"><button class="btn">Generate AI visual</button></form>'
                else: body+=app.notice('Connect AI in Settings & AI to run this job.')
            for a in assets:
                body+='<div class="two section"><div><img style="width:100%;max-height:680px;object-fit:contain;background:#f5f3f6;border-radius:16px" src="/'+app.e(a['relative_path'])+'" alt="AI generated product visual"><p class="tiny muted">AI-generated visual · '+app.e(a['status'])+'</p></div><div><h3>Fidelity gate</h3><p><strong>'+('Not checked' if a['fidelity_score'] is None else f'{float(a["fidelity_score"]):.0f}/100')+'</strong></p>'
                if a.get('fidelity_json'):
                    try:
                        fd=json.loads(a['fidelity_json']);body+='<p>'+app.e(fd.get('summary',''))+'</p>'
                        for issue in fd.get('issues',[]):body+='<div class="readiness-row"><span class="pill warn">CHECK</span><div class="row-main"><small>'+app.e(issue)+'</small></div></div>'
                    except Exception:pass
                if a['fidelity_score'] is None and m.secret():body+='<form method="post" action="/creative/fidelity"><input type="hidden" name="asset_id" value="'+app.e(a['id'])+'"><button class="btn secondary">Run fidelity review</button></form>'
                if a['fidelity_score'] is not None:
                    body+='<div class="toolbar section"><form method="post" action="/creative/approve"><input type="hidden" name="asset_id" value="'+app.e(a['id'])+'"><input type="hidden" name="decision" value="approve"><button class="btn">Approve visual</button></form><form method="post" action="/creative/approve"><input type="hidden" name="asset_id" value="'+app.e(a['id'])+'"><input type="hidden" name="decision" value="reject"><button class="btn secondary">Reject</button></form></div>'
                body+='<p class="helper section">A fidelity score is an automated comparison, not a guarantee. Review textile colour and pattern before using an AI visual as product marketing.</p></div></div>'
            body+='</div>'
        channel=[a for a in s['assets'] if a['asset_kind'] in ce.CHANNEL_SPECS or a['asset_kind']=='promo_reel']
        body+='<div class="section-head"><h2>Ready-to-use channel assets</h2><span class="tiny muted">Deterministic crops / overlays, not repeated garment regeneration</span></div><div class="product-grid">'
        for a in channel:
            if a['asset_kind']=='promo_reel' and a['relative_path'].endswith('.json'):
                body+=f'<div class="card"><span class="pill purple">Reel storyboard</span><h3>9:16 promotional reel</h3><p class="helper">MP4 rendering needs FFmpeg on this Mac. The storyboard and frames are ready.</p></div>';continue
            if a['asset_kind']=='promo_reel':
                body+=f'<div class="card"><video controls style="width:100%;border-radius:14px"><source src="/{app.e(a["relative_path"])}" type="video/mp4"></video><h3>Promotional reel</h3></div>';continue
            body+=f'<article class="product"><img src="/{app.e(a["relative_path"])}" alt="Channel creative"><div class="pbody"><span class="tiny muted">{app.e(a["channel"])} · {app.e(a["aspect_ratio"])}</span><h3>{app.e(ce.CHANNEL_SPECS.get(a["asset_kind"],(a["asset_kind"],))[0])}</h3><p>{app.e(a["source_kind"])}</p></div></article>'
        if not channel:body+='<div class="card empty">Create the social & ad pack above. It can use original photography immediately or an approved AI visual when available.</div>'
        body+='</div><div class="card section"><h2>Publishing handoff</h2><p class="helper">Prepared items are intentionally not auto-published yet. They are ready for future Instagram, Facebook, Pinterest, Meta Ads, email and ecommerce connectors. The CRM keeps the asset and channel relationship now so publishing APIs can be added without rebuilding the creative workflow.</p><div class="table-wrap"><table><tr><th>Channel</th><th>Status</th><th>Caption</th></tr>'
        for x in s['publish']:body+=f'<tr><td>{app.e(x["channel"])}</td><td>{app.e(x["status"])}</td><td>{app.e(x["caption"] or "")}</td></tr>'
        if not s['publish']:body+='<tr><td colspan="3">No channel handoffs yet.</td></tr>'
        body+='</table></div><div class="divider"></div><h3>Turn this product into a campaign</h3><p class="helper">Open the existing guided Campaign Studio with this product preselected. Audience permissions and duplicate checks still apply.</p><div class="toolbar">'+app.button('Plan B2C launch','/campaigns/new?audience=B2C&goal=New%20collection&product_id='+pid,'secondary')+app.button('Plan B2B wholesale launch','/campaigns/new?audience=B2B&goal=Catalogue%20discovery&product_id='+pid,'secondary')+'</div></div>'
        self.send_html(app.layout('Creative workspace',body,'creative'))
