import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {validateInitData} from '../src/auth.js';
const token='fake:test-token';
function signed(userId, timestamp){
 const p=new URLSearchParams({auth_date:String(timestamp),user:JSON.stringify({id:userId,first_name:'Lumi'})});
 const data=[...p].sort((a,b)=>a[0].localeCompare(b[0])).map(([k,v])=>`${k}=${v}`).join('\n');
 const secret=createHmac('sha256','WebAppData').update(token).digest();
 p.set('hash',createHmac('sha256',secret).update(data).digest('hex'));
 return p.toString();
}
test('accepts authentic Telegram initData',async()=>{const now=1700000000;assert.equal((await validateInitData(signed(123,now),token,now)).id,'123')});
test('rejects tampered Telegram initData',async()=>{const now=1700000000,p=new URLSearchParams(signed(123,now));p.set('user',JSON.stringify({id:999}));await assert.rejects(validateInitData(p.toString(),token,now),/подпись/)});
test('rejects expired data',async()=>{await assert.rejects(validateInitData(signed(123,1700000000),'fake:test-token',1700007200),/недействительна/)});

test('accepts valid initData with token containing pasted whitespace',async()=>{
 const now=1700000000;
 assert.equal((await validateInitData(signed(123,now),'  '+token+'\r\n',now)).id,'123');
});
test('rejects mismatched token even after whitespace normalization',async()=>{
 const now=1700000000;
 await assert.rejects(validateInitData(signed(123,now),'other:token',now),/Неверная подпись/);
});

// Fixed cross-language fixture generated with Python hmac and urllib.parse.
const modern = "user=%7B%22id%22%3A123%2C%22first_name%22%3A%22%D0%9B%D1%8E%D0%BC%D0%B8+%2B+%26+%3D+%F0%9F%92%9C%22%2C%22photo_url%22%3A%22https%3A%2F%2Fexample.org%2Fa%3Fx%3D1%26y%3D2%22%7D&signature=test_signature-123_&auth_date=1700000000&query_id=AA%2B%26%3D&chat_instance=-123&start_param=room_123&future_field=new+value&hash=992e4a59a6f5914a6dd1e4e01ffed17d56da371f2e934306247ea5e6a0105ca1";
test('modern Telegram HMAC includes signature and unknown fields',async()=>{assert.equal((await validateInitData(modern,token,1700000000)).first_name,'Люми + & = 💜')});
test('rejects changed or removed signature',async()=>{for(const remove of [true,false]){const p=new URLSearchParams(modern);if(remove)p.delete('signature');else p.set('signature','changed');await assert.rejects(validateInitData(p.toString(),token,1700000000),/подпись/)}});
test('accepts reordered fields',async()=>{const p=new URLSearchParams([...new URLSearchParams(modern)].reverse());assert.equal((await validateInitData(p.toString(),token,1700000000)).id,'123')});
test('rejects duplicate fields',async()=>{await assert.rejects(validateInitData(modern+'&user=bad',token,1700000000),/недействительна/)});

test('rejects future auth beyond clock tolerance',async()=>{const now=1700000000;await assert.rejects(validateInitData(signed(123,now+31),token,now),/недействительна/);assert.equal((await validateInitData(signed(123,now+30),token,now)).id,'123')});

test('rejects ambiguous signed line delimiters and key names',async()=>{
 const now=1700000000;
 for(const [key,value] of [['extra','line\nnext=value'],['extra','line\rnext'],['extra=key','value']]){
  const p=new URLSearchParams(signed(123,now));p.delete('hash');p.set(key,value);
  const secret=createHmac('sha256','WebAppData').update(token).digest();
  p.set('hash',createHmac('sha256',secret).update([...p].sort((a,b)=>a[0]<b[0]?-1:1).map(([k,v])=>`${k}=${v}`).join('\n')).digest('hex'));
  await assert.rejects(validateInitData(p.toString(),token,now),/недействительна/);
 }
});

test('rejects malformed wire encoding even when forgiving parsing yields signed data',async()=>{
 const now=1700000000;
 for(const [encoded,broken] of [['%25ZZ','%ZZ'],['%EF%BF%BD','%FF']]){
  const p=new URLSearchParams(signed(123,now));p.delete('hash');p.set('extra',decodeURIComponent(encoded));
  const secret=createHmac('sha256','WebAppData').update(token).digest();
  p.set('hash',createHmac('sha256',secret).update([...p].sort((a,b)=>a[0]<b[0]?-1:1).map(([k,v])=>`${k}=${v}`).join('\n')).digest('hex'));
  assert.equal((await validateInitData(p.toString(),token,now)).id,'123');
  await assert.rejects(validateInitData(p.toString().replace(encoded,broken),token,now),/недействительна/);
 }
});
