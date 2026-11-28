import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {createHmac} from 'node:crypto';
import {exchange,sessionUser} from '../src/session.js';
const t=1700000000, token='fixture:secret';
function signed(at=t){const p=new URLSearchParams({auth_date:String(at),user:JSON.stringify({id:42})});const key=createHmac('sha256','WebAppData').update(token).digest();p.set('hash',createHmac('sha256',key).update([...p].sort().map(([k,v])=>`${k}=${v}`).join('\n')).digest('hex'));return p.toString()}
function fixture(){const db=new DatabaseSync(':memory:');db.exec(readFileSync(new URL('../migrations/0003_sessions.sql',import.meta.url),'utf8'));db.exec(readFileSync(new URL('../migrations/0004_global_ban.sql',import.meta.url),'utf8'));db.exec(readFileSync(new URL('../migrations/0005_account_deletion.sql',import.meta.url),'utf8'));return {db,env:{BOT_TOKEN:token,DB:{prepare(sql){return {bind(...args){return {first:async()=>db.prepare(sql).get(...args)}}}}}}}}
test('parallel exchange permits exactly one login, including reordered initData',async()=>{const {db,env}=fixture();try{const raw=signed();const requests=await Promise.all(Array.from({length:16},(_,i)=>exchange(env,i%2?new URLSearchParams([...new URLSearchParams(raw)].reverse()).toString():raw,t)));assert.equal(requests.filter(Boolean).length,1);const session=requests.find(Boolean);assert.equal((await sessionUser(env,session.token,t)).id,'42');assert.notEqual(db.prepare('SELECT token_hash FROM web_sessions').get().token_hash,session.token)}finally{db.close()}});
test('session rejects expired, revoked and invalid tokens',async()=>{const {db,env}=fixture();try{const s=await exchange(env,signed(),t);assert.equal(await sessionUser(env,s.token,t+3600),null);assert.equal(await sessionUser(env,'a'.repeat(64),t),null);assert.equal(await sessionUser(env,'invalid',t),null);db.exec('UPDATE web_sessions SET user_id=NULL,token_hash=NULL,expires_at=0');assert.equal(await sessionUser(env,s.token,t),null);assert.equal(await exchange(env,signed(),t),null)}finally{db.close()}});
test('old launch data cannot create a session',async()=>{const {db,env}=fixture();try{await assert.rejects(exchange(env,signed(t-301),t),/заново/);assert.equal(db.prepare('SELECT COUNT(*) n FROM web_sessions').get().n,0)}finally{db.close()}});

test('deletion barrier rejects old launches and permits a fresh launch after expiry',async()=>{const {db,env}=fixture();try{db.prepare('INSERT INTO account_deletions VALUES(?,?,?)').run('42',t,t+120);assert.equal(await exchange(env,signed(t),t),null);assert.equal(await exchange(env,signed(t+120),t+121),null);assert.ok(await exchange(env,signed(t+121),t+121));}finally{db.close()}});
