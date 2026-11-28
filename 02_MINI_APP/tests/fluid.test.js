import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../public/fluid.js',import.meta.url),'utf8');
function setup(supported=true){const states=new Map(), listeners={}; const card={classList:{toggle:(k,v)=>states.set(k,v)}};const doc={hidden:true,documentElement:card,querySelectorAll:()=>[card],addEventListener:(k,v)=>listeners[k]=v};let callback,observed=0;const ctx={document:doc};if(supported)ctx.IntersectionObserver=class{constructor(cb){callback=cb}observe(){observed++}};vm.runInNewContext(source,ctx);return {states,doc,listeners,card,get observed(){return observed},emit:v=>callback([{target:card,isIntersecting:v}])}}
test('fluid pauses offscreen cards and resumes visible cards',()=>{const t=setup();assert.equal(t.observed,1);t.emit(false);assert.equal(t.states.get('lumi-offscreen'),true);t.emit(true);assert.equal(t.states.get('lumi-offscreen'),false);assert.equal(t.states.get('lumi-background'),true);t.doc.hidden=false;t.listeners.visibilitychange();assert.equal(t.states.get('lumi-background'),false)});
test('fluid preserves background fallback without IntersectionObserver',()=>{const t=setup(false);assert.equal(t.states.get('lumi-background'),true);assert.equal(t.observed,0)});
