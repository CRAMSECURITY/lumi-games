import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {validateInitData,AuthError} from '../src/auth.js';
import worker from '../src/worker.js';
const token='fixture:secret', t=1700000000;
function signed(user,at=t){const p=new URLSearchParams({auth_date:String(at),user:JSON.stringify(user)});const key=createHmac('sha256','WebAppData').update(token).digest();p.set('hash',createHmac('sha256',key).update([...p].sort().map(([k,v])=>`${k}=${v}`).join('\n')).digest('hex'));return p.toString()}
test('authentication rejects malformed and tampered inputs (deterministic fuzz)',async()=>{
 const raw=signed({id:42});assert.equal((await validateInitData(raw,token,t)).id,'42');
 const bad=[null,{},'', 'x'.repeat(8193),raw+'&user=bad',raw.replace('42','43'),signed({id:-1}),signed({id:1.5}),signed({id:'42'}),signed({id:42},t-3601),signed({id:42},t+31)];
 let x=12345;for(let i=0;i<256;i++){x=(Math.imul(x,1664525)+1013904223)>>>0;bad.push('hash='+x.toString(16)+'&user=%'+(x%256).toString(16));}
 for(const value of bad)await assert.rejects(validateInitData(value,token,t),AuthError);
});
test('anonymous requests cannot access protected routes',async()=>{
 const env={BOT_TOKEN:token,DB:{prepare(){throw new Error('unexpected database access')}},EDGE_RATE:{limit:async()=>({success:true})}};
 for(const route of ['room?code='+ 'a'.repeat(24),'morning','session','rooms','answer','join','unknown']){
 const r=await worker.fetch(new Request('https://example.test/api/'+route),env);assert.equal(r.status,401);assert.equal(r.headers.get('cache-control'),'no-store');}
});
test('API root cannot bypass edge policy',async()=>{const r=await worker.fetch(new Request('https://example.test/api'),{ASSETS:{fetch(){throw new Error('must not route to assets')}}});assert.equal(r.status,503)});
test('database failures are redacted and not mistaken for authentication failure',async()=>{
 const env={BOT_TOKEN:token,DB:{prepare(){throw new Error('Telegram database secret fixture')}},EDGE_RATE:{limit:async()=>({success:true})}};
 const r=await worker.fetch(new Request('https://example.test/api/session',{method:'POST',headers:{'x-telegram-init-data':signed({id:42},Math.floor(Date.now()/1000))}}),env);assert.equal(r.status,500);assert.doesNotMatch(await r.text(),/secret|database|stack/i);
});
