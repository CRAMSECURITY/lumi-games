import test from 'node:test';
import assert from 'node:assert/strict';
import worker,{readBoundedBody} from '../src/worker.js';
const request=body=>new Request('https://example.test/api/join',{method:'POST',body,duplex:'half'});
test('oversize declaration rejected before database access',async()=>{
 let db=0;const r=await worker.fetch(new Request('https://example.test/api/join',{method:'POST',headers:{'content-length':'4097'},body:'{}'}),{EDGE_RATE:{limit:async()=>({success:true})},get DB(){db++;throw Error('unexpected DB access')}});
 assert.equal(r.status,413);assert.equal(db,0);
});
test('bounded reader accepts fragmented body at limit',async()=>{
 const body=new ReadableStream({start(c){for(let i=0;i<4096;i++)c.enqueue(Uint8Array.of(65));c.close();}});
 const bytes=await readBoundedBody(request(body));assert.equal(bytes.length,4096);assert.ok(bytes.every(x=>x===65));
});
test('oversize stream rejects even if cancellation never completes',async()=>{
 const body=new ReadableStream({start(c){c.enqueue(new Uint8Array(4097));},cancel(){return new Promise(()=>{});}});
 await assert.rejects(readBoundedBody(request(body)),e=>e.status===413);
});
test('stalled stream hits deadline and is cancelled',async()=>{
 let cancelled=false;const body=new ReadableStream({cancel(){cancelled=true;}});
 await assert.rejects(readBoundedBody(request(body),20),e=>e.status===408);assert.equal(cancelled,true);
});
test('excessive empty fragments are rejected',async()=>{
 const body=new ReadableStream({pull(c){c.enqueue(new Uint8Array(0));}});
 await assert.rejects(readBoundedBody(request(body)),e=>e.status===413);
});
