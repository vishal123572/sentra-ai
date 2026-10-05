// Runs actual frontend event handlers against a local disposable HTTP server.
// DOM objects are stubs: this verifies the action sequence, not browser layout.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const origin=process.argv[2];
const payload=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))throw new Error('Use a disposable loopback test server.');
const events={},nodes={};
const document={activeElement:null,body:{append(){}},addEventListener(name,handler){events[name]=handler;},
 getElementById(id){return nodes[id]??=( {innerHTML:'',textContent:'',className:'',showModal(){},addEventListener(){}} );},
 createElement(){return {click(){},remove(){}};}};
let cookie='';
const requests=[];
const context=vm.createContext({document,console,setTimeout,clearTimeout,URL,URLSearchParams,Intl,TextEncoder,
 window:{scrollTo(){}},FormData:class{constructor(form){return new Map(Object.entries(form.values));}},
 async fetch(path,options={}){
  requests.push({path,body:options.body?JSON.parse(options.body):null});
  const headers={...options.headers};if(cookie)headers.Cookie=cookie;
  const response=await fetch(origin+path,{...options,headers});
  const setCookie=response.headers.get('set-cookie');if(setCookie)cookie=setCookie.split(';')[0];
  return response;
 }});
vm.runInContext(fs.readFileSync('web/app.js','utf8').replace(/boot\(\);\s*$/,''),context);
async function settled(){
 for(let attempt=0;attempt<800;attempt++){
  if(!vm.runInContext('S.busy',context))return;
  await new Promise(resolve=>setTimeout(resolve,5));
 }
 throw new Error('Frontend operation did not finish.');
}
async function click(act,data={}){events.click({target:{closest(){return {disabled:false,dataset:{act,...data}};}}});await settled();}
async function submit(id,values){events.submit({preventDefault(){},target:{id,values}});await settled();}
async function main(){
 await submit('login-form',{username:'examiner',password:'SatSaDemo2026!'});
 assert.ok(vm.runInContext('S.user&&S.data.entities.length',context),'login loads workspace: '+vm.runInContext('S.error',context)+' '+nodes.toast?.textContent);
 const entity=vm.runInContext("S.data.entities.find(e=>e.name.includes('Atlas Grid'))",context);
 const unique='FLOW-'+crypto.randomUUID().slice(0,8)+'-';
 const files=Object.fromEntries(Object.entries(payload.files).map(([kind,file])=>[kind,{...file,content:file.content.replaceAll('ATL-',unique),mapping:{}}]));
 context.importFiles=files;context.importEntity=entity.id;
 vm.runInContext("S.import={entity:importEntity,start:'2026-09-01',end:'2026-10-01',files:importFiles,validation:null};S.page='upload';",context);
 context.bundleFile={size:JSON.stringify(files).length,async text(){return JSON.stringify({period_start:'2026-09-01',period_end:'2026-10-01',files});}};
 await vm.runInContext('loadBundle(bundleFile)',context);
 await click('validate');assert.equal(vm.runInContext('S.import.validation.valid',context),true);
 await click('run-assessment');
 assert.equal(vm.runInContext('S.page',context),'assessment','import opens complete assessment');
 assert.equal(vm.runInContext('S.assessment.selection.selected_count',context),8);
 assert.ok(nodes.app.innerHTML.includes('Peer benchmark'));
 const imported=vm.runInContext('S.assessment.submission.id',context);
 const historySize=vm.runInContext('S.data.submissions.length',context);
 vm.runInContext("S.filter={search:'will-hide-results',entity:'wrong-entity',kind:'Negative space',status:'dismissed'};S.import.files=importFiles;",context);
 await click('validate');await click('run-assessment');
 assert.equal(vm.runInContext('S.assessment.submission.id',context),imported,'duplicate upload opens its exact stored result');
 assert.equal(vm.runInContext('S.data.submissions.length',context),historySize,'duplicate upload preserves assessment history');
 assert.equal(vm.runInContext('S.filter.search',context),'','old search cannot hide the new upload');
 assert.equal(vm.runInContext('S.period',context),'assessment:'+imported,'upload selects its exact assessment');
 await click('reanalyse');
 assert.equal(vm.runInContext('S.modal.type',context),'reanalyse');
 await submit('reanalyse-form',{reason:'Check that the same stored engine opens the existing immutable result.'});
 assert.equal(vm.runInContext('S.assessment.submission.id',context),imported);
 assert.equal(vm.runInContext('S.modal',context),null,'re-analysis closes its modal after opening the result');
 console.log('PASS repeated upload → exact assessment → cleared filters → same-engine re-analysis preserves history');
 await click('recommended');assert.equal(vm.runInContext('S.modal.type',context),'recommended');
 const selected=vm.runInContext('S.assessment.selection.records[0]',context);
 const submission=vm.runInContext('S.assessment.submission.id',context);
 await click('open-record',{submission,kind:selected.kind,id:selected.record_id});
 assert.equal(vm.runInContext('S.modal.type',context),'record');
 assert.ok(nodes.app.innerHTML.includes('Expected evidence'));
 await click('finding-tab',{tab:'records'});
 assert.ok(nodes.app.innerHTML.includes('Selected cases record'));
 await click('finding-tab',{tab:'provenance'});
 assert.ok(nodes.app.innerHTML.includes('File SHA-256'));
 const finding=vm.runInContext('S.modal.data.signals[0]',context);
 await click('finding',{id:finding.id});
 assert.ok(vm.runInContext('S.modal.back.type',context)==='record');
 assert.ok(nodes.app.innerHTML.includes('Evidence Investigation'));
 assert.ok(nodes.app.innerHTML.includes('Unverified — input presence'));
 await click('decision-intent',{status:'clarification'});
 assert.equal(vm.runInContext('S.modal.intent',context),'clarification');
 await click('finding-tab',{tab:'review'});
 await submit('review-form',{status:'clarification',comment:'Synthetic workflow check: confirm source export and escalation evidence.'});
 assert.equal(vm.runInContext('S.modal.data.status',context),'clarification');
 assert.ok(vm.runInContext('S.modal.data.reviews.length',context)>0);
 const write=requests.find(request=>request.path.endsWith('/review'));
 assert.equal(write.body.version,1,'decision uses preserved concurrency version');
 await click('back-modal');assert.equal(vm.runInContext('S.modal.type',context),'record');
 assert.equal(vm.runInContext('S.modal.data.signals[0].status',context),'clarification','back view refreshes decision');
 await click('back-recommended');assert.equal(vm.runInContext('S.modal.type',context),'recommended');
 await click('close-modal');
 await click('assessment-sample');
 assert.equal(vm.runInContext('S.modal.type',context),'sample');
 const unflagged=vm.runInContext('S.modal.data.records[0].case_id',context);
 await click('open-record',{submission,kind:'cases',id:unflagged});
 assert.equal(vm.runInContext('S.modal.data.signals.length',context),0);
 await click('back-modal');
 await click('observe-sample',{id:unflagged});
 await submit('sample-observation-form',{status:'needs_info',comment:'Please confirm the response and closure evidence for independent review.'});
 assert.equal(vm.runInContext('S.modal.type',context),'sample');
 assert.equal(vm.runInContext('S.modal.data.observations[0].status',context),'needs_info');
 assert.equal(requests.find(r=>r.path.endsWith('/sample-observation')).body.version,0);
 await click('close-modal');
 await click('blind-review',{submission});
 assert.ok(nodes.toast.textContent.includes('downloaded'));
 const labels=[{unit:'cases',record_id:selected.record_id,expert_concern:'true',adjudicated:'true',split:'held_out'},{unit:'cases',record_id:unflagged,expert_concern:'false',adjudicated:'true',split:'held_out'}];
 context.labelFile={name:'labels.json',size:JSON.stringify(labels).length,async text(){return JSON.stringify(labels);}};
 vm.runInContext('loadExpertLabels(labelFile)',context);await settled();
 assert.equal(vm.runInContext('S.modal.type',context),'evaluation');
 assert.equal(vm.runInContext('S.modal.data.labelled_records',context),2);
 await click('close-modal');
 await click('report',{format:'html',submission});
 assert.ok(nodes.toast.textContent.includes('downloaded'));
 console.log('PASS login → bundle load → validate → import → assessment → ranked sample → record explanations → source/timeline → examiner decision → refreshed evidence → independent evidence → saved observation → blinded export → expert comparison → HTML export');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
