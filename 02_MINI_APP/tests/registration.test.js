import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,readdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import worker from '../src/worker.js';
test('registration capacity, consent, isolation, cancellation and deletion',async()=>{
 const db=new DatabaseSync(':memory:');try{
 for(const name of readdirSync(new URL('../migrations/',import.meta.url)).sort())db.exec(readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8'));
 const t=Math.floor(Date.now()/1000), tokens=['a'.repeat(64),'b'.repeat(64),'c'.repeat(64)];
 tokens.forEach((v,i)=>db.prepare('INSERT INTO web_sessions(init_hash,token_hash,user_id,expires_at,retain_until) VALUES(?,?,?,?,?)').run('init'+i,createHash('sha256').update(v).digest('hex'),String(i+1),t+3600,t+3600));
 const env={BOT_TOKEN:'dummy',LUMI_BAN_SYNC_KEY:'a'.repeat(32),LUMI_EVENT_ORGANIZER:'1',LUMI_EVENT_REGISTRATION:'1',LUMI_BUSINESS_MODERATION:'1',LUMI_BUSINESS_MODERATOR_IDS:'2',EDGE_RATE:{limit:async()=>({success:true})},DB:{prepare(sql){return{bind(...args){const stmt=db.prepare(sql);return{first:async()=>stmt.get(...args),all:async()=>({results:stmt.all(...args)}),run:async()=>({meta:{changes:Number(stmt.run(...args).changes)}})}}}}}};
 async function call(i,path,body,status=200){const res=await worker.fetch(new Request('https://example.test/api/events/'+path,{method:body===undefined?'GET':'POST',headers:{'x-lumi-session':tokens[i]||''},body:body===undefined?undefined:JSON.stringify(body)}),env);assert.equal(res.status,status);return res.json()}
 const event={capacity:1,title:'Meetup',city:'Frankfurt',venue:'Public hall',kind:'network',starts_at:t+3600,description:'Business meeting',consent:true};
 await call(9,'list',undefined,401);await call(0,'submit',{...event,consent:false},400);await call(0,'submit',{...event,description:'https://example.test'},400);await call(0,'submit',{...event,starts_at:t-1},400);
 const {id}=await call(0,'submit',event);assert.deepEqual((await call(1,'list')).events,[]);assert.deepEqual((await call(1,'mine')).events,[]);await call(1,'cancel',{id},409);await call(0,'moderation/decide',{id,state:'approved'},403);assert.equal((await call(1,'moderation/list')).events.length,1);await call(1,'moderation/decide',{id,state:'approved'});const rows=(await call(1,'list')).events;assert.equal(rows.length,1);assert.ok(!('owner' in rows[0]));await call(1,'moderation/decide',{id,state:'rejected'},409);await call(0,'registration/join',{id,consent:true},409);await call(1,'registration/join',{id},400);await call(1,'registration/join',{id,consent:true});await call(1,'registration/join',{id,consent:true},409);await call(2,'registration/join',{id,consent:true},409);assert.equal((await call(2,'registration/list')).events[0].remaining,0);assert.equal((await call(1,'registration/mine')).events[0].joined,1);await call(2,'registration/leave',{id});assert.equal((await call(1,'registration/mine')).events.length,1);await call(1,'registration/leave',{id});await call(2,'registration/join',{id,consent:true});await call(0,'cancel',{id});assert.equal((await call(2,'registration/mine')).events[0].state,'cancelled');await call(1,'registration/join',{id,consent:true},409);assert.deepEqual((await call(1,'list')).events,[]);
 for(let i=0;i<4;i++)await call(0,'submit',event);await call(0,'submit',event,409);db.prepare('INSERT INTO account_deletions VALUES(?,?,?)').run('1',t,t+120);assert.equal(db.prepare('SELECT count(*) n FROM organizer_events').get().n,0);assert.equal(db.prepare('SELECT count(*) n FROM event_registrations').get().n,0);env.LUMI_EVENT_ORGANIZER='0';await call(1,'list',undefined,404);
 }finally{db.close()}
});
