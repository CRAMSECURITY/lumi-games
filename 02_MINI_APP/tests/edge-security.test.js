import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';
const req=()=>new Request('https://example.test/api/session',{headers:{'cf-connecting-ip':'192.0.2.1'}});
test('missing edge limiter fails closed',async()=>assert.equal((await worker.fetch(req(),{})).status,503));
test('edge denial precedes auth and database',async()=>{
 let key; const res=await worker.fetch(req(),{EDGE_RATE:{limit:async x=>{key=x.key;return {success:false}}}});
 assert.equal(key,'api:192.0.2.1');assert.equal(res.status,429);assert.equal(res.headers.get('retry-after'),'60');
});
test('allowed edge request still requires Telegram authentication',async()=>{
 const res=await worker.fetch(req(),{EDGE_RATE:{limit:async()=>({success:true})},DB:{},BOT_TOKEN:'fixture'});
 assert.equal(res.status,401);
});
