from __future__ import annotations
import json,re,urllib.parse
import marketing as m
import creative_engine as ce
import creative_studio as cs

class CreativeStudioPages:
    def v8_get(self,path,q):
        if path=='/creative-studio':self.creative_studio_home(q)
        elif path=='/creative-studio/new':self.creative_studio_new(q)
        elif re.fullmatch(r'/creative-studio/campaigns/[^/]+',path):self.creative_studio_campaign(path.split('/')[3],q)
        elif re.fullmatch(r'/creative-studio/campaigns/[^/]+/export',path):
            cid=path.split('/')[3];cs.require_active_campaign(cid);raw=cs.export_campaign_zip(cid);return self.send_file(raw,'creative_campaign_'+cid+'.zip','application/zip')
        else:return False
        return True

    def v8_post(self,path,f):
        v=lambda k,d='':f.get(k,[d])[0]
        if path=='/creative-studio/settings':
            cs.save_default_settings({k:x[0] for k,x in f.items()});return self.redirect('/creative-studio?saved=1')
        if path=='/creative-studio/video-key':
            cs.save_video_secret(v('video_api_key'));return self.redirect('/creative-studio?video_key=1')
        if path=='/creative-studio/video-key/clear':
            cs.clear_video_secret();return self.redirect('/creative-studio?video_key_cleared=1')
        if path=='/creative-studio/music':
            upload=getattr(self,'_creative_music_upload',None)
            if not upload:raise ValueError('Choose an audio file first.')
            cs.save_music(upload[0],upload[1],v('label') or upload[1]);return self.redirect('/creative-studio?music=1')
        if path=='/creative-studio/create':
            products=f.get('product_id',[]);placements=f.get('placement',[]);bundle=v('bundle','')
            if bundle and not placements:placements=cs.PRESET_BUNDLES.get(bundle,[])
            cid=cs.create_campaign({k:x[0] for k,x in f.items()},products,placements);return self.redirect('/creative-studio/campaigns/'+cid+'?created=1')
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/(archive|restore)',path)
        if m1:
            cid,action=m1.group(1),m1.group(2)
            (cs.archive_campaign if action=='archive' else cs.restore_campaign)(cid)
            return self.redirect('/creative-studio/campaigns/'+cid+'?'+action+'d=1')
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/(update|master|master-pack|master-review|images|videos|video-job|publish-prepare|business-plan|asset-review|asset-regenerate)',path)
        if m1:cs.require_active_campaign(m1.group(1))
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/update',path)
        if m1:
            cid=m1.group(1);cs.update_campaign(cid,{k:x[0] for k,x in f.items()});return self.redirect('/creative-studio/campaigns/'+cid+'?updated=1')
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/master',path)
        if m1:
            cid=m1.group(1);pid=v('product_id');variation=int(v('variation','1'));kind=v('master_kind','model');aid=cs.generate_master(cid,pid,variation,kind);return self.redirect('/creative-studio/campaigns/'+cid+'?master='+urllib.parse.quote(aid))
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/master-pack',path)
        if m1:
            cid=m1.group(1);kinds=f.get('master_kind',[]);result=cs.generate_master_pack(cid,kinds,v('master_variations','1'));return self.redirect('/creative-studio/campaigns/'+cid+'?master_pack='+str(result['generated'])+'&master_errors='+str(len(result['errors'])))
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/master-review',path)
        if m1:
            cid=m1.group(1);cs.approve_master(v('source_asset_id'),v('decision','approve')=='approve');return self.redirect('/creative-studio/campaigns/'+cid+'?review=1')
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/images',path)
        if m1:
            cid=m1.group(1);result=cs.generate_all_images(cid,force=v('force')=='1');return self.redirect('/creative-studio/campaigns/'+cid+'?images='+str(result['placement_assets'])+'&details='+str(result['detail_assets']))
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/videos',path)
        if m1:
            cid=m1.group(1);created=0;processed=0;provider=v('provider',cs.setting('v8_video_provider','local'));duration=(v('custom_duration','').strip() or v('duration','15'));video_style=v('video_style','Product showcase');music=v('music_id','');voice=v('voiceover_mode','none');voice_text=v('voiceover_text','');transition=v('transition_style','Fade');captions=v('captions_mode','off');logo_mode=v('video_logo_mode','Use logo')
            for p in cs.campaign_products(cid):
                for pl in cs.campaign_placements(cid):
                    custom=m.one('SELECT media_type FROM v8_custom_placements WHERE campaign_id=? AND placement_key=?',(cid,pl['placement_key']))
                    if pl['placement_key'] not in cs.VIDEO_PLACEMENTS and (not custom or custom['media_type']!='video'):continue
                    jid=cs.create_video_job(cid,p['product_id'],pl['placement_key'],{'provider':provider,'duration':duration,'video_style':video_style,'music_mode':music or 'none','voiceover_mode':voice,'voiceover_text':voice_text,'language':cs.campaign(cid)['language'],'transition_style':transition,'captions_mode':captions,'logo_mode':logo_mode});created+=1
                    # Local videos can be processed in a batch safely. Veo is paid and is left queued unless explicit paid_run is checked.
                    if provider=='local' or v('paid_run')=='1':
                        cs.process_video_job(jid,music);processed+=1
            return self.redirect('/creative-studio/campaigns/'+cid+f'?video_jobs={created}&video_done={processed}')
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/video-job',path)
        if m1:
            cid=m1.group(1);cs.process_video_job(v('job_id'),v('music_id'));return self.redirect('/creative-studio/campaigns/'+cid+'?video_one=1')
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/publish-prepare',path)
        if m1:
            cid=m1.group(1);made=cs.prepare_publish_handoffs(cid);return self.redirect('/creative-studio/campaigns/'+cid+'?handoffs='+str(made))
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/business-plan',path)
        if m1:
            cid=m1.group(1);ucid=cs.ensure_unified_campaign(cid);return self.redirect('/campaign-builder/'+ucid)
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/asset-review',path)
        if m1:
            cid=m1.group(1);cs.update_asset_status(v('asset_id'),v('decision','Approved'));return self.redirect('/creative-studio/campaigns/'+cid+'?asset_review=1')
        m1=re.fullmatch(r'/creative-studio/campaigns/([^/]+)/asset-regenerate',path)
        if m1:
            cid=m1.group(1);cs.regenerate_asset(v('asset_id'));return self.redirect('/creative-studio/campaigns/'+cid+'?regenerated=1')
        return False

    def creative_studio_home(self,q):
        import app
        cs.initialise();view=(q.get('view') or ['active'])[0];archived=view=='archived';all_camps=cs.list_campaigns(include_archived=True);camps=[c for c in all_camps if (c.get('status')=='Archived')==archived];products=m.products();img_count=m.one("SELECT count(*) n FROM v8_creative_campaign_assets WHERE media_type='image' AND status<>'Archived'")['n'];vid_count=m.one("SELECT count(*) n FROM v8_creative_campaign_assets WHERE media_type='video' AND status<>'Archived'")['n'];review=m.one("SELECT count(*) n FROM v8_creative_campaign_assets WHERE status IN ('Needs review','Fidelity review','Needs correction')")['n']
        active_count=sum(1 for c in all_camps if c.get('status')!='Archived');archived_count=len(all_camps)-active_count
        actions=app.button(f'Active ({active_count})','/creative-studio?view=active','' if not archived else 'secondary')+app.button(f'Archived ({archived_count})','/creative-studio?view=archived','' if archived else 'secondary')+app.button('AI product engine','/product-engine','secondary')
        if not archived:actions=app.button('New creative campaign','/creative-studio/new')+actions
        body=app.pagehead('Archived creative campaigns' if archived else 'AI Creative Studio','Archived creative campaigns retain generated assets and handoff history but are read-only until restored.' if archived else 'Upload products once, then build product-faithful image and video packs for social, Meta Ads and Google Ads.',actions)
        for key,msg in [('saved','Creative Studio defaults saved.'),('video_key','AI video key saved locally.'),('video_key_cleared','AI video key removed.'),('music','Music track uploaded for video edits.')]:
            if q.get(key):body+=app.notice(msg,'success')
        body+=f'''<div class="stats-grid"><div class="card stat-card"><span class="stat-label">{len(camps)}</span><strong>Creative campaigns</strong><span class="helper">Product → campaign → placement</span></div><div class="card stat-card"><span class="stat-label">{img_count}</span><strong>Image assets</strong><span class="helper">Placement-specific versions</span></div><div class="card stat-card"><span class="stat-label">{vid_count}</span><strong>Video assets</strong><span class="helper">Reels / Stories / YouTube</span></div><div class="card stat-card"><span class="stat-label">{review}</span><strong>Needs review</strong><span class="helper">AI fidelity / owner checks</span></div></div>'''
        body+='''<div class="card section"><div class="eyebrow">Automation-first workflow</div><h2>Raw product photos → complete campaign asset pack</h2><div class="flow"><span>Raw images</span><b>→</b><span>AI product understanding</span><b>→</b><span>Model / mannequin / studio master</span><b>→</b><span>Fidelity gate</span><b>→</b><span>Placement-specific images</span><b>→</b><span>Reels / video ads</span><b>→</b><span>Campaign handoff</span></div><p class="helper section">The garment is generated once as a controlled master and fidelity-checked. Approved masters are then intelligently recomposed for each placement instead of repeatedly asking AI to redraw the textile. This reduces cost and product drift.</p></div>'''
        body+='<div class="two section"><div><div class="section-head"><h2>Creative campaigns</h2><span class="tiny muted">Batch multiple products and placements</span></div>'
        if not camps:body+='<div class="card empty">No Creative Studio campaign yet. Start with one product and a recommended bundle, then expand to batch generation.</div>'
        for c in camps[:20]:
            body+=f'''<div class="card section"><div class="message-top"><div><span class="pill purple">{app.e(c['campaign_type'])}</span><h3>{app.e(c['name'])}</h3><p class="helper">{c['product_count']} product(s) · {c['asset_count']} asset(s) · {app.e(c['target_market'])} · {app.e(c['language'])}</p></div>{app.button('Open','/creative-studio/campaigns/'+c['id'],'secondary small')}</div></div>'''
        body+='</div><div><div class="card"><div class="eyebrow">Creative defaults</div><h2>Simple owner settings</h2><form method="post" action="/creative-studio/settings">'
        body+=app.field('Default target market','<input name="v8_default_market" value="'+app.e(cs.setting('v8_default_market','United Kingdom'))+'">')
        body+=app.field('Default language','<input name="v8_default_language" value="'+app.e(cs.setting('v8_default_language','English'))+'">')
        body+=app.field('Default image variations','<select name="v8_default_variations">'+app.options(['1','2','3','4'],cs.setting('v8_default_variations','2'))+'</select>','Each placement can have 1–4 layout variations without redrawing the product.')
        selected_video_mode=cs.setting('v8_video_provider','local')
        body+=app.field('Default video mode','<select name="v8_video_provider">'+app.options([('local','Local motion edit from approved images'),('veo','AI motion from approved images')],selected_video_mode)+'</select>')
        body+='<p><label class="checkline"><input type="checkbox" name="v8_auto_detail_pack" value="1" '+('checked' if cs.setting('v8_auto_detail_pack','1')=='1' else '')+'>Automatically prepare safe detail crops from original border/pallu/close-up photos</label></p><button class="btn">Save defaults</button></form>'
        video_key_present=bool(cs.video_secret())
        veo_model=cs.setting('v8_veo_model','veo-3.1-generate-preview')
        ai_video_state='Not connected'
        ai_video_kind='warn'
        ai_video_detail='No Google/Gemini video credential is stored. Local video preparation remains available.'
        if video_key_present:
            ai_video_state='Configured · validation required'
            ai_video_kind='purple'
            ai_video_detail='Credentials and model are configured, but this capability is not called operational until a real provider video request succeeds.'
            try:
                row=m.one("SELECT id FROM v13_ai_usage WHERE task_key='video_generation' AND status='Completed' ORDER BY created_at DESC LIMIT 1") if m.table_exists('v13_ai_usage') else None
            except Exception:
                row=None
            if row:
                ai_video_state='Validated by completed request'
                ai_video_kind='good'
                ai_video_detail='A real provider video request has completed successfully in this workspace.'
        body+=f'<div class="divider"></div><h3>Video generation</h3><p class="helper">Local video preparation and optional AI motion are separate capabilities.</p><div class="readiness-row"><div class="row-main"><strong>Local video preparation</strong><small>Builds motion edits from approved product images without calling an AI provider.</small></div><span class="pill good">Ready</span></div><div class="readiness-row"><div class="row-main"><strong>AI motion generation</strong><small>{app.e(ai_video_detail)}</small></div><span class="pill {ai_video_kind}">{app.e(ai_video_state)}</span></div>'+app.button('Configure AI provider','/settings#ai','secondary')
        body+='<div class="divider"></div><h3>Music library</h3><form method="post" action="/creative-studio/music" enctype="multipart/form-data"><label class="field">Track label<input name="label" placeholder="Commercial-safe instrumental"></label><label class="field">Audio file<input type="file" name="music_file" accept="audio/*" required><small>Choose a commercially licensed audio file.</small></label><button class="btn secondary section">Upload track</button></form><p class="helper">Only use music you are licensed to use commercially. Meta also offers a separate Sound Collection for commercial use.</p></div></div></div>'
        self.send_html(app.layout('AI Creative Studio',body,'creative_studio'))

    def creative_studio_new(self,q):
        import app
        cs.initialise();products=m.products();bundle=(q.get('bundle') or ['full_launch'])[0];preselected=set(q.get('product') or [])
        body=app.pagehead('New creative campaign','Choose products once, then select the placements you want. Recommended dimensions are built in.',app.button('Back','/creative-studio','secondary'))
        body+="""<form method="post" action="/creative-studio/create"><div class="two"><div><div class="card"><div class="eyebrow">1. Products</div><h2>What are you marketing?</h2><label class="checkline"><input type="checkbox" onclick="document.querySelectorAll('.creative-product-select').forEach(x=>x.checked=this.checked)"> Select / clear all products</label><div class="product-grid section">"""
        for p in products:
            img=p.get('img') or '';checked=' checked' if p['product_id'] in preselected else '';body+=f'''<label class="product selectable"><img src="/{app.e(img)}" alt=""><div class="pbody"><input type="checkbox" class="creative-product-select" name="product_id" value="{app.e(p['product_id'])}"{checked}> <strong>{app.e(p['public_product_name'])}</strong><p class="tiny muted">{app.e(p['product_code'] or p['internal_sku'])}</p></div></label>'''
        if not products:body+='<div class="empty">Add raw product photos in the AI Product Engine first.</div>'
        body+='</div></div><div class="card section"><div class="eyebrow">2. Campaign brief</div><h2>Keep it simple</h2>'
        body+=app.field('Campaign name','<input name="name" value="New collection creative pack" required>')
        body+=app.field('Campaign type','<select name="campaign_type">'+app.options(cs.CAMPAIGN_TYPES,'Collection launch')+'</select>')
        body+=app.field('Target market / region','<input name="target_market" value="'+app.e(cs.setting('v8_default_market','United Kingdom'))+'">')
        body+=app.field('Language','<input name="language" value="'+app.e(cs.setting('v8_default_language','English'))+'">')
        body+=app.field('Visual style','<select name="visual_style">'+app.options(cs.VISUAL_STYLES,'Luxury studio')+'</select>')
        body+=app.field('Background style','<select name="background_style">'+app.options(cs.BACKGROUND_STYLES,'Warm neutral')+'</select>')
        body+=app.field('Product presentation','<select name="subject_mode">'+app.options(cs.SUBJECT_MODES,'Adult model')+'</select>')
        body+=app.field('Model style','<select name="model_style">'+app.options(cs.MODEL_STYLES,'South Asian adult fashion model')+'</select>')
        body+='</div></div><div><div class="card"><div class="eyebrow">3. Message & branding</div><h2>What should the creative say?</h2>'
        body+=app.field('Text mode','<select name="text_mode">'+app.options(['Marketing text','No text'],'Marketing text')+'</select>')
        body+=app.field('Promotional message','<input name="promotional_message" placeholder="Discover the new Banarasi collection">','Google Search / Performance Max image assets will remain text-free even when marketing text is selected.')
        body+=app.field('CTA','<input name="cta" value="'+app.e(ce.setting('creative_cta','Explore the collection'))+'">')
        body+=app.field('Product price text','<input name="price_text" placeholder="From ₹18,900 or £189">')
        body+=app.field('Offer / discount','<input name="offer_text" placeholder="New arrival · Limited pieces">')
        body+=app.field('Logo','<select name="logo_mode">'+app.options(['Use logo','No logo'],'Use logo')+'</select>')
        body+=app.field('Layout variations per image placement','<select name="variations">'+app.options(['1','2','3','4'],cs.setting('v8_default_variations','2'))+'</select>')
        body+='<details><summary><strong>Custom dimensions (optional)</strong></summary><div class="two section">'+app.field('Custom image width (px)','<input type="number" name="custom_image_width" min="100" max="4096" placeholder="e.g. 1080">')+app.field('Custom image height (px)','<input type="number" name="custom_image_height" min="100" max="4096" placeholder="e.g. 1440">')+app.field('Custom image label','<input name="custom_image_label" placeholder="Retailer portrait asset">')+app.field('Custom video width (px)','<input type="number" name="custom_video_width" min="100" max="4096" placeholder="e.g. 1080">')+app.field('Custom video height (px)','<input type="number" name="custom_video_height" min="100" max="4096" placeholder="e.g. 1920">')+app.field('Custom video label','<input name="custom_video_label" placeholder="Marketplace video">')+'</div></details>'
        body+='</div><div class="card section"><div class="eyebrow">4. Platform presets</div><h2>Where will this run?</h2><label class="field">Quick bundle<select name="bundle">'+app.options([('instagram_launch','Instagram launch pack'),('meta_ads','Meta Ads pack'),('google_ads','Google Ads pack'),('full_social','Full organic social pack'),('full_launch','Full launch: social + Meta + Google')],bundle)+'</select><small>Use this if you do not tick individual placements below.</small></label><div class="divider"></div><h3>Or choose placements</h3>'
        for platform,items in cs.placement_groups().items():
            body+=f'<details><summary><strong>{app.e(platform)}</strong></summary><div class="section">'
            for key,spec in items:
                badge='video' if key in cs.VIDEO_PLACEMENTS else f"{spec['size'][0]}×{spec['size'][1]}"
                body+=f'<label class="checkline"><input type="checkbox" name="placement" value="{app.e(key)}"> {app.e(spec["label"])} <span class="tiny muted">{app.e(spec["ratio"])} · {badge}</span></label>'
            body+='</div></details>'
        body+='<button class="btn section" style="width:100%">Create creative campaign</button></div></div></div></form>'
        self.send_html(app.layout('New creative campaign',body,'creative_studio'))

    def creative_studio_campaign(self,cid,q):
        import app
        c=cs.campaign(cid);archived=c.get('status')=='Archived';products=cs.campaign_products(cid);placements=cs.campaign_placements(cid);assets=cs.campaign_assets(cid);jobs=m.rows('SELECT * FROM v8_video_jobs WHERE campaign_id=? ORDER BY created_at DESC',(cid,))
        life=(f'<form method="post" action="/creative-studio/campaigns/{app.e(cid)}/restore" data-confirm="Restore this creative campaign to Draft?"><button class="btn">Restore</button></form>' if archived else f'<form method="post" action="/creative-studio/campaigns/{app.e(cid)}/archive" data-confirm="Archive this creative campaign? Assets and history will be preserved."><button class="btn secondary">Archive</button></form>')
        actions=app.button('All creative work','/creative-studio','secondary')+life
        if not archived:actions=app.button('Export ZIP','/creative-studio/campaigns/'+cid+'/export','secondary')+actions
        body=app.pagehead(c['name'],f"{c['campaign_type']} · {c['target_market']} · {c['language']}",actions)
        if archived:body+=app.notice('This creative campaign is archived and read-only. Restore it before editing the brief, generating assets, reviewing outputs or exporting handoffs.','warn')
        if q.get('updated'):body+=app.notice('Creative brief updated. Rebuild placement assets to apply the new text/background/style.','success')
        if q.get('created'):body+=app.notice('Creative campaign created. Generate an AI master if you want model/mannequin/lifestyle photography, then approve it before building placement assets.','success')
        if q.get('master'):body+=app.notice('AI campaign master generated. Review its fidelity result before approval.','success')
        if q.get('master_pack'):
            errs=q.get('master_errors',['0'])[0];body+=app.notice(f"Generated {q['master_pack'][0]} AI master(s); {errs} job(s) could not complete. Review fidelity before approval.",'success' if errs=='0' else 'warn')
        if q.get('review'):body+=app.notice('AI master review saved.','success')
        if q.get('images'):body+=app.notice(f"Prepared {q['images'][0]} placement image(s) and {q.get('details',['0'])[0]} detail asset(s).",'success')
        if q.get('video_jobs'):body+=app.notice(f"Created {q['video_jobs'][0]} video job(s); {q.get('video_done',['0'])[0]} processed now.",'success')
        if q.get('handoffs'):body+=app.notice(q['handoffs'][0]+' approved asset handoff(s) prepared. Nothing was published.','success')
        if q.get('video_one'):body+=app.notice('Video job processed.','success')
        if q.get('asset_review'):body+=app.notice('Asset review updated.','success')
        if q.get('regenerated'):body+=app.notice('A new version was created; the previous version remains in history.','success')
        br=cs.brief_readiness(cid)
        if br['issues']:
            body+=app.notice('Campaign handoff is blocked until product truth is verified: '+'; '.join(br['issues'][:3]),'warn')
        elif br['warnings']:
            body+=app.notice('Creative can proceed, but review these copy details before launch: '+'; '.join(br['warnings'][:3]),'warn')
        else:
            body+=app.notice('Creative brief and product-truth gate are ready.','success')
        body+=f'''<div class="card section"><div class="eyebrow">Creative brief</div><div class="stats-grid"><div><strong>Style</strong><div class="helper">{app.e(c['visual_style'])}</div></div><div><strong>Presentation</strong><div class="helper">{app.e(c['subject_mode'])}</div></div><div><strong>Message</strong><div class="helper">{app.e(c['promotional_message'] or 'Product-led')}</div></div><div><strong>CTA</strong><div class="helper">{app.e(c['cta'])}</div></div></div><p class="helper section">Google image assets are intentionally generated without text or logos. Social and uploaded display creatives use placement-aware safe zones rather than merely resizing one artwork.</p></div>'''
        body+='<div class="card section"><details><summary><strong>Edit creative brief</strong></summary><form method="post" action="/creative-studio/campaigns/'+app.e(cid)+'/update" class="section">'+app.field('Campaign type','<select name="campaign_type">'+app.options(cs.CAMPAIGN_TYPES,c['campaign_type'])+'</select>')+app.field('Target market','<input name="target_market" value="'+app.e(c['target_market'])+'">')+app.field('Language','<input name="language" value="'+app.e(c['language'])+'">')+app.field('Visual style','<select name="visual_style">'+app.options(cs.VISUAL_STYLES,c['visual_style'])+'</select>')+app.field('Background','<select name="background_style">'+app.options(cs.BACKGROUND_STYLES,c['background_style'])+'</select>')+app.field('Presentation','<select name="subject_mode">'+app.options(cs.SUBJECT_MODES,c['subject_mode'])+'</select>')+app.field('Model style','<select name="model_style">'+app.options(cs.MODEL_STYLES,c['model_style'])+'</select>')+app.field('Promotional message','<input name="promotional_message" value="'+app.e(c['promotional_message'])+'">')+app.field('CTA','<input name="cta" value="'+app.e(c['cta'])+'">')+app.field('Price text','<input name="price_text" value="'+app.e(c['price_text'])+'">')+app.field('Offer','<input name="offer_text" value="'+app.e(c['offer_text'])+'">')+'<button class="btn secondary">Save brief</button></form></details></div>'
        body+='<div class="two section"><div class="card"><div class="eyebrow">Placement plan</div><h2>Selected formats</h2>'
        for pl in placements:
            spec=cs.placement_spec(cid,pl['placement_key']);custom=m.one('SELECT media_type FROM v8_custom_placements WHERE campaign_id=? AND placement_key=?',(cid,pl['placement_key']));is_video=(pl['placement_key'] in cs.VIDEO_PLACEMENTS) or bool(custom and custom['media_type']=='video')
            body+=f'<div class="readiness-row"><span class="pill {"purple" if is_video else "good"}">{"VIDEO" if is_video else "IMAGE"}</span><div class="row-main"><strong>{app.e(spec["label"])}</strong><small>{app.e(spec["ratio"])} · {spec["size"][0]}×{spec["size"][1]}{(" · "+str(pl["variations"])+" variation(s)") if not is_video else ""}</small></div></div>'
        body+='</div><div class="card"><div class="eyebrow">Batch actions</div><h2>Generate the campaign pack</h2>'
        body+='<form method="post" action="/creative-studio/campaigns/'+app.e(cid)+'/master-pack"><strong>1. Optional AI photography masters</strong><p class="helper">Creates paid reference-image edits for every selected product. Each result is fidelity-checked and still needs approval before downstream assets use it.</p>'
        for key,spec in cs.MASTER_KINDS.items():body+=f'<label class="checkline"><input type="checkbox" name="master_kind" value="{app.e(key)}" {"checked" if key in {"product","mannequin","model"} else ""}> {app.e(spec["label"])} <span class="tiny muted">{app.e(spec["description"])}</span></label>'
        body+=app.field('Variations per master type','<select name="master_variations">'+app.options(['1','2'],'1')+'</select>','Start with one. Additional AI variations increase API usage.')
        if cs.ai_image_ready():body+='<button class="btn secondary section" style="width:100%">Generate selected AI masters for all products</button>'
        else:body+='<button class="btn secondary section" style="width:100%" disabled>AI imagery unavailable — connect OpenAI first</button><p class="helper">OpenAI has not passed connection readiness. <a href="/settings">Open Settings</a> to connect it; original photography can still be used for deterministic placements.</p>'
        body+='</form><div class="divider"></div>'
        body+='<form method="post" action="/creative-studio/campaigns/'+app.e(cid)+'/images"><strong>2. Placement images + safe product details</strong><button class="btn section" style="width:100%">Generate all image placements + detail packs</button></form><p class="helper">Approved AI masters are selected by placement: clean product masters for product-first Google assets and model/lifestyle masters for social/performance placements. If none is approved, original photography is used.</p><div class="divider"></div><form method="post" action="/creative-studio/campaigns/'+app.e(cid)+'/videos"><strong>3. Video placements</strong>'
        body+=app.field('Video engine','<select name="provider">'+app.options([('local','Local motion edit — no generative video cost'),('veo','Google Veo 3.1 — reference-image AI motion')],cs.setting('v8_video_provider','local'))+'</select>')
        body+=app.field('Duration','<select name="duration">'+app.options([(str(x),str(x)+' seconds') for x in cs.DURATIONS],'15')+'</select>')
        body+=app.field('Custom duration (optional)','<input type="number" name="custom_duration" min="4" max="60" placeholder="4–60 seconds">','Overrides the preset duration when filled.')
        body+=app.field('Video style','<select name="video_style">'+app.options(cs.VIDEO_STYLES,'Product showcase')+'</select>')
        body+=app.field('Transitions','<select name="transition_style">'+app.options(['Fade','Slow zoom','Clean cuts'],'Fade')+'</select>')
        body+=app.field('Captions / subtitles','<select name="captions_mode">'+app.options([('off','Off'),('on','Show voice-over text as captions')],'off')+'</select>')
        body+=app.field('Logo in video','<select name="video_logo_mode">'+app.options(['Use logo','No logo'],c['logo_mode'])+'</select>')
        mus=[('', 'No music')]+[(x['id'],x['label']) for x in cs.music_assets()];body+=app.field('Music','<select name="music_id">'+app.options(mus,'')+'</select>')
        body+=app.field('Voice-over','<select name="voiceover_mode">'+app.options([('none','No voice-over'),('ai','AI voice-over (OpenAI TTS)')],'none')+'</select>')
        body+=app.field('Voice-over script','<textarea name="voiceover_text" rows="3" placeholder="Discover our latest collection..."></textarea>','AI-generated voices must be disclosed to end users. Only use music you have commercial rights to.')
        if cs.video_secret():body+='<label class="checkline"><input type="checkbox" name="paid_run" value="1"> If Veo is selected, run the paid AI video jobs now</label>'
        else:body+='<p class="helper">Veo can be selected to queue jobs, but a Gemini key must be added on the Creative Studio home page before paid generation.</p>'
        body+='<button class="btn secondary section" style="width:100%">Create / render video placements</button></form></div></div>'
        # Product masters
        body+='<div class="section-head"><h2>Product masters</h2><span class="tiny muted">Generate once, fidelity-check, then reuse across placements</span></div>'
        for p in products:
            masters=[a for a in assets if a['product_id']==p['product_id'] and a['placement_key'].startswith('MASTER')]
            master_button = '<button class="btn">Generate AI master</button>' if cs.ai_image_ready() else '<button class="btn" disabled>Connect OpenAI to generate</button><p class="helper"><a href="/settings">Open AI settings</a></p>'
            body+=f'<div class="card section"><div class="message-top"><div><span class="pill purple">{app.e(p["product_code"] or p["internal_sku"])}</span><h3>{app.e(p["public_product_name"])}</h3></div><a class="btn secondary small" href="/creative/products/{app.e(p["product_id"])}">Original creative workspace</a></div><div class="two section"><div><img style="width:100%;max-height:560px;object-fit:contain;background:#f5f3f6;border-radius:14px" src="/{app.e(p.get("img") or "")}" alt="Original product"><p class="tiny muted">Original source image</p></div><div><h3>AI model / mannequin / studio master</h3><p class="helper">Uses up to five original reference images and your selected style/background. The garment is never considered approved until the fidelity check passes and you approve it.</p><form method="post" action="/creative-studio/campaigns/{app.e(cid)}/master"><input type="hidden" name="product_id" value="{app.e(p["product_id"])}"><label class="field">Master type<select name="master_kind">{app.options([(k,v["label"]) for k,v in cs.MASTER_KINDS.items()],"model")}</select></label><label class="field">Variation<select name="variation">{app.options(["1","2","3","4"],"1")}</select></label>{master_button}</form></div></div>'
            for a in masters:
                v7=m.one('SELECT * FROM v7_creative_assets WHERE id=?',(a['source_asset_id'],)) if a['source_asset_id'] else None
                body+=f'<div class="two section"><div><img style="width:100%;max-height:620px;object-fit:contain;border-radius:14px" src="/{app.e(a["relative_path"])}"><p class="tiny muted">{app.e(a["placement_key"].replace("MASTER_","").replace("_"," " ).title())} · Version {a["version_no"]} · {app.e(a["status"])}</p></div><div><h3>Product-fidelity gate</h3>'
                if v7:
                    body+=f'<p><strong>{"Not checked" if v7["fidelity_score"] is None else str(round(float(v7["fidelity_score"])))+"/100"}</strong></p>'
                    if v7.get('fidelity_json'):
                        try:
                            fd=json.loads(v7['fidelity_json']);body+=f'<p>{app.e(fd.get("summary",""))}</p>'
                            for issue in fd.get('issues',[]):body+=f'<div class="readiness-row"><span class="pill warn">CHECK</span><div class="row-main"><small>{app.e(issue)}</small></div></div>'
                        except Exception:pass
                    if v7['fidelity_score'] is not None:
                        body+=f'''<div class="toolbar section"><form method="post" action="/creative-studio/campaigns/{app.e(cid)}/master-review"><input type="hidden" name="source_asset_id" value="{app.e(a['source_asset_id'])}"><input type="hidden" name="decision" value="approve"><button class="btn">Approve master</button></form><form method="post" action="/creative-studio/campaigns/{app.e(cid)}/master-review"><input type="hidden" name="source_asset_id" value="{app.e(a['source_asset_id'])}"><input type="hidden" name="decision" value="reject"><button class="btn secondary">Reject</button></form></div>'''
                body+='<p class="helper">Check colour, pattern, embroidery/print, border, pallu, blouse and texture against the originals. Automated fidelity scoring is a guardrail, not proof.</p></div></div>'
            body+='</div>'
        # Asset library grouped by product/platform
        body+='<div class="section-head"><h2>Asset library</h2><span class="tiny muted">Product → campaign → platform → format · previous versions are retained</span></div>'
        platform_filter=(q.get('platform') or [''])[0];status_filter=(q.get('status') or [''])[0];source_filter=(q.get('source') or [''])[0]
        platforms=sorted({(cs.placement_spec(cid,a['placement_key']) or {}).get('platform','Custom') for a in assets if not a['placement_key'].startswith('MASTER')})
        body+='<form method="get" class="toolbar section"><label class="field">Platform<select name="platform">'+app.options([('', 'All platforms')]+[(x,x) for x in platforms],platform_filter)+'</select></label><label class="field">Status<select name="status">'+app.options([('', 'All statuses'),('Needs review','Needs review'),('QC passed','QC passed'),('Approved','Approved'),('Rejected','Rejected')],status_filter)+'</select></label><label class="field">Source<select name="source">'+app.options([('', 'All sources'),('original','Original'),('ai','AI master / AI'),('local','Local placement')],source_filter)+'</select></label><button class="btn secondary small">Filter</button></form>'
        nonmasters=[a for a in assets if not a['placement_key'].startswith('MASTER') and a['status']!='Archived']
        if platform_filter:nonmasters=[a for a in nonmasters if (cs.placement_spec(cid,a['placement_key']) or {}).get('platform','Custom')==platform_filter]
        if status_filter:nonmasters=[a for a in nonmasters if a['status']==status_filter]
        if source_filter=='original':nonmasters=[a for a in nonmasters if 'Original' in (a.get('source_kind') or '')]
        elif source_filter=='ai':nonmasters=[a for a in nonmasters if 'AI' in (a.get('source_kind') or '') or a.get('source_asset_id')]
        elif source_filter=='local':nonmasters=[a for a in nonmasters if 'Placement-aware' in (a.get('notes') or '') or 'Local' in (a.get('source_kind') or '')]
        if not nonmasters:body+='<div class="card empty">Generate image or video placements above. Assets will appear here with preview, review, regeneration and direct download.</div>'
        by_product={}
        for a in nonmasters:by_product.setdefault(a['product_id'],[]).append(a)
        for pid,alist in by_product.items():
            p=next((x for x in products if x['product_id']==pid),None);body+=f'<div class="card section"><h3>{app.e(p["public_product_name"] if p else pid)}</h3><div class="product-grid">'
            for a in alist:
                spec=cs.placement_spec(cid,a['placement_key']);label=spec['label'] if spec else a['placement_key']
                if a['media_type']=='video' and a['relative_path'].endswith('.mp4'):
                    media=f'<video controls style="width:100%;max-height:430px;background:#111"><source src="/{app.e(a["relative_path"])}" type="video/mp4"></video>'
                elif a['media_type']=='video':media='<div class="empty" style="min-height:180px">Storyboard / manifest ready</div>'
                else:media=f'<img src="/{app.e(a["relative_path"])}" alt="{app.e(label)}">'
                qc=cs.quality_for(a['id'])
                qlabel=qc.get('qc_status') or 'Not checked';qscore='' if qc.get('score') is None else f" · {float(qc['score']):.0f}/100"
                body+=f'''<article class="product">{media}<div class="pbody"><span class="tiny muted">{app.e(label)} · v{a['version_no']} · variation {a['variation']}</span><h3>{app.e(a['status'])}</h3><p>{app.e(a['source_kind'] or '')}</p><p class="tiny"><strong>QC:</strong> {app.e(qlabel+qscore)}</p>'''
                for issue in (qc.get('issues') or [])[:2]:body+=f'<p class="tiny" style="color:#9b2c2c">{app.e(issue)}</p>'
                body+='<div class="toolbar"><a class="btn secondary small" href="/'+app.e(a['relative_path'])+'" download>Download</a>'
                if a['media_type']=='image' and cs.placement_spec(cid,a['placement_key']):body+=f'<form method="post" action="/creative-studio/campaigns/{app.e(cid)}/asset-regenerate"><input type="hidden" name="asset_id" value="{app.e(a["id"])}"><button class="btn secondary small">New variation</button></form>'
                if a['status']!='Approved':body+=f'''<form method="post" action="/creative-studio/campaigns/{app.e(cid)}/asset-review"><input type="hidden" name="asset_id" value="{app.e(a['id'])}"><input type="hidden" name="decision" value="Approved"><button class="btn secondary small">Approve</button></form>'''
                else:body+='<span class="pill good">APPROVED</span>'
                if a['status']!='Rejected':body+=f'''<form method="post" action="/creative-studio/campaigns/{app.e(cid)}/asset-review"><input type="hidden" name="asset_id" value="{app.e(a['id'])}"><input type="hidden" name="decision" value="Rejected"><button class="btn secondary small">Reject</button></form>'''
                body+='</div></div></article>'
            body+='</div></div>'
        # Jobs and campaign handoff
        queued=[j for j in jobs if j['status']=='Queued']
        if queued:
            body+='<div class="card section"><h2>Queued AI video jobs</h2><p class="helper">Reference-image Veo jobs are 8-second AI motion segments; longer requested ads can be completed with the local compositor. Paid jobs stay queued until you explicitly run them.</p>'
            for j in queued:
                spec=cs.placement_spec(cid,j['placement_key']);body+=f'''<div class="readiness-row"><span class="pill warn">QUEUED</span><div class="row-main"><strong>{app.e(spec['label'])}</strong><small>{app.e(j['provider'])} · {j['duration_seconds']} sec</small></div><form method="post" action="/creative-studio/campaigns/{app.e(cid)}/video-job"><input type="hidden" name="job_id" value="{app.e(j['id'])}"><button class="btn secondary small">Run now</button></form></div>'''
            body+='</div>'
        handoffs=cs.publish_handoffs(cid)
        body+='<div class="card section"><div class="eyebrow">Publishing handoff</div><h2>Approved creative → channel handoffs</h2><p class="helper">At automation level 2 or higher, V22 prepares handoffs automatically after the last required creative decision. Provider publication still requires a real connected channel and provider confirmation.</p><form method="post" action="/creative-studio/campaigns/'+app.e(cid)+'/publish-prepare"><button class="btn secondary">Refresh approved handoffs</button></form>'
        if handoffs:
            body+='<div class="table-wrap section"><table><tr><th>Platform</th><th>Product</th><th>Format</th><th>Status</th></tr>'
            for h in handoffs[:80]:body+=f'<tr><td>{app.e(h["platform"])}</td><td>{app.e(h["product_id"])}</td><td>{app.e(h["placement_key"])}</td><td>{app.e(h["status"])}</td></tr>'
            body+='</table></div>'
        body+='</div>'
        link=m.one('SELECT * FROM v19_creative_campaign_links WHERE creative_campaign_id=?',(cid,))
        body+='<div class="card section"><div class="eyebrow">Next step</div><h2>Creative → business campaign</h2><p class="helper">Create one business-goal campaign from the approved creative pack. This prepares audiences, channel readiness and approval work; it never activates paid spend automatically.</p><div class="toolbar">'
        if link and link.get('unified_campaign_id'):body+=app.button('Open linked campaign','/campaign-builder/'+link['unified_campaign_id'],'secondary')
        else:body+='<form method="post" action="/creative-studio/campaigns/'+app.e(cid)+'/business-plan"><button class="btn">Create connected business campaign plan</button></form>'
        body+=app.button('Plan B2B campaign','/campaigns/new?audience=B2B&goal=Catalogue%20discovery','secondary')+'</div></div>'
        self.send_html(app.layout('Creative campaign',body,'creative_studio'))
