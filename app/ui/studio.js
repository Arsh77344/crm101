'use strict';
// No analytics, remote libraries, or automatic sending.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelector('[data-menu]')?.addEventListener('click', () => document.querySelector('aside').classList.toggle('open'));
  document.querySelectorAll('[data-confirm]').forEach(form => form.addEventListener('submit', e => {
    if (!window.confirm(form.dataset.confirm)) e.preventDefault();
  }));
  const wizard = document.querySelector('[data-wizard]');
  let current = 0;
  if (wizard) {
    const panels = [...wizard.querySelectorAll('.wizard-step')];
    const steps = [...document.querySelectorAll('.steps li')];
    function show(i) {
      current = Math.max(0, Math.min(panels.length - 1, i));
      panels.forEach((p,n) => p.hidden = n !== current);
      steps.forEach((s,n) => s.classList.toggle('current', n === current));
      if (current === 2) previewAudience();
      window.scrollTo({top:0,behavior:'auto'});
    }
    wizard.querySelectorAll('[data-next]').forEach(b => b.addEventListener('click', () => {
      for (const input of panels[current].querySelectorAll('input,select,textarea')) {
        if (!input.checkValidity()) {input.reportValidity(); return;}
      }
      if (current === 1 && !wizard.querySelector('[name=product_ids]:checked')) {window.alert('Choose at least one product.'); return;}
      show(current + 1);
    }));
    wizard.querySelectorAll('[data-back]').forEach(b => b.addEventListener('click', () => show(current - 1)));
    async function previewAudience() {
      const target=document.getElementById('audience-preview');
      target.textContent='Checking your local contact database...';
      const params=new URLSearchParams(new FormData(wizard));
      try {
        const r=await fetch('/api/audience?' + params, {credentials:'same-origin'});
        const data=await r.json();
        if (!r.ok) throw new Error(data.error || 'Could not preview the audience');
        target.replaceChildren();
        const heading=document.createElement('h3');heading.textContent=data.matching.toLocaleString()+' contacts match your planning filters';target.append(heading);
        const note=document.createElement('p');note.className='helper';note.textContent=data.selected.length+' selected for this draft campaign. '+data.eligible+' have documented channel permission in the matching pool. '+data.duplicates+' duplicate addresses omitted. '+data.suppressed+' suppressed records omitted.';target.append(note);
        for(const c of data.selected.slice(0,5)) {
          const row=document.createElement('div');row.className='readiness-row';
          const main=document.createElement('span');main.className='row-main';main.textContent=c.name+' / '+c.type;
          const status=document.createElement('span');status.className='pill '+(c.eligible?'good':'warn');status.textContent=c.reason;
          row.append(main,status);target.append(row);
        }
      } catch(err) {target.textContent=err.message;}
    }
    wizard.addEventListener('submit',e=>{
      if(current !== panels.length-1){e.preventDefault();show(current+1);}
    });
    show(0);
  }
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    const text=document.getElementById(button.dataset.copy)?.value;
    if (!text) return;
    try {await navigator.clipboard.writeText(text); const prev=button.textContent;button.textContent='Copied preview';setTimeout(()=>button.textContent=prev,1800);}
    catch {window.alert('Select the draft text and press Command + C to copy it.');}
  }));
  document.querySelectorAll('form[data-busy]').forEach(form => form.addEventListener('submit',()=>{
    const submit=form.querySelector('button[type=submit],button:not([type])');
    if(submit){setTimeout(()=>{submit.disabled=true;submit.textContent=form.dataset.busy;},0);}
  }));
});
