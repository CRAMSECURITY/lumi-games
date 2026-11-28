import test from 'node:test';
import assert from 'node:assert/strict';
import {securityEvent,observeResponse} from '../src/threat-monitor.js';
import worker from '../src/worker.js';
test('only fixed security event fields are emitted',()=>{
 const events=[];const sink={warn:s=>events.push(JSON.parse(s))};
 for(const status of [200,400,401,403,413,429,500,503,404,'401','__proto__']) securityEvent(status,sink);
 assert.deepEqual(events.map(e=>e.status),[401,403,413,429,500,503]);
 for(const e of events) assert.deepEqual(Object.keys(e).sort(),['component','event','schema','status']);
});
test('logging failure does not alter response',()=>{
 const r=new Response('unchanged',{status:403});assert.equal(observeResponse(r,{warn(){throw Error('offline')}}),r);
});
test('rate-limit event excludes all request data',async()=>{
 const original=console.warn;const events=[];console.warn=s=>events.push(s);
 try{
 const r=await worker.fetch(new Request('https://example.test/api/private-secret?token=secret',{headers:{authorization:'Bearer secret','cf-connecting-ip':'192.0.2.1'}}),{EDGE_RATE:{limit:async()=>({success:false})}});
 assert.equal(r.status,429);assert.equal(events.length,1);assert.equal(JSON.parse(events[0]).event,'rate_limited');assert.doesNotMatch(events[0],/secret|192\.0\.2\.1/);
 }finally{console.warn=original;}
});
