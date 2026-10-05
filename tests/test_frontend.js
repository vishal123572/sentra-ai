// Dependency-free render smoke tests. These complement HTTP tests, not browser QA.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const document = {getElementById(){return {innerHTML:'',textContent:'',className:'',showModal(){},addEventListener(){}};},addEventListener(){},activeElement:null};
const context=vm.createContext({document,console,setTimeout,clearTimeout,URL,URLSearchParams,Intl,FormData,window:{scrollTo(){}},fetch(){throw new Error('Network not expected in render tests');}});
let source=fs.readFileSync('web/app.js','utf8');
source=source.replace(/boot\(\);\s*$/, '');
vm.runInContext(source,context);
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
context.fixture=fixture.state||fixture;
vm.runInContext("S.user={username:'examiner',role:'admin',csrf:'test'}; S.data=fixture; S.import.entity=fixture.entities[0].id;",context);
for(const name of ['overview','entitiesPage','findingsPage','reviewPage','uploadPage','reportsPage','methodologyPage']){
 const html=vm.runInContext(name+'()',context);
 assert.ok(html.length>300,name+' rendered');
 assert.ok(!html.includes('undefined'),name+' has no undefined content');
 assert.ok(!html.includes('NaN'),name+' has no NaN content');
 console.log('PASS',name);
}
vm.runInContext("S.data.entities[0].name='<script>alert(1)</script>';",context);
assert.ok(!vm.runInContext('entitiesPage()',context).includes('<script>alert(1)</script>'));
assert.ok(vm.runInContext('recordsView([{case_id:"X",investigation_notes:"<img src=x onerror=alert(1)>"}],"cases")',context).includes('&lt;img'));
console.log('PASS untrusted text escaping');
if(fixture.assessment){
 context.assessment=fixture.assessment;
 context.record=fixture.record;
 context.finding=fixture.finding;
 vm.runInContext('S.assessment=assessment;',context);
 const html=vm.runInContext('assessmentPage()',context);
 for(const label of ['Negative space','Peer benchmark','Why this attention index?','Recommended examiner sample','Open record & explanation'])assert.ok(html.includes(label),label);
 assert.ok(!html.includes('undefined')&&!html.includes('NaN'));
 for(const tab of ['explanation','records','provenance']){
  vm.runInContext(`S.modal={type:'record',data:record,selection:assessment.selection.records[0],plan:assessment.selection,tab:'${tab}'};`,context);
  const modal=vm.runInContext('renderModal()',context);
  assert.ok(modal.includes('Record evidence & explanation'));
  assert.ok(!modal.includes('undefined')&&!modal.includes('NaN'));
 }
 for(const tab of ['investigation','explanation','evidence','review','provenance']){
  vm.runInContext(`S.modal={type:'finding',data:finding,tab:'${tab}'};`,context);
  assert.ok(!vm.runInContext('renderModal()',context).includes('undefined'));
 }
 vm.runInContext("record.signals[0].explanations[0].observed.push('<img src=x onerror=alert(1)>');S.modal={type:'record',data:record};",context);
 assert.ok(!vm.runInContext('renderModal()',context).includes('<img src=x onerror=alert(1)>'));
 vm.runInContext("S.modal={type:'sample',name:'Atlas',data:assessment.independent_sample};",context);
 assert.ok(vm.runInContext('renderModal()',context).includes('Check what the detectors missed'));
 vm.runInContext("S.modal={type:'sample-observation',caseId:assessment.independent_sample.records[0].case_id,sample:assessment.independent_sample};",context);
 assert.ok(vm.runInContext('renderModal()',context).includes('sample-observation-form'));
 console.log('PASS assessment workflow, record tabs, finding tabs and explanation escaping');
}
