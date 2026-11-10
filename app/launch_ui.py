"""Small-business product launch: upload, prepare, review; social follows approval."""
from __future__ import annotations
import html
import json
import re
from urllib.parse import urlencode
import launch_studio as ls
import launch_publish as publish
import marketing as m
import runtime_config as rc

e=lambda value:html.escape(str(value if value is not None else ''),quote=True)


def input_(name,value='',label='',type_='text',hint='',attrs=''):
    return f'<label class="lp-field">{e(label)}<input type="{type_}" name="{e(name)}" value="{e(value)}" {attrs}><small>{e(hint)}</small></label>'


def area(name,value,label,rows=4):
    return f'<label class="lp-field">{e(label)}<textarea name="{e(name)}" rows="{rows}">{e(value)}</textarea></label>'


def select(name,items,value='',label=''):
    opts=''.join(f'<option value="{e(k)}" {"selected" if str(k)==str(value) else ""}>{e(v)}</option>' for k,v in items)
    return f'<label class="lp-field">{e(label)}<select name="{e(name)}">{opts}</select></label>'


def hidden(name,value):return f'<input type="hidden" name="{e(name)}" value="{e(value)}">'


def form(d,action,body,label,step='details',extra=''):
    return f'<form method="post" action="/launch/{action}" {extra}>'+hidden('id',d['id'])+hidden('revision',d['revision'])+hidden('step',step)+body+f'<button class="lp-button" type="submit">{e(label)}</button></form>'


def note(text):return f'<div class="lp-note">{e(text)}</div>'


def heading(kicker,title,copy=''):
    return f'<div class="lp-heading"><span class="lp-kicker">{e(kicker)}</span><h1>{e(title)}</h1><p>{e(copy)}</p></div>'


def shell(body):
    return '<link rel="stylesheet" href="/ui/launch.css"><script defer src="/ui/launch.js"></script><div class="lp">'+body+'</div>'


class LaunchPages:
    def launch_get(self,path,q):
        if not (path=='/launch' or path.startswith('/launch/')):return False
        from app import layout
        try:
            if path=='/launch':body=self.launch_home()
            elif path=='/launch/ai':body=self.launch_ai_setup(q)
            elif path=='/launch/store':
                return self.json_response(publish.resources(q.get('connection_id',[''])[0])) or True
            elif re.fullmatch(r'/launch/[a-f0-9]{32}/status',path):
                did=path.split('/')[2];d=ls.get(did)
                job=m.one('SELECT status,message FROM launch_jobs WHERE draft_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(did,))
                return self.json_response({'revision':d['revision'],'busy':bool(ls.busy(did)),'job':job}) or True
            elif re.fullmatch(r'/launch/[a-f0-9]{32}/kit',path):
                d=ls.get(path.split('/')[2]);self.send_file(ls.export_kit(d),ls.slug(d['title'])+'-launch-kit.zip','application/zip');return True
            elif re.fullmatch(r'/launch/[a-f0-9]{32}',path):body=self.launch_detail(ls.get(path.split('/')[2]),q)
            else:self.send_error(404);return True
            message=q.get('message',[''])[0]
            self.send_html(layout('Launch a product',shell((note(message) if message else '')+body),'launch'));return True
        except ValueError as exc:
            self.send_html(layout('Launch a product',shell(note(str(exc))+'<a href="/launch">Back to product launches</a>'),'launch'),400);return True

    def launch_home(self):
        body=heading('FROM PHONE PHOTO TO SHOP FRONT','Your next product starts here.','A few photos. A little about your product. We’ll help with the rest.')
        connected=bool(m.secret())
        if not connected:body+='<div class="lp-note"><b>Connect AI to enable the automation.</b> Without it, uploads are saved and resized locally. <a href="/launch/ai">Set up AI →</a></div>'
        body+='<div class="lp-start"><section class="lp-card"><h2>What are you selling?</h2><form action="/launch/upload" method="post" enctype="multipart/form-data">'
        body+='<label class="lp-drop"><span class="lp-upload-icon">↥</span><strong>Add your product photos</strong><span>Choose or drop photos here. Include each colour you sell.</span><input required type="file" name="product_images" multiple accept="image/jpeg,image/png,image/webp,image/heic,image/heif"><small>JPG, PNG, WebP or HEIC · up to 20 photos · 20 MB each · 80 MB total</small></label><div class="lp-upload-preview" aria-live="polite"></div>'
        body+=input_('title','','Product name (optional)',hint='A simple name is enough. AI can suggest one.')+area('facts','','Tell us a little (optional)',3)
        body+=select('shoot',[('product','Just the product'),('mannequin','Product + mannequin shoot'),('model','Product + AI model shoot')],'product','What kind of photos would you like?')
        if connected:body+='<small>Generates copy and the chosen photo shoot using your AI account. API usage is charged by your provider. Review the results before publishing.</small>'
        body+='<button class="lp-button" type="submit">'+('Generate product preview' if connected else 'Save product draft')+' <span>→</span></button></form></section>'
        body+='<aside class="lp-aside"><span class="lp-kicker">MADE FOR EVERYDAY PHOTOS</span><h2>Your phone camera is enough to start.</h2><ol><li><b>Upload</b><p>Use a clear front photo, a close-up, and any other angles you have.</p></li><li><b>Make it yours</b><p>Review the copy and photos. Confirm colours, sizes, stock and price.</p></li><li><b>Review & launch</b><p>Approve your listing, send it to your store, then create your social posts.</p></li></ol><p class="lp-muted">Use natural light and a plain background. Real photos of every colour help keep the listing accurate.</p></aside></div>'
        if not m.secret():body+=note('AI is not connected yet. You can upload photos, optimise them and build listings manually. Connect AI in Settings for writing, studio photos and market research.')
        b=ls.brand()
        body+='<details class="lp-card"><summary>Your brand preferences · set once</summary><form action="/launch/brand" method="post"><div class="lp-two">'
        for key,label in [('voice','Writing style'),('audience','Who you sell to'),('style','Photo style'),('market','Main selling market')]:body+=input_(key,b[key],label)
        body+='</div>'+area('avoid',b['avoid'],'Words or claims to avoid',2)+'<button class="lp-button" type="submit">Save brand preferences</button><small>Applied to new launches. Existing drafts keep their brand snapshot.</small></form></details>'
        drafts=ls.drafts()
        if drafts:
            body+='<div class="lp-section-head"><h2>Your product launches</h2><span>Pick up where you left off</span></div><div class="lp-drafts">'
            for d in drafts:
                cover=next((x for x in d['images'] if x['id']==d['cover_id']),d['images'][0])
                body+=f'<a class="lp-draft" href="/launch/{d["id"]}"><img src="/{e(cover["selected"])}" alt="{e(cover["alt"])}"><div><span class="lp-pill">{e(d["status"])}</span><h3>{e(d["title"])}</h3><small>{len([v for v in d["variants"] if v["enabled"]])} combination(s) · {len(d["images"])} photos</small></div><span>→</span></a>'
            body+='</div>'
        return body

    def launch_ai_setup(self,q):
        did=q.get('id',[''])[0]
        back='/launch/'+did if re.fullmatch('[a-f0-9]{32}',did) else '/launch'
        body=heading('POWER YOUR PRODUCT AUTOMATION','Connect AI once.','Use your OpenAI API account for titles, descriptions, studio photography and model shoots. You can choose your website later.')
        body+='<div class="lp-start"><section class="lp-card"><h2>Connect your API account</h2><p>Get an API key from <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">OpenAI’s API dashboard</a>. Sign in, choose a project, and create a key for this software. Complete any API billing or account verification requested there.</p>'
        body+='<form method="post" action="/launch/ai-connect">'+hidden('id',did)
        body+=input_('api_key','','OpenAI API key','password',hint='Enter the key here, not in chat. It is saved privately on this machine and is never displayed.',attrs='autocomplete="new-password"')
        body+='<small>'+('A key is already configured. Leave the field empty to test it.' if m.secret() else 'No API key is connected yet.')+'</small><button type="submit" class="lp-button">Save & check connection</button></form></section>'
        body+='<aside class="lp-aside"><h2>What happens next</h2><ol><li>Create your key in your own OpenAI account.</li><li>Enter it in this form and check the connection.</li><li>Return to your product and choose <b>Generate with AI</b>.</li></ol><p>The app writes the listing, creates studio edits, then runs your chosen mannequin or AI-model shoot. Each completed result appears in the preview.</p><p>Checking this connection verifies model access. Generating content uses API credits; the first generation also checks that usage is available.</p></aside></div>'
        try:result=json.loads(m.settings().get('launch_ai_connection_check') or '{}')
        except ValueError:result={}
        for check in result.get('checks',[]):
            body+=note(check['label']+': '+('Model access verified. ' if check['ready'] else 'Needs attention. ')+check['detail'])
        body+=f'<a class="lp-button" href="{e(back)}">Return to product →</a>'
        return body

    def launch_progress_preview(self,d):
        body='<section class="lp-card"><h2>Preview as results arrive</h2><small>'+e(d['content_engine'])+'</small><h3>'+e(d['title'])+'</h3><p class="lp-description">'+e(d['description'])+'</p><div class="lp-photo-grid">'
        for im in d['images']:
            body+='<article class="lp-photo"><div class="lp-comparison">'
            versions=[{'path':im['source'],'kind':'Original'}]+[v for v in im['variants'] if v.get('generated')]
            for version in versions:
                body+=f'<figure><img src="/{e(version["path"])}" alt="{e(version["kind"])}"><figcaption>{e(version["kind"])}</figcaption></figure>'
            body+='</div></article>'
        return body+'</div></section>'

    def launch_detail(self,d,q):
        step=q.get('step',['details'])[0]
        if step not in {'details','photos','review','social'}:step='details'
        body='<a class="lp-back" href="/launch">← All product launches</a>'+heading('YOUR PRODUCT LAUNCH',d['title'],'Everything stays together as one product, including its colours and sizes.')
        body+='<nav class="lp-steps" aria-label="Product launch steps">'
        for key,label in [('details','1 · Product details'),('photos','2 · Photos'),('review','3 · Review & launch'),('social','Social posts')]:
            body+=f'<a class="{"current" if step==key else ""}" href="/launch/{d["id"]}?step={key}">{label}</a>'
        body+='</nav>'
        if d.get('product_id'):
            body+=f'<p class="lp-save-state">Saved in Products · <a href="/products/{e(d["product_id"])}">View product record →</a></p>'
        if not m.secret():
            body+=f'<div class="lp-note">AI is not connected. Photo resizing and saving work; AI writing and shoots need <a href="/launch/ai?id={d["id"]}">an API connection</a>.</div>'
        if step=='review' and not publish.stores():
            body+='<div class="lp-note">Website not connected. Your product is saved inside this software. <a href="/integrations">Connect Shopify or Wix</a>, then approve and send the listing to put it on your website.</div>'
        busy=ls.busy(d['id'])
        if busy:
            body+=f'<div class="lp-note lp-working" role="status" data-launch-status="/launch/{d["id"]}/status" data-revision="{d["revision"]}"><span class="lp-spinner"></span><span data-job-message>{e(busy["message"] or "Your request is queued…")}</span></div>'
            # Do not offer editable forms while a job owns this draft.
            return body+self.launch_progress_preview(d)
        job=m.one("SELECT * FROM launch_jobs WHERE draft_id=? ORDER BY created_at DESC,id DESC LIMIT 1",(d['id'],))
        if job and job['status']=='Failed':body+=note('The last action could not finish: '+job['message'])
        if step in {'details','photos'}:
            body+='<section class="lp-card"><h2>Let AI prepare this product</h2><p>Write the title, description, SEO and alt text, then create studio photos and your chosen shoot. Existing details can be restored from Saved versions.</p>'
            if m.secret():
                body+=form(d,'generate',select('shoot',[('product','Studio photos only'),('mannequin','Studio + mannequin shoot'),('model','Studio + AI model shoot')],d['shoot'],'Photo shoot')+'<small>Uses your connected API account. You will review generated copy and images before publishing.</small>','Generate with AI','photos')
            else:body+=f'<a class="lp-button" href="/launch/ai?id={d["id"]}">Connect AI to start →</a>'
            body+='</section>'
        if step=='photos' and d['content_engine'].startswith('AI'):
            body+='<section class="lp-card"><span class="lp-kicker">AI COPY PREVIEW · REVIEW REQUIRED</span><h2>'+e(d['title'])+'</h2><p class="lp-description">'+e(d['description'])+'</p></section>'
        if step=='details':body+=self.launch_details_form(d)
        elif step=='photos':body+=self.launch_photos_form(d)
        elif step=='review':body+=self.launch_review(d)
        else:body+=self.launch_social(d)
        versions=m.rows('SELECT revision,reason,created_at FROM launch_versions WHERE draft_id=? ORDER BY revision DESC LIMIT 12',(d['id'],))
        body+='<details class="lp-history"><summary>Saved versions</summary>'
        body+=form(d,'restore',select('restore_revision',[(v['revision'],str(v['revision'])+' · '+v['reason']) for v in versions],label='Restore a previous draft'),'Restore draft',step)
        return body+'</details>'

    def launch_details_form(self,d):
        body='<div class="lp-editor"><section class="lp-card"><h2>Make the details yours</h2>'
        if d.get('suggestions',{}).get('questions'):body+=note('Please check: '+' · '.join(str(x) for x in d['suggestions']['questions']))
        if d.get('suggestions',{}).get('different_products'):body+=note('These photos may include different products. Keep only photos of this product before approval.')
        fields=input_('title',d['title'],'Product title',attrs='required maxlength="180"')+area('description',d['description'],'Description')
        fields+='<details><summary>Product facts & search appearance</summary>'+area('facts',d['facts'],'What you know about the product',3)+'<div class="lp-two">'+input_('material',d['material'],'Material (only if known)')+input_('category',d['category'],'Product type')+'</div>'
        fields+=input_('seo_title',d['seo_title'],'Search title',attrs='maxlength="70"')+area('meta_description',d['meta_description'],'Search description',2)+input_('tags',', '.join(d['tags']),'Search tags, separated by commas')+'</details>'
        fields+='<div class="lp-two">'+input_('price',d['price'],'Selling price',type_='number',attrs='min="0" step="0.01"')+input_('currency',d['currency'],'Currency',attrs='maxlength="3" pattern="[A-Z]{3}" required')+'</div>'+input_('market',d['market'],'Where do you sell?',hint='For example: India · online retail')
        fields+='<details><summary>Costs & target margin (optional)</summary><div class="lp-two">'+input_('cost',d['cost'],'Product cost',type_='number',attrs='min="0" step="0.01"')+input_('extra_cost',d['extra_cost'],'Packaging, fees & other costs',type_='number',attrs='min="0" step="0.01"')+'</div>'+input_('margin',d['margin'],'Target gross margin (%)',type_='number',attrs='min="0" max="94"')+'<small>Include taxes, shipping and fees relevant to your business. Suggestions are not a guarantee of profit.</small></details>'
        body+=form(d,'edit',fields,'Save product details')+'</section><aside class="lp-card lp-price"><span class="lp-kicker">A LITTLE HELP WITH PRICING</span><h2>Find your price</h2><p>Compare similar products in your market, then choose the price that works for you.</p>'
        price=ls.pricing(d)
        if price['suggested']:
            body+=f'<div class="lp-price-number">{e(d["currency"])} {e(price["suggested"])}</div><p>Suggested from {price["count"]} comparable listings and your cost floor.</p>'
            body+=form(d,'use-price','','Use suggested price')
        elif d['research']:body+=note('Refresh research after changing product facts, or after 7 days. At least three matching listings are needed.' if price['stale'] else 'Not enough comparable listings to suggest a reliable market price.')
        if price['floor']:body+=f'<p>Cost-based floor: <b>{e(d["currency"])} {e(price["floor"])}</b></p>'
        body+=form(d,'research','','Check market prices')
        if d['research']:
            body+='<p class="lp-muted">Checked '+e(d['research'].get('checked_at','')[:16].replace('T',' '))+' UTC</p><details><summary>See comparable products</summary>'
            for i,x in enumerate(d['research'].get('comparables',[])):
                body+=f'<div class="lp-comparable"><a href="{e(x["url"])}" target="_blank" rel="noopener noreferrer">{e(x["title"])}</a><b>{e(x["currency"])} {e(x["price"])}</b><small>{e(x["reason"])} {e(x["price_context"])}</small>'
                body+=form(d,'exclude',hidden('index',i),('Include comparison' if x['excluded'] else 'Exclude comparison'))+'</div>'
            body+='</details>'+note(d['research'].get('notes',''))
        body+='</aside></div>'
        colours=next((o['values'] for o in d['options'] if o['name']=='Colour'),[]);sizes=next((o['values'] for o in d['options'] if o['name']=='Size'),[])
        custom=next((o for o in d['options'] if o['name'] not in {'Colour','Size'}),{'name':'','values':[]})
        body+='<section class="lp-card"><h2>Does it come in different colours or sizes?</h2><p>Leave these empty for a single option. We’ll keep all combinations under this product.</p>'
        fields='<div class="lp-two">'+input_('colours',', '.join(colours),'Colours',hint='Separate with commas, e.g. Blue, Cream')+input_('sizes',', '.join(sizes),'Sizes',hint='Separate with commas, e.g. S, M, L')+'</div><details><summary>Another option, such as capacity or finish</summary><div class="lp-two">'+input_('option_name',custom['name'],'Option name')+input_('option_values',', '.join(custom['values']),'Choices, separated by commas')+'</div></details>'
        suggestions=d.get('suggestions',{}).get('suggested_colours') or d.get('suggestions',{}).get('suggested_colors')
        if suggestions:fields+=note('Possible colours from your photos: '+', '.join(str(x) for x in suggestions)+'. Confirm the real colour names before using them.')
        body+=form(d,'edit',fields,'Create / update combinations')
        fields=hidden('variants_form','1')+'<div class="lp-table-wrap"><table><thead><tr><th>Sell this</th><th>Combination</th><th>Stock</th><th>Price override</th><th>SKU</th></tr></thead><tbody>'
        for v in d['variants']:
            fields+=f'<tr><td><input type="checkbox" name="enabled_{v["id"]}" value="1" {"checked" if v["enabled"] else ""} aria-label="Sell {e(" / ".join(v["choices"].values()) or "Standard")}"></td><td>{e(" / ".join(v["choices"].values()) or "Standard")}</td><td><input name="stock_{v["id"]}" type="number" min="0" max="99999" value="{e(v["stock"])}" aria-label="Stock"></td><td><input name="price_{v["id"]}" type="number" min="0" step="0.01" value="{e(v["price"])}" placeholder="{e(d["price"] or "Base price")}" aria-label="Price override"></td><td><input name="sku_{v["id"]}" value="{e(v["sku"])}" maxlength="40" aria-label="SKU"></td></tr>'
        fields+='</tbody></table></div><small>Untick combinations you don’t sell. Use 0 for sold out. Blank prices use the main selling price. Photos are shared across sizes of the same colour.</small>'
        body+=form(d,'edit',fields,'Save stock & combinations')+'</section>'
        body+='<div class="lp-bottom">'+form(d,'prepare','','Suggest copy & optimise photos')+f'<a class="lp-button" href="/launch/{d["id"]}?step=photos">Next: review photos →</a></div>'
        return body

    def launch_photos_form(self,d):
        body='<section class="lp-card"><h2>Your photos, ready for the shop</h2><p>Compare every edit with your original. Check colour, shape, material and details before approval.</p>'
        colours=next((o['values'] for o in d['options'] if o['name']=='Colour'),[])
        fields=hidden('photos_form','1')+'<div class="lp-photo-grid">'
        for im in d['images']:
            iid=im['id'];fields+='<article class="lp-photo"><div class="lp-comparison">'
            fields+=f'<figure><img loading="lazy" src="/{e(im["source"])}" alt="Original phone photo"><figcaption>Original</figcaption></figure><figure><img loading="lazy" src="/{e(im["selected"])}" alt="{e(im["alt"])}"><figcaption>Selected for listing</figcaption></figure></div>'
            fields+=select('selected_'+iid,[(im['source'],'Original phone photo')]+[(v['path'],v['kind']) for v in im['variants']],im['selected'],'Photo version')
            if colours:fields+=select('colour_'+iid,[('','Choose colour')]+[(c,c) for c in colours],im['colour'],'This photo shows')
            fields+=area('alt_'+iid,im['alt'],'Image description (alt text)',2)
            for warning in im['warnings']:fields+='<small class="lp-warning">'+e(warning)+'</small>'
            fields+=f'<label class="lp-check"><input type="checkbox" name="approve_{iid}" value="1" {"checked" if im["approved"] else ""}>This photo and alt text accurately represent my product</label><label class="lp-check"><input type="radio" name="cover_id" value="{iid}" {"checked" if iid==d["cover_id"] else ""}>Use as the cover photo</label></article>'
        fields+='</div>'
        body+=form(d,'edit',fields,'Save & approve selected photos','photos')+'</section>'
        body+='<section class="lp-card"><h2>Try a professional shoot</h2><p>Studio editing improves the presentation. Model shoots create a new AI image, so review product fidelity carefully.</p>'
        count=len(d['images'])*(2 if d['shoot'] in {'model','mannequin'} else 1)
        body+=form(d,'photoshoot',note('Your chosen shoot: '+{'product':'product only','model':'AI model','mannequin':'mannequin'}[d['shoot']]+'. Up to '+str(count)+' image generations use your connected AI account. Studio edits are created first; completed edits are kept if interrupted.'),'Prepare all photos','photos')
        preferred={'product':'studio','mannequin':'mannequin','model':'model'}.get(d['shoot'],'studio')
        body+=form(d,'enhance','<div class="lp-two">'+select('image_id',[(im['id'],f'Photo {i+1} · '+(im['colour'] or im['filename'])) for i,im in enumerate(d['images'])],label='Choose photo')+select('kind',[('studio','Studio lighting & background'),('mannequin','Mannequin shoot'),('model','AI model shoot')],preferred,'Choose shoot')+'</div>','Create photo','photos')+'</section>'
        body+='<details class="lp-card"><summary>Add or remove photos</summary>'+form(d,'photos','<input type="file" required name="product_images" accept="image/*,.heic,.heif" multiple>','Add photos','photos',extra='enctype="multipart/form-data"')
        body+=form(d,'keep-both',select('image_id',[(im['id'],im['filename']) for im in d['images']],label='Keep an original alongside its selected edit'),'Keep both in the listing','photos')
        body+=form(d,'remove-photo',select('image_id',[(im['id'],im['filename']) for im in d['images']],label='Photo to remove'),'Remove photo from this draft','photos')+'</details>'
        return body+f'<div class="lp-bottom"><a href="/launch/{d["id"]}">← Product details</a><a class="lp-button" href="/launch/{d["id"]}?step=review">Next: review & launch →</a></div>'

    def launch_review(self,d):
        cover=next(x for x in d['images'] if x['id']==d['cover_id'])
        body='<div class="lp-editor"><section class="lp-card"><span class="lp-kicker">LISTING PREVIEW</span>'+f'<img class="lp-cover" src="/{e(cover["selected"])}" alt="{e(cover["alt"])}"><h2>{e(d["title"])}</h2><p class="lp-description">{e(d["description"])}</p>'
        for v in d['variants']:
            if v['enabled']:body+=f'<div class="lp-variant-summary"><span>{e(" / ".join(v["choices"].values()) or "Standard")}</span><b>{e(d["currency"])} {e(v["price"] or d["price"] or "Price needed")}</b><small>{e(v["stock"])} in stock</small></div>'
        body+='<details><summary>Search preview</summary><h3>'+e(d['seo_title'] or d['title'])+'</h3><p>'+e(d['meta_description'])+'</p></details></section><aside class="lp-card"><h2>Ready to launch?</h2>'
        issues=ls.blockers(d)
        if issues:body+='<ul class="lp-checklist">'+''.join('<li>'+e(x)+'</li>' for x in issues)+'</ul>'
        approved=d.get('approved_revision')==d['revision']
        if approved:body+=note('This version is approved. Editing the product will require approval again.')
        elif not issues:body+=form(d,'approve','<label class="lp-check"><input type="checkbox" required name="confirm" value="1">I have checked the product facts, photos, prices and stock.</label>','Approve this listing','review')
        if approved:
            body+=f'<a class="lp-button lp-secondary" href="/launch/{d["id"]}/kit">Download listing kit</a><p class="lp-muted">Optimised images, alt text, product data and a simple catalogue for other websites.</p>'
            stores=publish.stores()
            if stores:
                fields=select('connection_id',[('','Choose a store')]+[(c['id'],c['label']+' · '+c['connector_key']) for c in stores],label='Destination store')
                fields+='<button class="lp-button lp-secondary" type="button" data-store-load>Load store options</button><p data-store-note aria-live="polite"></p>'
                fields+='<div data-store-options>'+select('location_id',[('','Choose stock location')],label='Shopify stock location')+select('publication_id',[('','Choose sales channel')],label='Shopify sales channel')+'</div>'
                fields+=input_('store_currency','','For Wix: confirm your store currency',hint='Enter the currency shown in your Wix store settings, e.g. INR')
                fields+=select('visibility',[('draft','Save as a hidden store draft'),('live','Publish on the selected store / channel')],label='What should happen?')
                fields+='<label class="lp-check"><input required type="checkbox" name="confirm" value="1">Send this approved product, its photos, prices and stock to this destination.</label>'
                body+=form(d,'deliver',fields,'Send to store','review')
            else:body+='<p><a href="/integrations">Connect Shopify or Wix</a> to send your listing directly.</p>'
            if rc.TEAM_TEST_MODE and not rc.ALLOW_EXTERNAL_WRITES:body+=note('This workspace is in team test mode. Downloads work; sending to a live store is disabled by the workspace settings.')
            body+=f'<a class="lp-button" href="/launch/{d["id"]}?step=social">Create social posts →</a>'
        deliveries=m.rows('SELECT * FROM launch_deliveries WHERE draft_id=?',(d['id'],))
        for x in deliveries:
            r=json.loads(x['receipt']);body+=note(r.get('destination','Store')+' · '+x['status']+(' · '+x['error'] if x['error'] else ''))
        body+='</aside></div>'
        body+='<details class="lp-card"><summary>Add your live product link for captions & QR codes</summary>'+form(d,'edit',input_('product_url',d['product_url'],'Product website link',type_='url',hint='Changing the link requires product approval again.'),'Save product link','review')+'</details>'
        return body

    def launch_social(self,d):
        body='<section class="lp-card"><span class="lp-kicker">ONE PRODUCT, MORE PLACES</span><h2>Introduce it to your customers.</h2><p>Create feed, square and story images, with captions for Instagram, Facebook and WhatsApp. Only in-stock combinations are included.</p>'
        if d.get('approved_revision')!=d['revision']:return body+note('Approve the current listing in Review & launch first.')+'</section>'
        body+=form(d,'social','','Create social & WhatsApp kit','social')+'</section>'
        social=d.get('social',{})
        if not social:return body
        if social.get('basis')!=ls.fingerprint(d):return body+note('Your product changed. Create a fresh social kit so prices, photos and stock match.')
        body+='<div class="lp-social-assets">'
        for asset in social.get('assets',[]):body+=f'<figure><img src="/{e(asset["path"])}" alt="{e(asset["alt"])}"><figcaption>{e(asset["format"])}</figcaption></figure>'
        body+='</div><section class="lp-card"><h2>Make the captions yours</h2>'
        fields=''.join(area('caption_'+k,v,k,5) for k,v in social['captions'].items())
        fields+='<label class="lp-check"><input required type="checkbox" name="confirm" value="1">I have reviewed these captions and images for sharing.</label>'
        body+=form(d,'social-save',fields,'Approve social kit','social')
        if social.get('approved'):body+=f'<a class="lp-button lp-secondary" href="/launch/{d["id"]}/kit">Download ready-to-post kit</a><p>Includes platform images, captions and image descriptions. Upload these to your social accounts when you’re ready.</p>'
        return body+'</section>'

    def launch_post(self,path,f):
        if not path.startswith('/launch/'):return False
        raw={k:v[0] for k,v in f.items()};action=path.removeprefix('/launch/');did=raw.get('id','');step=raw.get('step','details')
        if step not in {'details','photos','review','social'}:step='details'
        try:
            if action=='ai-connect':
                try:
                    result=ls.check_ai_connection(raw.get('api_key',''))
                    message='Connection checked. '+str(sum(c['ready'] for c in result['checks']))+' of 3 capabilities have model access.'
                except ValueError as exc:message=str(exc)
                self.redirect('/launch/ai?'+urlencode({'id':did if re.fullmatch('[a-f0-9]{32}',did) else '','message':message}));return True
            elif action=='brand':ls.save_brand(raw);message='Brand preferences saved.'
            elif action=='upload':
                raw['_ai_actor']=str((getattr(self,'current_user',None) or {}).get('id') or 'local-owner')
                d=ls.create(raw,getattr(self,'_launch_images',[]));did=d['id']
                ls.enqueue(d,'generate' if m.secret() else 'prepare');message='Your product is being prepared.'
                if m.secret():step='photos'
            else:
                d=ls.get(did)
                if str(d['revision'])!=raw.get('revision'):raise ValueError('This draft changed. Refresh and review the latest version.')
                if ls.busy(did):raise ValueError('Wait for the current action to finish before making another change.')
                if action=='edit':ls.edit(d,raw);message='Saved.'
                elif action=='generate':
                    if not m.secret():raise ValueError('Connect AI first, then generate this product preview.')
                    if raw.get('shoot',d['shoot'])!=d['shoot']:d=ls.edit(d,{'shoot':raw['shoot']})
                    ls.enqueue(d,'generate');step='photos';message='AI generation started. Completed copy and photos will appear below.'
                elif action in {'prepare','research','enhance','photoshoot','social','deliver'}:
                    ls.enqueue(d,action,raw);message='Your request is queued.'
                elif action=='approve':
                    if raw.get('confirm')!='1':raise ValueError('Confirm that you reviewed this listing.')
                    ls.approve(d);message='Listing approved.'
                elif action=='photos':ls.add_images(d,getattr(self,'_launch_images',[]));ls.save(d,'More photos added');message='Photos added. Review their alt text and colour.'
                elif action=='keep-both':
                    import copy
                    if len(d['images'])>=ls.MAX_IMAGES:raise ValueError('Keep up to 20 listing photos.')
                    im=next((im for im in d['images'] if im['id']==raw.get('image_id')),None)
                    if not im or im['selected']==im['source']:raise ValueError('Choose an edited version of this photo first.')
                    if any(x['selected']==im['source'] for x in d['images']):raise ValueError('The original is already included in this listing.')
                    original=copy.deepcopy(im);original.update({'id':ls.uid(),'selected':im['source'],'approved':False,'variants':[],'kind':'Phone photo','alt':im.get('source_alt') or d['title']})
                    d['images'].append(original);ls.save(d,'Original added alongside edited photo');message='Original and edit are both included. Review their alt text and colour.'
                elif action=='remove-photo':
                    if len(d['images'])<=1:raise ValueError('Keep at least one photo.')
                    d['images']=[im for im in d['images'] if im['id']!=raw.get('image_id')]
                    if d['cover_id'] not in {im['id'] for im in d['images']}:d['cover_id']=d['images'][0]['id']
                    ls.save(d,'Photo removed from draft');message='Photo removed from this draft. Saved versions keep it.'
                elif action=='restore':ls.restore(d,int(raw['restore_revision']));message='Previous draft restored. Review before approving.'
                elif action=='exclude':
                    x=d['research']['comparables'][int(raw['index'])];x['excluded']=not x['excluded'];ls.save(d,'Market comparison selection changed');message='Price comparison updated.'
                elif action=='use-price':
                    price=ls.pricing(d)['suggested']
                    if not price:raise ValueError('Check current market prices before using a suggestion.')
                    ls.edit(d,{'price':price});message='Suggested price applied. Variant price overrides are unchanged.'
                elif action=='social-save':
                    ls.require_approved(d)
                    if d.get('social',{}).get('basis')!=ls.fingerprint(d):raise ValueError('Create a fresh social kit after changing the product.')
                    if raw.get('confirm')!='1':raise ValueError('Review the captions and images before approving.')
                    for k in d['social']['captions']:
                        value=raw.get('caption_'+k,'').strip()[:2200]
                        if not value:raise ValueError('Add a caption for each channel.')
                        d['social']['captions'][k]=value
                    d['social']['approved']=True;ls.save(d,'Social kit approved',invalidate=ls.preserve_approval(d));message='Social kit is ready to download.'
                else:raise ValueError('Unknown product launch action.')
        except (ValueError,KeyError,IndexError) as exc:message=str(exc) or 'Please check the form and try again.'
        dest='/launch/'+did if re.fullmatch('[a-f0-9]{32}',did) else '/launch'
        self.redirect(dest+'?'+urlencode({'step':step,'message':message}));return True
