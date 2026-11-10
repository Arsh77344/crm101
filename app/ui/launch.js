(() => {
  'use strict';
  const drop = document.querySelector('.lp-drop');
  if (drop) {
    const input = drop.querySelector('input[type=file]');
    const preview = document.querySelector('.lp-upload-preview');
    let urls = [];
    const show = () => {
      urls.forEach(URL.revokeObjectURL); urls = []; preview.replaceChildren();
      let bytes = 0;
      for (const file of input.files) {
        bytes += file.size;
        if (/image\/(jpeg|png|webp)/.test(file.type)) {
          const img = document.createElement('img');
          img.src = URL.createObjectURL(file); urls.push(img.src); img.alt = file.name; preview.append(img);
        }
      }
      input.setCustomValidity(input.files.length > 20 || bytes > 80 * 1024 * 1024 || [...input.files].some(f => f.size > 20 * 1024 * 1024)
        ? 'Choose up to 20 photos, 20 MB each and 80 MB total.' : '');
      const count = document.createElement('small');count.textContent = `${input.files.length} photo(s) selected`; preview.append(count);
    };
    input.addEventListener('change', show);
    ['dragenter', 'dragover'].forEach(event => drop.addEventListener(event, e => {e.preventDefault(); drop.classList.add('dragover');}));
    ['dragleave', 'drop'].forEach(event => drop.addEventListener(event, e => {e.preventDefault(); drop.classList.remove('dragover');}));
    drop.addEventListener('drop', e => {if(e.dataTransfer.files.length){input.files = e.dataTransfer.files;show();}});
  }
  let changed = false;
  document.querySelectorAll('.lp-photo').forEach(photo => {
    const version=photo.querySelector('select[name^="selected_"]');
    const approved=photo.querySelector('input[name^="approve_"]');
    if(version)version.addEventListener('change',()=>{
      photo.querySelector('.lp-comparison figure:last-child img').src='/'+version.value;
      if(approved)approved.checked=false;
    });
    photo.querySelectorAll('textarea,select[name^="colour_"]').forEach(field=>field.addEventListener('input',()=>{if(approved)approved.checked=false;}));
  });
  const dirtyForms = new Set();
  document.querySelectorAll('.lp form').forEach(form => {
    form.dataset.noDirty = '1';
    form.addEventListener('input', () => { changed = true; dirtyForms.add(form); });
    form.addEventListener('submit', e => {
      if([...dirtyForms].some(other => other !== form) && !window.confirm('You have unsaved changes in another section. Continue without saving those changes?')){e.preventDefault();return;}
      changed = false; form.querySelectorAll('button[type=submit]').forEach(b => {b.disabled = true;});
    });
  });
  window.addEventListener('beforeunload', e => {if(changed){e.preventDefault();e.returnValue = '';}});
  const progress = document.querySelector('[data-launch-status]');
  if(progress){
    const poll = async () => {
      try {const response = await fetch(progress.dataset.launchStatus, {credentials:'same-origin'});
        if(response.ok){const state=await response.json();
          if(!state.busy || String(state.revision)!==progress.dataset.revision){location.reload();return;}
          const message=progress.querySelector('[data-job-message]');if(message&&state.job?.message)message.textContent=state.job.message;
        }
      } catch (_) { /* A temporary connection failure must not restart a paid job. */ }
      setTimeout(poll, 3000);
    };setTimeout(poll, 2000);
  }
  const load = document.querySelector('[data-store-load]');
  if(load){
    const form=load.closest('form'); const note=form.querySelector('[data-store-note]');
    form.elements.connection_id.addEventListener('change',()=>{
      ['location_id','publication_id'].forEach(name=>form.elements[name].replaceChildren(new Option('Load store options','')));note.textContent='';
    });
    load.addEventListener('click',async()=>{
      if(!form.elements.connection_id.value){note.textContent='Choose a store first.';return;}
      load.disabled=true;note.textContent='Loading your store…';
      try{
        const response=await fetch('/launch/store?'+new URLSearchParams({connection_id:form.elements.connection_id.value}),{credentials:'same-origin'});
        if(!response.ok)throw new Error('Could not load the store. Check its connection and permissions in Connected apps.');
        const data=await response.json();
        for(const [key,name] of [['locations','location_id'],['publications','publication_id']]){
          const select=form.elements[name];select.replaceChildren(new Option('Choose…',''));
          (data[key]?.nodes || []).forEach(item=>select.add(new Option(item.name,item.id)));
        }
        note.textContent=data.shop ? `Store currency: ${data.shop.currencyCode}. Choose the stock location and sales channel below.` : 'For Wix, confirm the currency from your store settings below. Shopify options do not apply.';
      }catch(error){note.textContent=error.message;}finally{load.disabled=false;}
    });
  }
})();
