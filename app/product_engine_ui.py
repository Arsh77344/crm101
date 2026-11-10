from __future__ import annotations
import io, json, re, zipfile
import marketing as m
import product_engine as pe
import v35_truth as truth


class ProductEnginePages:
    def v6_get(self,path,q):
        if path=='/product-engine': self.product_engine_home(q)
        elif re.fullmatch(r'/product-engine/intakes/[^/]+',path): self.product_engine_intake(path.split('/')[3])
        elif re.fullmatch(r'/product-engine/products/[^/]+',path): self.product_engine_product(path.split('/')[3],q)
        else: return False
        return True

    def v6_post(self,path,f):
        import app
        v=lambda k,d='':f.get(k,[d])[0]
        if path=='/product-engine/upload':
            archives=getattr(self,'_product_archives',[]) or []
            if not archives: raise ValueError('Choose at least one ZIP containing raw product photographs.')
            requested=v('requested_type','Auto')
            if requested not in {'Auto','Saree','Suit','Dupatta','Fabric','Lehenga','Other'}: raise ValueError('Choose a valid product type.')
            engine=v('engine','local')
            if engine not in {'local','ai'}: raise ValueError('Choose local or AI processing.')
            if engine=='ai' and not m.secret(): raise ValueError('AI is not connected. Use local processing or connect your API key in Settings & AI.')
            created=[]
            for raw,name in archives:
                rid=pe.stage_recoverable_archive(raw,name,requested,engine,pe.setting('product_auto_assets','1')=='1');iid,pids=pe.process_recoverable_archive(rid)
                created.append((iid,pids))
            all_pids=[pid for _,pids in created for pid in pids]
            if v('creative_pack')=='1' and all_pids:
                import creative_studio as cs
                cid=cs.create_campaign({'name':'Product upload launch pack','campaign_type':'New arrival','visual_style':'Luxury studio','background_style':'Warm neutral','subject_mode':'Adult model','variations':'1','target_market':cs.setting('v8_default_market','United Kingdom'),'language':cs.setting('v8_default_language','English')},all_pids,cs.PRESET_BUNDLES['full_launch'])
                cs.generate_all_images(cid)
                return self.redirect('/creative-studio/campaigns/'+cid+'?created=1')
            if len(created)==1:return self.redirect('/product-engine/intakes/'+created[0][0])
            return self.redirect('/product-engine?uploaded='+str(sum(len(x[1]) for x in created)))
        if path=='/product-engine/upload-images':
            images=getattr(self,'_product_images',[]) or []
            if not images: raise ValueError('Choose at least one product photograph.')
            requested=v('requested_type','Auto')
            if requested not in {'Auto','Saree','Suit','Dupatta','Fabric','Lehenga','Other'}: raise ValueError('Choose a valid product type.')
            engine=v('engine','local')
            if engine not in {'local','ai'}: raise ValueError('Choose local or AI processing.')
            if engine=='ai' and not m.secret(): raise ValueError('AI is not connected. Use local processing or connect your API key in Settings & AI.')
            if len(images)>pe.MAX_FILES: raise ValueError(f'Upload no more than {pe.MAX_FILES} images at once. Split larger batches.')
            buf=io.BytesIO()
            with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                for raw,name in images:
                    if not name or __import__('pathlib').Path(name).suffix.lower() not in pe.IMAGE_EXTS: raise ValueError(f'{name or "Unnamed file"}: use JPG, PNG, WEBP, AVIF, HEIC/HEIF, TIFF or BMP.')
                    if len(raw)>30*1024*1024: raise ValueError('Keep each product image under 30 MB.')
                    z.writestr(__import__('pathlib').Path(name).name,raw)
            rid=pe.stage_recoverable_archive(buf.getvalue(),'Direct raw image upload.zip',requested,engine,pe.setting('product_auto_assets','1')=='1');iid,pids=pe.process_recoverable_archive(rid)
            if v('creative_pack')=='1' and pids:
                import creative_studio as cs
                cid=cs.create_campaign({'name':'Product upload launch pack','campaign_type':'New arrival','visual_style':'Luxury studio','background_style':'Warm neutral','subject_mode':'Adult model','variations':'1','target_market':cs.setting('v8_default_market','United Kingdom'),'language':cs.setting('v8_default_language','English')},pids,cs.PRESET_BUNDLES['full_launch'])
                cs.generate_all_images(cid)
                return self.redirect('/creative-studio/campaigns/'+cid+'?created=1')
            return self.redirect('/product-engine/intakes/'+iid+'?direct='+str(len(pids)))
        if re.fullmatch(r'/product-engine/intakes/[^/]+/retry',path):
            old=path.split('/')[3];iid,pids=pe.retry_failed_intake(old);return self.redirect('/product-engine/intakes/'+iid+'?retried=1')
        if re.fullmatch(r'/product-engine/intakes/[^/]+/dismiss',path):
            pe.dismiss_failed_intake(path.split('/')[3]);return self.redirect('/product-engine?dismissed=1')
        if path=='/product-engine/settings':
            pe.save_settings({k:x[0] for k,x in f.items()});return self.redirect('/product-engine?saved=1')
        if path=='/product-engine/scan-inbox':
            results=pe.process_inbox_once();done=sum(x.get('status')=='Processed' for x in results);return self.redirect('/product-engine?scanned='+str(done))
        if path=='/product-engine/open-inbox':
            pe.open_inbox_folder();return self.redirect('/product-engine?opened=1')
        if path=='/product-engine/assets':
            pid=v('product_id');pe.prepare_assets(pid);return self.redirect('/product-engine/products/'+pid+'?assets=1')
        if path=='/product-engine/ai-analyse':
            pid=v('product_id');pe.ai_analyse_product(pid);return self.redirect('/product-engine/products/'+pid+'?ai=1')
        if path=='/product-engine/apply-ai':
            pid=v('product_id');self.apply_ai_suggestions(pid);return self.redirect('/product-engine/products/'+pid+'?applied=1')
        if path=='/product-engine/verify':
            pid=v('product_id');pe.approve_filename_facts(pid,v('evidence'));return self.redirect('/product-engine/products/'+pid+'?verified=1')
        return False

    def apply_ai_suggestions(self,pid):
        fields=pe.fields(pid); suggestions={}
        for f in fields:
            if f['source_type']=='AI inferred' and f['field_value']:
                suggestions[f['field_name']]=f['field_value']
        c=pe.content(pid)
        allowed={'colour','fabric','weave_or_motif','category'}
        with m.connect() as con:
            if suggestions:
                pairs=[(k,v) for k,v in suggestions.items() if k in allowed]
                if pairs:
                    con.execute('UPDATE products SET '+','.join(k+'=?' for k,_ in pairs)+' WHERE product_id=?',tuple(v for _,v in pairs)+(pid,))
            if c.get('suggested_name'):
                con.execute('UPDATE products SET public_product_name=? WHERE product_id=?',(c['suggested_name'][:180],pid))
            if c.get('b2c_description'):
                con.execute('UPDATE products SET description=? WHERE product_id=?',(c['b2c_description'][:5000],pid))
            if c.get('tags_json'):
                try:tags=', '.join(json.loads(c['tags_json']))[:1000]
                except Exception:tags=''
                if tags:con.execute('UPDATE products SET tags=? WHERE product_id=?',(tags,pid))
            con.execute('UPDATE m4_product_review SET confirmed=0 WHERE product_id=?',(pid,))
        collection_names=[]
        if c.get('collections_json'):
            try:
                collection_names=[str(x).strip() for x in json.loads(c['collections_json']) if str(x).strip()]
            except Exception:
                collection_names=[]
        applied_collections=truth.apply_collection_suggestions(pid,collection_names) if collection_names else []
        pe.event(pid,None,'ai.applied',f'AI suggestions applied to the draft. {len(applied_collections)} merchandise collection(s) were linked after owner approval. Product fact verification remains required.')

    def product_engine_home(self,q):
        import app
        pe.initialise()
        intakes=pe.get_intakes()
        count=m.one('SELECT count(*) n FROM products')['n']
        images=m.one('SELECT count(*) n FROM product_images')['n']
        auto=m.one('SELECT count(*) n FROM v6_product_assets')['n']
        reviewed=m.one('SELECT count(*) n FROM m4_product_review WHERE confirmed=1')['n']
        body=app.pagehead('Add products from photos','Upload raw product photography. The system organises the images, prepares product drafts and shows you only what needs review.',app.button('Products','/products','secondary'))
        if q.get('uploaded'):body+=app.notice(q['uploaded'][0]+' product drafts created from the uploaded files.','success')
        if q.get('saved'):body+=app.notice('Product-intake defaults saved.','success')
        if q.get('scanned'):body+=app.notice(q['scanned'][0]+' inbox ZIP(s) processed.','success')
        if q.get('opened'):body+=app.notice('Product inbox opened in Finder. Drop ZIPs there; the local watcher checks it about once a minute.','success')
        if q.get('dismissed'):body+=app.notice('Interrupted intake acknowledged. Its historical record was kept and it no longer appears as an active alert.','success')
        body+='''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">%s</span><strong>Products</strong><span class="helper">Master catalogue records</span></div><div class="card stat-card"><span class="stat-label">%s</span><strong>Raw images</strong><span class="helper">Originals stay untouched</span></div><div class="card stat-card"><span class="stat-label">%s</span><strong>Prepared assets</strong><span class="helper">Web, email, WhatsApp & social sources</span></div><div class="card stat-card"><span class="stat-label">%s</span><strong>Fact-reviewed</strong><span class="helper">Owner/supplier verified</span></div></div>'''%(count,images,auto,reviewed)
        pending=len(pe.inbox_pending())
        ai_state=m.ai_health();ai_ready=ai_state.get('status')=='Connected'
        engine_opts=[('local','Local preparation · no AI/API cost')]
        if ai_ready:engine_opts.append(('ai','AI-assisted image analysis · uses API credits'))
        ai_note=('AI-assisted preparation is ready.' if ai_ready else 'AI is not connected. Local preparation remains available using local drafting and manual review.')
        if ai_ready:
            preparation_control=app.field('Preparation mode','<select name="engine">'+app.options(engine_opts,'ai')+'</select>',ai_note)
            mode_notice='<div class="note success"><strong>AI-assisted Preparation</strong><br>The connected AI provider has passed validation. Review generated facts before accepting uncertain claims.</div>'
        else:
            preparation_control=app.field('Preparation mode','<div class="mode-choice"><strong>Local Preparation</strong><span>No AI/API call will be made.</span></div><input type="hidden" name="engine" value="local">',ai_note)
            mode_notice='<div class="note warn"><strong>Local Preparation Mode</strong><br>'+app.e(ai_note)+' <a href="/settings#ai">Configure AI</a>.</div>'
        body+='<div class="choice-hero"><section class="choice-card recommended"><div class="eyebrow">RECOMMENDED</div><h2>Upload product photos</h2><p>Select one or more raw photographs. Descriptive filenames help group images, but they are never treated as your brand. Originals are kept unchanged.</p><form method="post" action="/product-engine/upload-images" enctype="multipart/form-data"><div class="file-well section">'+app.field('Choose product photos','<input type="file" name="product_images" accept="image/jpeg,image/png,image/webp,image/avif,image/heic,image/heif,image/tiff,image/bmp,.jpg,.jpeg,.png,.webp,.avif,.heic,.heif,.tif,.tiff,.bmp" multiple required>','You can select several images at once.')+'</div><div class="formgrid section">'+app.field('What kind of product?','<select name="requested_type">'+app.options([('Auto','Let the system decide'),('Saree','Saree'),('Suit','Suit'),('Dupatta','Dupatta'),('Fabric','Fabric'),('Lehenga','Lehenga'),('Other','Other')])+'</select>')+preparation_control+'</div>'+mode_notice+'<label class="checkline section"><input type="checkbox" name="creative_pack" value="1" checked> Also prepare social, Meta and Google image sizes from the original photography</label><div class="form-foot"><button class="btn">'+('Prepare with AI' if ai_ready else 'Prepare locally')+'</button></div></form></section><section class="choice-card"><div class="eyebrow">WHAT HAPPENS NEXT</div><h2>You review the exceptions</h2><p>The system groups images, drafts product information, prepares safe image sizes and flags missing price, stock, uncertain facts or possible duplicates.</p><ol class="helper"><li>Images grouped into products</li><li>Product draft created</li><li>Channel-sized assets prepared</li><li>Uncertain facts held for your review</li></ol>'+app.button('Open product workflow','/product-workspace','secondary')+'</section></div>'
        body+='<details class="manual-entry section"><summary>Advanced intake options</summary><div class="manual-body"><div class="two section"><div><h3>Watched ZIP inbox</h3><p class="helper">For batch operations only. The local worker can watch a product_inbox folder for ZIP files while the CRM is running.</p><div class="toolbar"><span class="pill purple">'+str(pending)+' waiting</span><form method="post" action="/product-engine/open-inbox"><button class="btn secondary">Open inbox in Finder</button></form><form method="post" action="/product-engine/scan-inbox"><button class="btn secondary">Scan now</button></form></div></div><div><h3>Upload ZIP folders</h3><form method="post" action="/product-engine/upload" enctype="multipart/form-data"><div class="file-well">'+app.field('Product ZIP file(s)','<input type="file" name="product_archives" accept=".zip,application/zip" multiple required>','One or more ZIP files containing product photographs.')+'</div><div class="formgrid section">'+app.field('Product type','<select name="requested_type">'+app.options([('Auto','Let the system decide'),('Saree','Saree'),('Suit','Suit'),('Dupatta','Dupatta'),('Fabric','Fabric'),('Lehenga','Lehenga'),('Other','Other')])+'</select>')+app.field('Preparation','<select name="engine">'+app.options(engine_opts,'local')+'</select>')+'</div><label class="checkline section"><input type="checkbox" name="creative_pack" value="1" checked> Prepare channel-sized image derivatives</label><div class="form-foot"><button class="btn secondary">Process ZIP photography</button></div></form></div></div></div></details>'
        body+='<div class="card section"><div class="eyebrow">AUTOMATIC PREPARATION</div><h2>From photography to a reviewable product draft</h2><div class="three">'
        steps=[('1','Organise photos','Groups related images and identifies useful product views.'),('2','Prepare the draft','Drafts safe product information, tags and SEO copy from available evidence.'),('3','Surface exceptions','Keeps price, stock and uncertain product claims for human review.')]
        for n,t,d in steps:body+=f'<div class="concept-card"><span class="round-number">{n}</span><h3 class="section">{t}</h3><p>{d}</p></div>'
        body+='</div>'+app.notice('The system will not turn visual appearance into claims such as pure silk, handloom, certification or real gold/silver zari. Those remain review items.')+'</div>'
        body+='<div class="two section"><div><div class="section-head"><h2>Recent product intakes</h2><span class="tiny muted">Newest first</span></div>'
        if not intakes:body+='<div class="card empty">No product intakes yet. Existing migrated products and raw-image records remain untouched.</div>'
        for r in intakes:
            status_kind='warn' if r['status'] in {'Failed','Processing'} else 'purple'
            extra=''
            if r['status']=='Failed':
                extra='<p class="helper section">This intake was interrupted before completion. Existing records were kept; '+('the saved upload can be retried from the intake page.' if pe.recovery_available(r['id']) else 'select the source photographs again to retry.')+'</p>'
            warning_badge='<span class="pill warn">'+str(r["warning_count"])+" warning(s)</span>" if r["warning_count"] else ""
            body+=f'<a class="card section" style="display:block;text-decoration:none;color:inherit" href="/product-engine/intakes/{app.e(r["id"])}"><div class="message-top"><div><span class="pill {status_kind}">{app.e(r["status"])}</span><h3>{app.e(r["archive_name"])}</h3></div><span class="tiny muted">{app.e(r["created_at"])}</span></div><div class="toolbar"><span class="tag">{r["product_count"]} product(s)</span><span class="tag">{r["image_count"]} image(s)</span><span class="tag">{app.e(r["engine"])}</span>{warning_badge}</div>{extra}</a>'
        body+='</div><details class="manual-entry"><summary>Advanced product-intake defaults</summary><div class="manual-body"><form method="post" action="/product-engine/settings" class="section">'
        body+=app.field('Ignore source prefix token(s)','<input name="product_ignore_tokens" value="'+app.e(pe.setting('product_ignore_tokens','Usaya'))+'">','Comma separated. These labels stay in source metadata but are removed from customer-facing names.')
        body+=app.field('Default product type','<select name="default_product_type">'+app.options(['Saree','Suit','Dupatta','Fabric','Lehenga','Other'],pe.setting('default_product_type','Saree'))+'</select>')
        body+='<p><label class="checkline"><input type="checkbox" name="product_auto_assets" value="1" '+('checked' if pe.setting('product_auto_assets','1')=='1' else '')+'>Prepare channel-sized image derivatives automatically after intake.</label></p><button class="btn secondary">Save defaults</button></form></div></details></div>'
        self.send_html(app.layout('Product preparation',body,'product_engine'))

    def product_engine_intake(self,iid):
        import app
        r,products=pe.intake(iid)
        body=app.pagehead('Product intake',r['archive_name'],app.button('New intake','/product-engine','secondary')+app.button('Products','/products','secondary'))
        body+=f'<div class="toolbar"><span class="pill {"warn" if r["status"] in {"Failed","Processing"} else "purple"}">{app.e(r["status"])}</span><span class="tag">{r["product_count"]} product(s)</span><span class="tag">{r["image_count"]} accepted raw images</span><span class="tag">{app.e(r["engine"])}</span></div>'
        if r['status']=='Failed':
            if pe.recovery_available(iid):
                body+=app.notice('This intake was interrupted before it completed. The original upload is still stored privately on this Mac, so you can retry without selecting the files again. Existing product/image records are preserved.','warn')
                body+='<div class="toolbar section"><form method="post" action="/product-engine/intakes/'+app.e(iid)+'/retry"><button class="btn">Retry saved upload</button></form><form method="post" action="/product-engine/intakes/'+app.e(iid)+'/dismiss"><button class="btn secondary">Dismiss this alert</button></form></div>'
            else:
                body+=app.notice('This intake was interrupted before it completed. Existing product or image records were not deleted. The original upload is not available for automatic retry, so select the source photographs again.','warn')
                body+='<form class="section" method="post" action="/product-engine/intakes/'+app.e(iid)+'/dismiss"><button class="btn secondary">Dismiss this alert</button></form>'
        elif r['status']=='Dismissed':body+=app.notice('This interrupted intake was acknowledged. It is kept only as historical evidence.','info')
        issues=m.rows('SELECT filename,issue FROM v18_3_intake_file_issues WHERE intake_id=? ORDER BY created_at,filename',(iid,))
        if issues:
            body+='<div class="card section"><h2>Files that need attention</h2><p class="helper">The valid photographs were processed. These files were not used, so you can re-export or replace them without losing the rest of the intake.</p><div class="table-wrap"><table><tr><th>File</th><th>Why it was skipped</th></tr>'
            for issue in issues: body+=f'<tr><td>{app.e(issue["filename"])}</td><td>{app.e(issue["issue"])}</td></tr>'
            body+='</table></div></div>'
        body+='<div class="product-grid section">'
        for p in products:
            ready=pe.readiness(p['product_id'])
            body+=f'<article class="product"><a href="/product-engine/products/{app.e(p["product_id"])}">'+(f'<img src="/{app.e(p["img"])}" alt="Product intake image">' if p['img'] else '<div style="aspect-ratio:4/5;background:#eee"></div>')+'</a><div class="pbody"><span class="tiny muted">'+app.e(p['product_code'] or p['internal_sku'])+'</span><h3>'+app.e(p['public_product_name'])+'</h3><p>'+app.e(p['colour'] or 'Colour not identified')+' / '+app.e(p['category'])+'</p><div class="toolbar"><span class="pill '+('good' if ready['confirmed'] else 'warn')+'">'+('Facts verified' if ready['confirmed'] else 'Needs fact review')+'</span>'+(f'<span class="pill warn">Possible duplicate</span>' if p['duplicate_group'] else '')+'</div><div class="tiny muted section">Catalogue '+str(ready['catalogue'])+'% · Sales '+str(ready['sales'])+'% · Marketing '+str(ready['marketing'])+'%</div></div></article>'
        body+='</div>'
        self.send_html(app.layout('Product intake',body,'product_engine'))

    def product_engine_product(self,pid,q):
        import app
        p=m.one('''SELECT p.*,coalesce(r.confirmed,0) confirmed,r.evidence FROM products p LEFT JOIN m4_product_review r USING(product_id) WHERE p.product_id=?''',(pid,))
        if not p:raise ValueError('Product not found.')
        imgs=m.rows('SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC,image_role',(pid,))
        c=pe.content(pid);fs=pe.fields(pid);ready=pe.readiness(pid);it=pe.product_intake(pid)
        assets=m.rows('SELECT variant,count(*) n,method FROM v6_product_assets WHERE product_id=? GROUP BY variant,method ORDER BY variant',(pid,))
        body=app.pagehead(p['public_product_name'],p['product_code'] or p['internal_sku'],app.button('Create full asset pack','/creative-studio/new?product='+pid+'&bundle=full_launch')+app.button('Open full product record','/products/'+pid,'secondary')+app.button('Product engine','/product-engine','secondary'))
        for key,msg in [('assets','Channel-sized product assets prepared.'),('ai','AI analysis saved as reviewable suggestions.'),('applied','AI suggestions applied to the draft. Verification is still required.'),('verified','Product facts marked as verified using your evidence note.')]:
            if q.get(key):body+=app.notice(msg,'success')
        body+='<div class="stats-grid"><div class="card stat-card"><span class="stat-label">'+str(ready['catalogue'])+'%</span><strong>Catalogue</strong><span class="helper">Identity, imagery, SEO and copy</span></div><div class="card stat-card"><span class="stat-label">'+str(ready['sales'])+'%</span><strong>Sales</strong><span class="helper">Fact review, pricing, stock and MOQ</span></div><div class="card stat-card"><span class="stat-label">'+str(ready['marketing'])+'%</span><strong>Marketing</strong><span class="helper">Verified facts, copy, assets and tags</span></div><div class="card stat-card"><span class="stat-label">'+str(ready['images'])+'</span><strong>Raw images</strong><span class="helper">'+str(ready['assets'])+' prepared derivatives</span></div></div>'
        if ready['blockers'] or ready['warnings']:
            body+='<div class="card section"><h2>Needs attention</h2>'
            for x in ready['blockers']:body+=f'<div class="readiness-row"><span class="pill warn">BLOCKER</span><div class="row-main"><strong>{app.e(x)}</strong></div></div>'
            for x in ready['warnings']:body+=f'<div class="readiness-row"><span class="pill">REVIEW</span><div class="row-main"><strong>{app.e(x)}</strong></div></div>'
            body+='</div>'
        body+='<div class="two section"><div><div class="card"><div class="gallery">'
        for im in imgs:body+=f'<figure style="margin:0"><img src="/{app.e(im["relative_path"])}" alt="{app.e(im["image_role"])}"><figcaption class="tiny muted">{app.e(im["image_role"])} · {app.e(im["original_filename"])}</figcaption></figure>'
        body+='</div></div><div class="card section"><h2>What the engine extracted</h2><div class="table-wrap"><table><tr><th>Field</th><th>Value</th><th>Source</th><th>Confidence</th><th>Status</th></tr>'
        if fs:
            for f in fs:body+=f'<tr><td>{app.e(f["field_name"])}</td><td>{app.e(f["field_value"])}</td><td>{app.e(f["source_type"])}</td><td>{("%.0f%%"%(float(f["confidence"])*100)) if f["confidence"] is not None else "—"}</td><td>{app.e(f["verification_status"])}</td></tr>'
        else:body+='<tr><td colspan="5">No extraction metadata has been saved yet.</td></tr>'
        body+='</table></div></div></div><div><div class="card"><h2>Source & processing</h2><div class="kv">'
        for label,val in [('Source product name',p['source_product_name']),('Customer-facing draft',p['public_product_name']),('Source archive',it['archive_name'] if it else 'Legacy/manual product'),('Processing engine',it['engine'] if it else 'Legacy/manual'),('Fact review','Verified' if p['confirmed'] else 'Needs review')]:body+=f'<div>{label}</div><div>{app.e(val)}</div>'
        body+='</div></div><div class="card section"><h2>Automation actions</h2><p class="helper">These actions never change price, stock or verification status automatically.</p><form method="post" action="/product-engine/assets"><input type="hidden" name="product_id" value="'+app.e(pid)+'"><button class="btn secondary" style="width:100%">Prepare / refresh image variants</button></form><div class="section"></div>'
        if m.secret():
            body+='<form method="post" action="/product-engine/ai-analyse" data-confirm="Run a paid AI image + filename analysis for this product? Selected images and source filenames will be sent to the configured OpenAI API account."><input type="hidden" name="product_id" value="'+app.e(pid)+'"><button class="btn" style="width:100%">Run AI image analysis</button></form>'
        else:body+=app.notice('AI is not connected. Local filename processing and image preparation still work. Connect AI in Settings & AI if you want visual analysis.')
        ai_fields=any(f['source_type']=='AI inferred' for f in fs)
        if ai_fields:body+='<div class="section"><form method="post" action="/product-engine/apply-ai" data-confirm="Apply the latest AI suggestions to this product draft? This does not verify them."><input type="hidden" name="product_id" value="'+app.e(pid)+'"><button class="btn secondary" style="width:100%">Apply AI suggestions to draft</button></form></div>'
        body+='</div><div class="card section"><h2>Verify for sales & marketing</h2><p class="helper">Use an owner check, supplier specification or manufacturing record. Image appearance alone is not evidence of composition or provenance.</p><form method="post" action="/product-engine/verify"><input type="hidden" name="product_id" value="'+app.e(pid)+'">'+app.field('Verification note','<input name="evidence" required value="'+app.e(p['evidence'] or '')+'" placeholder="Owner checked against manufacturing record / supplier spec...">')+'<button class="btn" style="width:100%">Verify current product facts</button></form></div></div></div>'
        body+='<div class="two section"><div class="card"><h2>Generated selling copy</h2><div class="readiness-row"><strong>B2C</strong><span>'+app.e(c.get('b2c_description') or 'Not generated')+'</span></div><div class="readiness-row"><strong>B2B</strong><span>'+app.e(c.get('b2b_description') or 'Not generated')+'</span></div><div class="readiness-row"><strong>Short specification</strong><span>'+app.e(c.get('short_description') or 'Not generated')+'</span></div></div><div class="card"><h2>SEO & merchandising</h2><div class="kv">'
        def jlist(key):
            try:return ', '.join(json.loads(c.get(key) or '[]'))
            except Exception:return ''
        for label,val in [('SEO title',c.get('seo_title')),('Meta description',c.get('meta_description')),('Slug',c.get('slug')),('Tags',jlist('tags_json')),('Suggested collections',jlist('collections_json'))]:body+=f'<div>{label}</div><div>{app.e(val or "Not generated")}</div>'
        body+='</div></div></div><div class="card section"><h2>Prepared channel assets</h2><div class="toolbar">'
        if assets:
            for a in assets:body+=f'<span class="tag">{app.e(a["variant"])} · {a["n"]} · {app.e(a["method"])}</span>'
        else:body+='<span class="helper">No derivatives yet. Prepare image variants above.</span>'
        body+='</div><p class="tiny muted">Prepared assets are resized derivatives for channel handoff. They do not perform background removal or generative retouching. Originals remain unchanged.</p></div>'
        self.send_html(app.layout('Product engine review',body,'product_engine'))
