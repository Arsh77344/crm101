'use strict';
// Local UI conveniences. No trackers, marketing transports or remote scripts.
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-lookup]').forEach(el=>{
    const input=el.querySelector('.lookup-input'),hidden=el.querySelector('input[type=hidden]'),box=el.querySelector('.lookup-results');
    const id='lookup-'+Math.random().toString(36).slice(2);box.id=id;input.setAttribute('aria-controls',id);
    let timer,seq=0;
    const close=()=>{box.hidden=true;input.setAttribute('aria-expanded','false');};
    input.addEventListener('input',()=>{
      hidden.value='';clearTimeout(timer);const token=++seq;const term=input.value.trim();close();if(term.length<2)return;
      timer=setTimeout(async()=>{
        try{
          const r=await fetch('/api/record-search?kind='+encodeURIComponent(el.dataset.lookup)+'&q='+encodeURIComponent(term));
          if(!r.ok)throw new Error('Search unavailable');const data=await r.json();if(token!==seq)return;
          box.replaceChildren();
          if(!data.length){const t=document.createElement('div');t.textContent='No matching records';t.className='empty';box.append(t);}
          data.forEach((record,index)=>{
            const b=document.createElement('button');b.type='button';b.setAttribute('role','option');b.id=id+'-'+index;b.textContent=record.label||record.id;
            const sub=document.createElement('small');sub.textContent=record.detail||record.type;b.append(sub);
            b.addEventListener('click',()=>{hidden.value=record.id;input.value=record.label||record.id;close();input.focus();});
            b.addEventListener('keydown',ev=>{if(ev.key==='Escape'){close();input.focus();}if(ev.key==='ArrowDown'){ev.preventDefault();b.nextElementSibling?.focus();}if(ev.key==='ArrowUp'){ev.preventDefault();if(b.previousElementSibling)b.previousElementSibling.focus();else input.focus();}});
            box.append(b);
          });box.hidden=false;input.setAttribute('aria-expanded','true');
        }catch(err){if(token!==seq)return;box.textContent='Search could not load. Try again.';box.hidden=false;}
      },180);
    });
    input.addEventListener('keydown',ev=>{if(ev.key==='ArrowDown'&&!box.hidden){ev.preventDefault();box.querySelector('button')?.focus();}if(ev.key==='Enter'&&!hidden.value&&!box.hidden){ev.preventDefault();box.querySelector('button')?.click();}if(ev.key==='Escape')close();});
    document.addEventListener('click',ev=>{if(!el.contains(ev.target))close();});
    el.closest('form')?.addEventListener('submit',ev=>{if(input.value.trim()&&!hidden.value){ev.preventDefault();window.alert('Choose a '+el.dataset.lookup.toLowerCase()+' search result, or clear its name.');input.focus();}});
  });
  document.querySelectorAll('[data-bulk]').forEach(form=>{
    const checkboxes=[...form.querySelectorAll('[name=contact_ids]')],all=form.querySelector('[data-select-page]'),count=form.querySelector('[data-selection-count]');
    const update=()=>{const n=checkboxes.filter(x=>x.checked).length;count.textContent=String(n);all.indeterminate=n>0&&n<checkboxes.length;all.checked=n===checkboxes.length&&n>0;};
    all.addEventListener('change',()=>{checkboxes.forEach(x=>x.checked=all.checked);update();});checkboxes.forEach(x=>x.addEventListener('change',update));
    form.querySelector('[data-open-bulk]').addEventListener('click',()=>{const panel=form.querySelector('#bulk-panel');panel.open=true;panel.scrollIntoView({block:'center'});});
    form.addEventListener('submit',ev=>{if(!checkboxes.some(x=>x.checked)){ev.preventDefault();window.alert('Select at least one contact on this page.');}});
  });
  document.querySelectorAll('[data-action-form]').forEach(form=>{
    const select=form.querySelector('[name=action]');if(!select)return;
    const show=()=>form.querySelectorAll('[data-action-kind]').forEach(el=>{el.hidden=!el.dataset.actionKind.split(' ').includes(select.value);});
    select.addEventListener('change',show);show();
  });
  const pipelines={B2B:['New','Qualified','Showroom Sent','Quote Sent','Negotiation','Won','Lost'],B2C:['New','Enquiry','Selection Confirmed','Payment Pending','Won','Lost'],Unassigned:['New','Qualified','Showroom Sent','Negotiation','Won','Lost']};
  const p=document.querySelector('select[name=pipeline]');
  if(p){p.addEventListener('change',()=>{const s=p.closest('form').querySelector('select[name=stage]');s.replaceChildren();for(const stage of pipelines[p.value]||[]){const o=document.createElement('option');o.value=stage;o.textContent=stage;s.append(o);}});}
  document.querySelectorAll('[data-move-form]').forEach(form=>form.addEventListener('submit',ev=>{
    const stage=form.querySelector('[name=stage]').value;
    if(['Won','Lost'].includes(stage)&&!window.confirm('Move this deal to '+stage+'? This does not confirm payment or send any message.'))ev.preventDefault();
  }));
  const board=document.querySelector('[data-board]');let card=null;
  if(board){
    board.querySelectorAll('[data-deal]').forEach(c=>{
      c.addEventListener('dragstart',ev=>{card=c;c.classList.add('dragging');ev.dataTransfer.effectAllowed='move';ev.dataTransfer.setData('text/plain',c.dataset.deal);});
      c.addEventListener('dragend',()=>{c.classList.remove('dragging');card=null;board.querySelectorAll('.drag-over').forEach(e=>e.classList.remove('drag-over'));});
    });
    board.querySelectorAll('[data-stage]').forEach(lane=>{
      lane.addEventListener('dragover',ev=>{if(card&&lane.dataset.stage!=='Other / legacy'){ev.preventDefault();lane.classList.add('drag-over');}});
      lane.addEventListener('dragleave',()=>lane.classList.remove('drag-over'));
      lane.addEventListener('drop',ev=>{ev.preventDefault();lane.classList.remove('drag-over');if(!card||lane.dataset.stage==='Other / legacy')return;const f=card.querySelector('form');const s=f.querySelector('[name=stage]');if(s.value===lane.dataset.stage)return;s.value=lane.dataset.stage;f.requestSubmit();});
    });
  }
});

// V25 owner-first interaction helpers.
document.addEventListener('DOMContentLoaded',()=>{
  const globalSearch=document.getElementById('global-search');
  document.addEventListener('keydown',ev=>{
    if((ev.metaKey||ev.ctrlKey)&&ev.key.toLowerCase()==='k'&&globalSearch){ev.preventDefault();globalSearch.focus();globalSearch.select();}
    if(ev.key==='Escape')document.querySelectorAll('.quick-create[open]').forEach(x=>x.removeAttribute('open'));
  });

  const quick=document.querySelector('.quick-create');
  if(quick){
    document.addEventListener('click',ev=>{if(!quick.contains(ev.target))quick.removeAttribute('open');});
  }

  // Warn only on substantial edit forms, not quick status/filter controls.
  const editForms=[...document.querySelectorAll('form[method="post" i]')].filter(form=>{
    if(form.hasAttribute('data-no-dirty'))return false;
    const editable=form.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]),textarea,select');
    return form.querySelector('textarea')||editable.length>=3;
  });
  let dirtyForm=null;
  editForms.forEach(form=>{
    const mark=()=>{dirtyForm=form;form.dataset.unsaved='1';};
    form.addEventListener('input',mark);form.addEventListener('change',mark);
    form.addEventListener('submit',()=>{form.dataset.unsaved='0';if(dirtyForm===form)dirtyForm=null;});
  });
  window.addEventListener('beforeunload',ev=>{if(dirtyForm&&dirtyForm.dataset.unsaved==='1'){ev.preventDefault();ev.returnValue='';}});

  // Clearer feedback for ordinary server-side actions.
  document.querySelectorAll('form[method="post" i]:not([data-busy])').forEach(form=>form.addEventListener('submit',ev=>{
    if(ev.defaultPrevented)return;
    const btn=ev.submitter||form.querySelector('button[type=submit],button:not([type])');
    if(!btn||btn.disabled)return;
    const original=btn.textContent.trim();
    const busy=/save|update|create|add/i.test(original)?'Saving…':'Working…';
    setTimeout(()=>{if(!ev.defaultPrevented){btn.disabled=true;btn.dataset.originalLabel=original;btn.textContent=busy;}},0);
  }));

  // On phones, navigating should close the drawer immediately.
  document.querySelectorAll('aside a.nav').forEach(link=>link.addEventListener('click',()=>document.querySelector('aside')?.classList.remove('open')));
});

// V45 accessible mobile navigation drawer.
document.addEventListener('DOMContentLoaded',()=>{
  const menu=document.querySelector('[data-menu]');
  const aside=document.getElementById('primary-navigation');
  const backdrop=document.querySelector('[data-menu-close]');
  if(!menu||!aside)return;
  const setOpen=open=>{
    aside.classList.toggle('open',open);
    menu.setAttribute('aria-expanded',open?'true':'false');
    menu.setAttribute('aria-label',open?'Close navigation':'Open navigation');
    if(backdrop)backdrop.tabIndex=open?0:-1;
  };
  // Replace the earlier visual-only toggle with an ARIA-synchronised state.
  menu.addEventListener('click',()=>setOpen(aside.classList.contains('open')));
  backdrop?.addEventListener('click',()=>{setOpen(false);menu.focus();});
  document.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&aside.classList.contains('open')){setOpen(false);menu.focus();}});
  aside.querySelectorAll('a.nav').forEach(link=>link.addEventListener('click',()=>setOpen(false)));
});

// V47 generic bulk selection helper. Checkboxes may live outside the form and
// use the HTML form= attribute so row-level action forms remain valid HTML.
document.querySelectorAll('[data-select-form]').forEach(btn=>{
  btn.addEventListener('click',()=>{
    const id=btn.getAttribute('data-select-form');
    const boxes=[...document.querySelectorAll('input[type=checkbox][form="'+id+'"]')];
    const shouldCheck=boxes.some(x=>!x.checked);
    boxes.forEach(x=>{x.checked=shouldCheck;});
    btn.textContent=shouldCheck?'Clear visible':'Select visible';
  });
});
