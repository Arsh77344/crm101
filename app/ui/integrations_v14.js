(function(){
  'use strict';
  const root=document.getElementById('wa-embedded');
  if(!root)return;
  const button=document.getElementById('wa-connect-button');
  const status=document.getElementById('wa-status');
  const form=document.getElementById('wa-complete-form');
  const appId=root.dataset.appId||'';
  const configId=root.dataset.configId||'';
  const version=root.dataset.graphVersion||'v26.0';
  let authCode='';
  let result={};
  function say(msg){if(status)status.textContent=msg;}
  function maybeSubmit(){
    if(!authCode||!result.waba_id||!result.phone_number_id)return;
    document.getElementById('wa-code').value=authCode;
    document.getElementById('wa-waba').value=result.waba_id;
    document.getElementById('wa-phone').value=result.phone_number_id;
    document.getElementById('wa-business').value=result.business_id||'';
    say('Meta setup completed. Validating the WhatsApp business number...');
    form.submit();
  }
  window.addEventListener('message',function(event){
    if(event.origin!=='https://www.facebook.com'&&event.origin!=='https://web.facebook.com')return;
    let data=event.data;
    try{if(typeof data==='string')data=JSON.parse(data);}catch(_){return;}
    if(!data||data.type!=='WA_EMBEDDED_SIGNUP')return;
    if(data.event==='FINISH'){
      const d=data.data||{};
      result={waba_id:d.waba_id||d.wabaId||'',phone_number_id:d.phone_number_id||d.phoneNumberId||'',business_id:d.business_id||d.businessId||''};
      maybeSubmit();
    }else if(data.event==='CANCEL'){say('WhatsApp setup was cancelled. Nothing was connected.');}
    else if(data.event==='ERROR'){say('Meta could not complete WhatsApp setup. Review the Meta setup and try again.');}
  });
  window.fbAsyncInit=function(){
    window.FB.init({appId:appId,autoLogAppEvents:true,xfbml:false,version:version});
  };
  const sdk=document.createElement('script');sdk.async=true;sdk.defer=true;sdk.crossOrigin='anonymous';sdk.src='https://connect.facebook.net/en_US/sdk.js';document.head.appendChild(sdk);
  button.addEventListener('click',function(){
    if(!appId||!configId){say('WhatsApp login is not configured on this platform yet.');return;}
    if(!window.FB){say('Meta login is still loading. Try again in a moment.');return;}
    say('Opening secure Meta onboarding...');
    window.FB.login(function(response){
      if(response&&response.authResponse&&response.authResponse.code){authCode=response.authResponse.code;maybeSubmit();}
      else if(!authCode){say('Meta login did not return an authorisation code. Nothing was connected.');}
    },{config_id:configId,response_type:'code',override_default_response_type:true,extras:{setup:{}}});
  });
})();
