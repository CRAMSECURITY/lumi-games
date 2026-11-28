import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../public/microinteractions.js',import.meta.url),'utf8');
function setup(){let handler, count=0,time=0;const state={reduced:false,disabled:false};const target={closest:()=>state.disabled?target:null};const doc={hidden:false,addEventListener:(name,fn)=>{assert.equal(name,'click');handler=fn}};const win={matchMedia:()=>({matches:state.reduced}),Telegram:{WebApp:{HapticFeedback:{selectionChanged:()=>count++}}}};vm.runInNewContext(source,{document:doc,window:win,performance:{now:()=>time}});return {state,doc,win,get count(){return count},advance:()=>time+=101,click:(extra={})=>handler({isTrusted:true,defaultPrevented:false,detail:1,target:{closest:()=>target},...extra})}}
test('microinteractions limit repeated tactile feedback',()=>{const t=setup();t.click();t.click();assert.equal(t.count,1);t.advance();t.click();assert.equal(t.count,2)});
test('microinteractions ignore canceled, synthetic, keyboard and disabled clicks',()=>{const t=setup();t.click({defaultPrevented:true});t.click({isTrusted:false});t.click({detail:0});t.state.disabled=true;t.click();assert.equal(t.count,0)});
test('microinteractions respect reduced motion, background and absent Telegram',()=>{const t=setup();t.state.reduced=true;t.click();t.state.reduced=false;t.doc.hidden=true;t.click();t.doc.hidden=false;delete t.win.Telegram;t.click();assert.equal(t.count,0)});
