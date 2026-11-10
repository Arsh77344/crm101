"""Reviewed, local outreach playbooks and personalisation settings."""
from __future__ import annotations
import hashlib
import json
import re
import ipaddress
import urllib.parse
import marketing as m
import contact_tools as ct

GOALS=['Catalogue discovery','Book a video consultation','Reorder conversation','New collection',
       'Wholesale enquiry','Sample request','Styling consultation','Festive collection','Customer feedback','Reconnect with customers']
PLAYBOOKS=[
 ('stockist','B2B','Meet your next stockist','Catalogue discovery','Introduce your collection and ask about the boutique\'s sourcing requirements.'),
 ('wholesale','B2B','Start a wholesale conversation','Wholesale enquiry','Discuss style, quantity and budget before preparing a quote. Never invent trade prices or MOQ.'),
 ('samples','B2B','Offer a closer product review','Sample request','Ask whether a detailed product review would help. Do not promise free samples.'),
 ('reorder','B2B','Explore a repeat order','Reorder conversation','For actual customers: ask whether they are planning another order. Do not claim knowledge of earlier purchases.'),
 ('discovery','B2C','Help someone discover a saree','Catalogue discovery','Invite a collection review and ask for preferences. Do not infer buying intent from a social follow.'),
 ('styling','B2C','Start a styling conversation','Styling consultation','Ask about colours and desired style. Use only preferences the customer has confirmed.'),
 ('new','B2C','Introduce a new collection','New collection','Introduce the selected collection without unverified scarcity or discount claims.'),
 ('festive','Both','Plan a seasonal collection','Festive collection','Let the customer choose their occasion; do not assume their religion, celebrations or marital status.'),
 ('video','Both','Invite a video consultation','Book a video consultation','Invite a closer product discussion; use a verified booking link only when configured.'),
 ('feedback','B2C','Ask an existing customer for feedback','Customer feedback','For actual customers: ask what would improve the experience, without inventing an order history.'),
 ('reconnect','Both','Reconnect with customers','Reconnect with customers','For actual customers: open a low-pressure conversation. Do not invent a date or previous discussion.')]
TOKENS={'greeting','brand','cta','first_name','full_name','company_name','role_title','product_name','collection','sender_name','signature'}
TONES=['Warm and professional','Elegant and understated','Friendly and conversational','Direct and practical']
SCHEMA='''
CREATE TABLE IF NOT EXISTS m41_campaign_options(campaign_id TEXT PRIMARY KEY, options_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS m41_templates(id TEXT PRIMARY KEY, name TEXT NOT NULL, audience TEXT, channel TEXT, messages_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
'''

def initialise():
    with m.connect() as con:con.executescript(SCHEMA)

def defaults(journey='B2B'):
    return {'greeting':'full','length':'Standard','use_preferences':'yes','sender_name':'','signature':'','cta_text':'',
            'cta_url':'','day1':4 if journey=='B2B' else 3,'day2':9 if journey=='B2B' else 7,'template_id':''}

def options(raw,journey='B2B'):
    result=defaults(journey)
    for key in result:
        if key in raw:result[key]=str(raw[key]).strip()
    if result['greeting'] not in {'full','first','company','neutral'}:raise ValueError('Choose a supported greeting style.')
    if result['length'] not in {'Concise','Standard'}:raise ValueError('Choose Concise or Standard message length.')
    if result['use_preferences'] not in {'yes','no'}:raise ValueError('Choose whether to use confirmed preferences.')
    for key in ['day1','day2']:
        try:result[key]=int(result[key])
        except (ValueError,TypeError):raise ValueError('Follow-up timing must be a whole number of days.')
    if not 0<result['day1']<result['day2']<=60:raise ValueError('Use increasing follow-up days between 1 and 60, such as 4 and 9.')
    for key,limit in [('sender_name',100),('signature',500),('cta_text',240),('cta_url',1000)]:
        if len(result[key])>limit:raise ValueError(f'{key.replace("_"," ").title()} is too long.')
        if '{{' in result[key] or '}}' in result[key]:raise ValueError('Use plain text, not merge fields, in sender/signature/CTA settings.')
    if result['cta_url'] and not safe_url(result['cta_url']):raise ValueError('Use a real public HTTPS destination, not a localhost, private IP or preview link.')
    if result['template_id'] and not m.one('SELECT id FROM m41_templates WHERE id=?',(result['template_id'],)):raise ValueError('The selected template no longer exists.')
    return result

def safe_url(url):
    try:
        p=urllib.parse.urlparse(url);host=(p.hostname or '').lower().rstrip('.')
        if p.scheme!='https' or not host or p.username or p.password or any(x.isspace() for x in url):return False
        if host in {'localhost','0.0.0.0','::1'} or host.endswith(('.localhost','.local')):return False
        try:return ipaddress.ip_address(host).is_global
        except ValueError:return '.' in host
    except ValueError:return False

def load(camid,journey='B2B'):
    r=m.one('SELECT options_json FROM m41_campaign_options WHERE campaign_id=?',(camid,))
    return {**defaults(journey),**(json.loads(r['options_json']) if r else {})}

def store(con,camid,raw,journey,channel):
    opts=options(raw,journey)
    if opts['template_id']:
        t=m.one('SELECT * FROM m41_templates WHERE id=?',(opts['template_id'],))
        if t['channel']!=channel or t['audience'] not in {'Both',journey}:raise ValueError('Choose a template with the same channel and compatible customer journey.')
    con.execute('INSERT INTO m41_campaign_options(campaign_id,options_json) VALUES(?,?) ON CONFLICT(campaign_id) DO UPDATE SET options_json=excluded.options_json',(camid,json.dumps(opts)))

def safe_context(camid,journey):
    opts=load(camid,journey)
    # Exclude names, signatures and actual CTA destinations from provider payload.
    return {'greeting_style':opts['greeting'],'message_length':opts['length'],
            'use_confirmed_preferences':opts['use_preferences']=='yes','sequence_days':[0,opts['day1'],opts['day2']],
            'sender_placeholder':'{{sender_name}}','signature_placeholder':'{{signature}}',
            'has_custom_cta':bool(opts['cta_text'] or opts['cta_url'])}

def tokens(camid,cid):
    c=ct.profile(cid);cam=m.campaign(camid);journey=cam['audience_type'] if cam['audience_type']!='Both' else ('B2C' if c['contact_type']=='B2C' else 'B2B')
    opts=load(camid,journey);base=m.personal_tokens(camid,cid)
    full=ct.clean_display_name(c.get('full_name'))
    first=ct.clean_display_name(c.get('first_name'))
    company=ct.clean_display_name(c.get('company_name'))
    who={'full':full, 'first':first, 'company':company, 'neutral':''}[opts['greeting']]
    if opts['greeting'] in {'full','first'} and not first and c.get('contact_type') in {'B2B','Both'}:
        who=ct.greeting_name(c)
    base['greeting']=('Hello '+who+',') if who else 'Hello,'
    if opts['cta_text'] or opts['cta_url']:
        base['cta']=opts['cta_text'] or 'Explore the collection'
        if opts['cta_url']:base['cta']+=': '+opts['cta_url']
    selected=[p for p in m.products() if p['product_id'] in cam['product_ids'] and p['confirmed']]
    base.update(first_name=c.get('first_name') or 'there',full_name=c.get('full_name') or 'there',
       company_name=c.get('company_name') or ('your business' if journey=='B2B' else ''),role_title=c.get('role_title') or '',
       product_name=selected[0]['public_product_name'] if selected else 'a piece from the collection',
       collection='; '.join(p['public_product_name'] for p in selected[:3]) or 'our selected saree collection',
       sender_name=opts['sender_name'],signature=opts['signature'])
    return base

def render(text,camid,cid):
    t=tokens(camid,cid)
    return re.sub(r'\{\{([a-z_]+)\}\}',lambda match:t.get(match[1],match[0]),str(text))

def local_signature_hash(camid,cid):
    opts=load(camid);t=tokens(camid,cid)
    template=m.one('SELECT * FROM m41_templates WHERE id=?',(opts['template_id'],)) if opts['template_id'] else None
    return hashlib.sha256(json.dumps({'options':opts,'tokens':t,'template':template},sort_keys=True).encode()).hexdigest()

def local_messages(ctx):
    b2b=ctx['journey']=='B2B';goal=ctx['goal'];p=ctx.get('personalisation',{})
    days=p.get('sequence_days',[0,4,9] if b2b else [0,3,7]);short=p.get('message_length')=='Concise'
    names='; '.join(x['public_product_name'] for x in ctx['products'][:3] if x['verified']) or 'a selected saree collection'
    intents={
      'Catalogue discovery':('A collection for your store' if b2b else 'A collection for you to explore', 'Which styles are you currently sourcing?' if b2b else 'Which colours or styles would you like to explore?'),
      'Wholesale enquiry':('Your next wholesale collection','Which styles and order quantities would you like us to discuss?'),
      'Sample request':('A closer look at the collection','Would detailed photos or a product discussion help you evaluate the collection?'),
      'Book a video consultation':('Explore the collection together','Would you like to arrange a video conversation for a closer look?'),
      'Reorder conversation':('Planning your next order?','Are you considering another order, and what would you like to explore?'),
      'New collection':('Explore this collection','Would you like help choosing a piece or comparing styles?'),
      'Styling consultation':('Find a style that feels like you','Do you have a preferred colour, style or budget you would like to share?'),
      'Festive collection':('A collection for your next occasion','Is there an occasion or style you would like help choosing for?'),
      'Customer feedback':('Your feedback would be helpful','What would make your next experience with us more useful?'),
      'Reconnect with customers':('Would you like to explore the collection?','Would you like to reconnect, or prefer we leave the conversation here?')}
    subject,question=intents.get(goal,intents['Catalogue discovery'])
    intro={'Warm and professional':'I am reaching out from {{brand}} to introduce',
           'Elegant and understated':'A considered introduction from {{brand}} to',
           'Friendly and conversational':'Hello from {{brand}}. Here is',
           'Direct and practical':'From {{brand}}: explore'}[ctx['tone'] if ctx['tone'] in TONES else TONES[0]]
    pref=ctx['contact_context'].get('preferences','')
    extra=('\n\nYou mentioned: '+pref) if pref else ''
    aim='We can discuss your sourcing requirements before preparing a quotation.' if b2b else 'We can help you compare pieces and choose at your own pace.'
    initial=f'{{{{greeting}}}}\n\n{intro} {names}.{extra}\n\n{question}'
    if not short:initial+='\n\n'+aim
    initial+='\n\n{{cta}}'
    follow=f'{{{{greeting}}}}\n\nA gentle follow-up from {{{{brand}}}} about the collection. {question}\n\n{{{{cta}}}}'
    final='{{greeting}}\n\nA final note from {{brand}}. There is no pressure to decide now. Shall we keep the conversation open, or leave it here?\n\n{{cta}}'
    texts=[initial,follow,final]
    if ctx['channel']=='WhatsApp':texts=[f'{{{{greeting}}}} {intro} {names}. {question} {{{{cta}}}}',follow,final]
    if ctx['channel']=='SMS':
        texts=['{{greeting}} From {{brand}}: would you like to explore our saree collection? {{cta}}',
               '{{greeting}} From {{brand}}: would a closer look at the collection help? {{cta}}',
               '{{greeting}} From {{brand}}: shall we continue the conversation or leave it here?']
    if ctx['channel']=='Phone':
        texts=[f'{{{{greeting}}}} I am calling from {{{{brand}}}}. Is now a convenient time for a short conversation?\n\nIf yes: {question}\n\nIf no: offer to end the call.\n\nAgree a next step only if they wish. {{{{cta}}}}',
               '{{greeting}} I am calling from {{brand}}. Is now a convenient time? Ask whether a collection discussion would help; do not assume a prior conversation. {{cta}}',
               '{{greeting}} I am calling from {{brand}}. Check whether the person would like further contact and record their answer. End politely if not.']
    why=('B2B sourcing' if b2b else 'B2C discovery')+'; '+goal+'; '+ctx['tone']+'; '+p.get('message_length','Standard')
    if pref:why+='; confirmed preferences used'
    return [{'step':i,'day_offset':days[i],'subject':([subject,'A closer look at the collection','Shall we keep in touch?'][i] if ctx['channel']=='Email' else ''),
      'alternative_subject':('Explore the collection with us' if ctx['channel']=='Email' else ''),'body':text,'why':why,
      'source_ids':[x['id'] for x in ctx['products'] if x['verified']]} for i,text in enumerate(texts)]

def save_template(raw):
    name=str(raw.get('name','')).strip()[:180];channel=raw.get('channel','Email');aud=raw.get('audience','Both')
    if not name:raise ValueError('Give the sequence template a name.')
    if channel not in {'Email','WhatsApp','Social DM','SMS','Phone'} or aud not in {'B2B','B2C','Both'}:raise ValueError('Choose a supported channel and journey.')
    msgs=[]
    for i in range(3):
        body=str(raw.get('body'+str(i),'')).strip();sub=str(raw.get('subject'+str(i),'')).strip() if channel=='Email' else ''
        if not body or len(body)>4000 or len(sub)>200:raise ValueError('Add three message bodies, each under 4,000 characters; subject lines must be under 200.')
        unknown=set(re.findall(r'\{\{([^}]+)\}\}',body+' '+sub))-TOKENS
        if unknown:raise ValueError('Unsupported merge fields: '+', '.join(sorted(unknown)))
        if '{{brand}}' not in body:raise ValueError('Include {{brand}} in each message so the sender is clear.')
        if re.search(r'127\.0\.0\.1|localhost|<script|<iframe',body+' '+sub,re.I):raise ValueError('Remove local links and embedded markup from the template.')
        msgs.append({'body':body,'subject':sub})
    tid=raw.get('id') or m.uid('TPL')
    if raw.get('id') and not m.one('SELECT id FROM m41_templates WHERE id=?',(tid,)):raise ValueError('Template not found.')
    with m.connect() as con:con.execute('''INSERT INTO m41_templates(id,name,audience,channel,messages_json) VALUES(?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET name=excluded.name,audience=excluded.audience,channel=excluded.channel,messages_json=excluded.messages_json,updated_at=CURRENT_TIMESTAMP''',(tid,name,aud,channel,json.dumps(msgs)))
    return tid

def template_messages(camid,cid,ctx):
    opts=load(camid,ctx['journey'])
    if not opts['template_id']:return None
    t=m.one('SELECT * FROM m41_templates WHERE id=?',(opts['template_id'],))
    if not t or t['channel']!=ctx['channel'] or t['audience'] not in {'Both',ctx['journey']}:raise ValueError('The saved template no longer matches this campaign. Review the campaign settings.')
    days=ctx['personalisation']['sequence_days']
    return [{'step':i,'day_offset':days[i],'subject':x['subject'],'alternative_subject':'','body':x['body'],
             'why':'Your reusable template: '+t['name']+'; locally merged from explicit contact fields. Review any factual claims.',
             'source_ids':[]} for i,x in enumerate(json.loads(t['messages_json']))]
