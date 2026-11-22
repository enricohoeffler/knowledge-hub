// Exercise the actual client script against a small DOM and a controllable API.
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import assert from 'node:assert/strict';

const source = readFileSync('knowledge_hub/app.py', 'utf8');
const script = source.split('<script>')[1].split('</script>')[0].replaceAll('\\\\', '\\');
const elements = Object.fromEntries(['page','editor','msg','theme','dock','header-actions','editpanel','open','edit-title','time','save','restore','close'].map(id => [id, {
  id, value:'', textContent:'', hidden:id==='editpanel', disabled:false, dataset:{}, options:[],
  setAttribute(){}, replaceWith(next){ elements.editor=next; }, append(child){this.options.push(child);}
}]));
const files = { 'index.md':'# Start\n', 'rezepte/soljanka.md':'# Rezept\n', 'andere.md':'# Andere\n' };
const response = (ok, json) => ({ok, json:async()=>json});
let delayedFile = null;
let delayedSave = null;
const requests = [];
const mockFetch = async (url, opts) => {
  requests.push({url,opts});
  if (url==='api/pages') return response(true,{pages:Object.keys(files),built_at:'test'});
  if (url.startsWith('api/file?')) {
    const path=decodeURIComponent(url.split('=')[1]);
    if (delayedFile?.path===path) { await delayedFile.promise; }
    return response(true,{content:files[path],revision:'rev-'+path});
  }
  if(url==='api/save') {
    const data=JSON.parse(opts.body);
    if(delayedSave) await delayedSave.promise;
    files[data.path]=data.content;
    return response(true,{revision:'neu-'+data.path,message:'Gespeichert'});
  }
  throw Error('unexpected request: '+url);
};
const doc = {
  body:{dataset:{}},
  location:{href:'http://test/site/index.html'},
  addEventListener(type,handler){if(type==='click')this.onClick=handler},
  importNode(node){
    const ids=node.id==='dock'?['dock','editor','msg','editpanel','open','edit-title','time','save','restore','close']:['header-actions','theme'];
    const copies=Object.fromEntries(ids.map(id=>[id,{...elements[id],onclick:undefined}]));
    for(const id of ids)elements[id]=copies[id];
    copies[node.id].querySelector=s=>copies[s.slice(1)];
    return copies[node.id];
  },
  createElement(){return {value:'', textContent:'', dataset:{}, setAttribute(){},replaceWith(next){elements.editor=next;}}},
  querySelector(){return {append(){}}}
};
const frame = {contentDocument:doc,contentWindow:{location:{href:'http://test/site/index.html'}},src:''};
const document={documentElement:{dataset:{}},querySelector(s){return s==='iframe'?frame:elements[s.slice(1)]},createElement(){return {value:'',textContent:''}}};
let acceptNavigation=false,confirmations=0;
const context={document,location:{href:'http://test/'},URL,Array,decodeURIComponent,localStorage:{getItem(){return null},setItem(){}},fetch:mockFetch,confirm:()=>{confirmations++;return acceptNavigation}};
runInNewContext(script,context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const nav=async(path)=>{const next={...frame.contentDocument,__khGuard:false};frame.contentDocument=next;frame.contentWindow.location.href='http://test/site/'+path.replace(/\.md$/,'.html');next.location={href:frame.contentWindow.location.href};frame.onload();await tick()};
const linkClick=(href)=>{let prevented=false; const link={href,target:'',hasAttribute:()=>false}; frame.contentDocument.onClick({button:0,target:{closest:()=>link},preventDefault(){prevented=true},stopImmediatePropagation(){}});return prevented};
const click=async(id)=>{await elements[id].onclick();await tick()};
await tick(); await tick();
await click('open');
assert.equal(elements.editor.value,'# Start\n');
elements.editor.value='# Gespeichert\n';
await click('save');
assert.equal(files['index.md'],'# Gespeichert\n');
await nav('index.md');
assert.equal(typeof elements.save.onclick,'function','save remains bound after the view reloads');
await nav('rezepte/soljanka.md');
assert.equal(elements.editor.value,'# Rezept\n','clean editor follows navigation after save');
assert.match(elements['edit-title'].textContent,/soljanka/);
assert.equal(typeof elements.save.onclick,'function','save remains bound after a page change');
await click('close');
assert.equal(elements.editpanel.hidden,true,'close works on the new page');
await click('open');
assert.equal(elements.editor.value,'# Rezept\n','reopen loads the displayed page');
elements.editor.value='# Ungespeicherter Entwurf\n';
assert.equal(linkClick('http://test/site/andere.html'),true,'dirty navigation is intercepted');
assert.equal(confirmations,1,'dirty navigation asks before leaving');
assert.equal(elements.editor.value,'# Ungespeicherter Entwurf\n','cancel keeps the draft');
acceptNavigation=true;
assert.equal(linkClick('http://test/site/andere.html'),true);
assert.equal(frame.src,'http://test/site/andere.html','confirmation navigates to the chosen page');
assert.equal(elements.editor.value,'','confirmed discard clears previous draft');
await nav('andere.md');
assert.equal(elements.editpanel.hidden,true,'confirmed discard resets editor');
await click('open');
assert.equal(elements.editor.value,'# Andere\n','editing opens the selected file');
await nav('rezepte/soljanka.md');
elements.editor.value='# Ungespeicherter Entwurf\n';
await nav('andere.md');
assert.equal(elements.editor.value,'# Ungespeicherter Entwurf\n','unsaved draft survives navigation');
const saves=requests.filter(r=>r.url==='api/save').length;
await click('save');
assert.equal(requests.filter(r=>r.url==='api/save').length,saves,'cannot save draft to a different page');
await nav('rezepte/soljanka.md');
assert.equal(elements.editor.value,'# Ungespeicherter Entwurf\n');
await click('save');
assert.equal(files['rezepte/soljanka.md'],'# Ungespeicherter Entwurf\n');
let release; delayedFile={path:'andere.md',promise:new Promise(r=>{release=r})};
await nav('andere.md');
elements.editor.value='# Während Laden geändert\n';
release(); await tick(); await tick();
assert.equal(elements.editor.value,'# Während Laden geändert\n','typing during a delayed load is retained');
delayedFile=null;
await nav('rezepte/soljanka.md');
let finishSave; delayedSave={promise:new Promise(r=>{finishSave=r})};
const pendingSave=elements.save.onclick();
await tick();
elements.editor.value='# Während Speichern weitergeschrieben\n';
await nav('andere.md');
finishSave(); await pendingSave; await tick();
assert.equal(files['rezepte/soljanka.md'],'# Während Laden geändert\n');
assert.equal(elements.editor.value,'# Während Speichern weitergeschrieben\n','typing during a delayed save is retained');
assert.match(elements['edit-title'].textContent,/soljanka/,'draft stays attached to original file');
console.log('PASS: save and navigate, unsaved drafts, wrong-page guard, delayed load and save');
