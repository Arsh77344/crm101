from __future__ import annotations

import json
import handover_core as hc


def _pill(status:str)->str:
    s=(status or '').lower()
    if s in {'fully working','working','ready','verified','configured'}:kind='good'
    elif 'partial' in s or 'configured' in s or 'optional' in s:kind='purple'
    elif 'not implemented' in s or 'ui only' in s or 'placeholder' in s:kind='muted'
    else:kind='warn'
    return f'<span class="pill {kind}">{status}</span>'


class HandoverPages:
    def v15_get(self,path,q):
        if path in {'/handover','/start-here'}:self.v15_handover(q)
        elif path=='/v15-e2e':self.v15_e2e(q)
        elif path=='/external-requirements':self.v15_external_requirements(q)
        elif path=='/v15-doctor.json':return self.json_response(hc.doctor_report())
        else:return False
        return True

    def v15_post(self,path,f):
        if path=='/v15/openai/test':
            hc.verify_openai_connection();return self.redirect('/handover?ai_tested=1')
        return False

    def v15_handover(self,q):
        import app
        report=hc.journey_audit()
        by_no={x['no']:x for x in report['steps']}
        def state(step_no):
            raw=by_no.get(step_no,{}).get('status','Requires setup')
            if raw in {'Working','Ready'}:return ('Done','done')
            if raw=='Partial':return ('In progress','')
            return ('Needs setup','')
        setup=[
            (1,'Business details','Confirm the business name, currency and the basics the system should use everywhere.','/setup'),
            (2,'Connect the apps you use','Sign in to your store, social, advertising and email accounts when you are ready.','/integrations'),
            (3,'Add products from photos','Upload product photos. The system prepares draft records and shows you what needs review.','/product-engine'),
            (10,'Create your first campaign','Choose what you want to achieve. The system prepares channel-specific campaign content.','/campaign-builder'),
        ]
        completed=sum(1 for no,_,_,_ in setup if state(no)[0]=='Done')
        next_step=next(((no,title,desc,url) for no,title,desc,url in setup if state(no)[0]!='Done'),setup[-1])
        body=app.pagehead('Get your business ready','Complete the essentials once. After that, Home will tell you what needs attention each day.',app.button('Go to Home','/today','secondary'))
        if q.get('ai_tested'):body+=app.notice('AI access was checked successfully.','success')
        body+=f'<div class="onboarding-progress"><div class="onboarding-hero"><div class="eyebrow">Your next step</div><h2>{app.e(next_step[1])}</h2><p>{app.e(next_step[2])}</p>{app.button("Continue setup",next_step[3])}</div><div class="onboarding-summary"><div class="eyebrow">Setup progress</div><strong>{completed} of {len(setup)}</strong><p>These are the only essentials you need to complete before the system can do most of the routine preparation for you.</p></div></div>'
        body+='<div class="section"><div class="eyebrow">Your setup checklist</div><h2>Four steps to get started</h2><div class="setup-checklist">'
        for i,(no,title,desc,url) in enumerate(setup,1):
            label,cls=state(no)
            action='Review' if label=='Done' else ('Continue' if label=='In progress' else 'Start')
            marker='&#10003;' if cls=='done' else str(i)
            body+=f'<div class="setup-step {cls}"><div class="step-num">{marker}</div><span class="setup-status">{app.e(label)}</span><h3>{app.e(title)}</h3><p>{app.e(desc)}</p>{app.button(action,url,"secondary small")}</div>'
        body+='</div></div>'
        body+='<div class="section"><div class="eyebrow">What the system handles</div><h2>You review decisions; the OS handles the routine preparation</h2><div class="what-happens-grid"><div class="what-happens-card"><strong>Products</strong><span>Organises photos, prepares product drafts, flags missing facts and creates marketing-ready assets.</span></div><div class="what-happens-card"><strong>Marketing</strong><span>Builds channel-specific campaign content and checks whether each connected channel is ready.</span></div><div class="what-happens-card"><strong>Customers</strong><span>Keeps customer records, tasks, opportunities, consent and follow-up work together.</span></div><div class="what-happens-card"><strong>Operations</strong><span>Tracks orders, stock, background work and exceptions that need your attention.</span></div></div></div>'
        requirements=sum(1 for x in hc.external_requirements() if x['status'].startswith('Required'))
        body+=f'<details class="advanced-readiness"><summary>Advanced readiness details</summary><div class="advanced-body"><p class="helper">For technical setup or deployment work, you can inspect the detailed readiness reports. These are not part of the normal daily workflow.</p><div class="actions">{app.button("Detailed system readiness","/capability-audit","secondary")}{app.button("External setup requirements","/external-requirements","secondary")}{app.button("Full end-to-end check","/v17-e2e","secondary")}</div><p class="helper">Current journey: {report["counts"].get("Working",0)} working, {report["counts"].get("Partial",0)} partial, {report["counts"].get("Requires setup",0)} need setup. External items still required: {requirements}.</p></div></details>'
        self.send_html(app.layout('Start here',body,'handover'))

    def v15_e2e(self,q):
        import app
        report=hc.journey_audit();body=app.pagehead('Strict end-to-end business journey','This audit uses evidence and configuration, not the existence of a button/table, and never sends, publishes or spends.',app.button('Start here','/handover','secondary'))
        body+=f'<div class="card section"><h2>{_pill(report["status"])}</h2><p class="helper">Working means the relevant local workflow/evidence exists. Partial means a real implementation exists but the complete business outcome is not yet covered.</p></div><div class="card section"><table><thead><tr><th>#</th><th>Business stage</th><th>Status</th><th>Evidence / limitation</th><th></th></tr></thead><tbody>'
        for x in report['steps']:
            body+=f'<tr><td>{x["no"]}</td><td><strong>{app.e(x["label"])}</strong></td><td>{_pill(x["status"])}</td><td>{app.e(x["detail"])}</td><td>{app.button("Open",x["action_url"],"secondary small") if x.get("action_url") else ""}</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('End-to-end journey',body,'e2e'))

    def v15_external_requirements(self,q):
        import app
        rows=hc.external_requirements();body=app.pagehead('What you still need to provide','External accounts, approvals and infrastructure the application cannot manufacture for you.',app.button('Start here','/handover','secondary'))
        body+='<div class="card section"><table><thead><tr><th>Requirement</th><th>Status</th><th>Why</th><th>Where you get it</th><th>Where it goes</th><th>When</th></tr></thead><tbody>'
        for r in rows:
            body+=f'<tr><td><strong>{app.e(r["item"])}</strong></td><td>{_pill(r["status"])}</td><td>{app.e(r["why"])}</td><td>{app.e(r["where_get"])}</td><td>{app.e(r["where_go"])}</td><td>{app.e(r["when"])}</td></tr>'
        body+='</tbody></table></div>'
        self.send_html(app.layout('External requirements',body,'handover'))
