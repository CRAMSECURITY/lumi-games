import test from 'node:test';
import assert from 'node:assert/strict';
import worker,{readBoundedBody} from '../src/worker.js';
const req=()=>new Request('https://example.test/api/session');
const secret='PRIVATE_FIXTURE_SECRET';
test('limiter outage and invalid responses fail closed without DB access',async()=>{
 for(const limit of [async()=>{throw Error(secret)},async()=>null,async()=>({success:'true'})]){
  let accessed=false;const r=await worker.fetch(req(),{EDGE_RATE:{limit},get DB(){accessed=true;throw Error(secret)}});
  assert.equal(r.status,503);assert.equal(accessed,false);assert.ok(!(await r.text()).includes(secret));assert.equal(r.headers.get('cache-control'),'no-store');
 }
});
test('missing database or token returns generic unavailable response',async()=>{
 const edge={EDGE_RATE:{limit:async()=>({success:true})}};
 for(const env of [edge,{...edge,DB:{},BOT_TOKEN:'  '}]){
  const r=await worker.fetch(req(),env);assert.equal(r.status,503);assert.ok(!/BOT_TOKEN|D1/.test(await r.text()));
 }
});
test('asynchronous asset rejection is caught and sanitized',async()=>{
 const r=await worker.fetch(new Request('https://example.test/'),{ASSETS:{fetch:async()=>{throw Error(secret)}}});
 assert.equal(r.status,500);assert.ok(!(await r.text()).includes(secret));
});
test('broken input stream is rejected as a client error',async()=>{
 const body=new ReadableStream({pull(c){c.error(Error(secret));}});
 const req=new Request('https://example.test/api/join',{method:'POST',body,duplex:'half'});
 await assert.rejects(readBoundedBody(req),e=>e.status===400&&!e.message.includes(secret));
});
test('scheduled cleanup failure remains visible but sanitized',async()=>{
 let task;await worker.scheduled({scheduledTime:Date.now()},{DB:{prepare(){throw Error(secret)}}},{waitUntil(p){task=p;}});
 await assert.rejects(task,e=>e.message==='LUMI scheduled cleanup failed');
});
