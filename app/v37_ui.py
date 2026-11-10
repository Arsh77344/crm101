from __future__ import annotations
import v37_business_readiness as br

class V37BusinessPages:
    def v37_get(self,path,q):
        if path=='/business-exceptions':self.business_exceptions(q)
        elif path=='/business-readiness':self.business_readiness(q)
        elif path=='/crm-health':self.crm_health(q)
        else:return False
        return True

    def business_exceptions(self,q):
        import app
        rows=br.business_exceptions()
        body=app.pagehead('Needs attention','One exception-first queue. Normal successful work stays quiet; only items needing a decision, repair or follow-up appear here.',app.button('Business readiness','/business-readiness','secondary'))
        if not rows:body+=app.notice('No current business exceptions were found.','success')
        for x in rows:
            kind='warn' if x['priority'] in {'Critical','High'} else 'purple'
            advanced=''
            if x.get('technical_detail'):
                advanced='<details class="manual-entry section"><summary>Advanced details</summary><div class="manual-body"><p class="tiny muted">'+app.e(x['technical_detail'])+'</p></div></details>'
            body+=f'<div class="card section"><div class="message-top"><div><span class="pill {kind}">{app.e(x["priority"])}</span> <span class="pill purple">{app.e(x["kind"])}</span><h3>{app.e(x["title"])}</h3><p class="helper">{app.e(x["detail"])}</p>{advanced}</div>{app.button(x.get("action_label") or "Open recovery",x["url"],"secondary")}</div></div>'
        self.send_html(app.layout('Needs attention',body,'exceptions'))

    def business_readiness(self,q):
        import app
        rows=br.readiness_scorecard(app.ROOT)
        body=app.pagehead('Business readiness','Factual launch-readiness by domain. A critical failure is never hidden behind an overall percentage.',app.button('Needs attention','/business-exceptions','secondary')+app.button('System health','/system-health','secondary'))
        body+='<div class="card section"><table><thead><tr><th>Domain</th><th>Status</th><th>Evidence / condition</th><th></th></tr></thead><tbody>'
        for r in rows:
            kind='good' if r['status']=='READY' else 'warn' if r['status']=='NOT READY' else 'purple'
            body+=f'<tr><td><strong>{app.e(r["domain"])}</strong></td><td><span class="pill {kind}">{app.e(r["status"])}</span></td><td>{app.e(r["why"])}</td><td>{app.button("Open",r["url"],"secondary small")}</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('Business readiness',body,'readiness'))

    def crm_health(self,q):
        import app
        h=br.crm_health();body=app.pagehead('CRM health','Database-quality indicators so the owner can see whether customer data is trustworthy.',app.button('Customers & leads','/contacts','secondary'))
        cards=[('Profiles',str(h['total'])),('Quality estimate',str(h['quality_percent'])+'%'),('Possible duplicate emails',str(h['duplicate_email_rows'])),('Possible duplicate phones',str(h['duplicate_phone_rows'])),('Invalid emails',str(h['invalid_email'])),('Invalid phones',str(h['invalid_phone'])),('Missing names',str(h['missing_name'])),('Missing source',str(h['missing_source']))]
        body+='<div class="metric-grid section">'+''.join(f'<div class="metric"><span>{app.e(k)}</span><strong>{app.e(v)}</strong></div>' for k,v in cards)+'</div><div class="card section"><h2>How to use this</h2><p class="helper">These are quality indicators, not automatic merge instructions. Duplicate candidates should be reviewed before merging when identity is uncertain.</p></div>'
        self.send_html(app.layout('CRM health',body,'contacts'))
