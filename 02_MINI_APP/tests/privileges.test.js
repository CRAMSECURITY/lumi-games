import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,readdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import worker from '../src/worker.js';
test('privilege consent, ownership, expiry, single redemption and deletion',async()=>{
 const db=new DatabaseSync(':memory:');try{
 for(const name of readdirSync(new URL('../migrations/',import.meta.url)).sort())db.exec(readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8'));
 const t=Math.floor(Date.now()/1000), tokens=['a'.repeat(64),'b'.repeat(64),'c'.repeat(64)];
 tokens.forEach((v,i)=>db.prepare('INSERT INTO web_sessions(init_hash,token_hash,user_id,expires_at,retain_until) VALUES(?,?,?,?,?)').run('init'+i,createHash('sha256').update(v).digest('hex'),String(i+1),t+3600,t+3600));
 const env={BOT_TOKEN:'dummy',LUMI_BAN_SYNC_KEY:'a'.repeat(32),LUMI_PRIVILEGES:'1',LUMI_EVENT_ORGANIZER:'1',LUMI_EVENT_REGISTRATION:'1',LUMI_BUSINESS_MODERATION:'1',LUMI_BUSINESS_MODERATOR_IDS:'2',EDGE_RATE:{limit:async()=>({success:true})},DB:{prepare(sql){return{bind(...args){const stmt=db.prepare(sql);return{first:async()=>stmt.get(...args),all:async()=>({results:stmt.all(...args)}),run:async()=>({meta:{changes:Number(stmt.run(...args).changes)}})}}}}}};
 async function call(i,path,body,status=200){const res=await worker.fetch(new Request('https://example.test/api/privileges/'+path,{method:body===undefined?'GET':'POST',headers:{'x-lumi-session':tokens[i]||''},body:body===undefined?undefined:JSON.stringify(body)}),env);assert.equal(res.status,status);return res.json()}
 const add=(id,start,end,enabled)=>db.prepare('INSERT INTO partner_privileges VALUES(?,?,?,?,?,?,?,?)').run(id,'1','Test','Test terms','Berlin',start,end,enabled);
 add('active',t-10,t+3600,1);add('expired',t-100,t-1,1);add('draft',t-10,t+3600,0);
 await call(9,'list',undefined,401);assert.equal((await call(1,'list')).offers.length,1);await call(1,'claim',{id:'active'},400);await call(1,'claim',{id:'expired',consent:true},409);await call(0,'claim',{id:'active',consent:true},409);
 const {code}=await call(1,'claim',{id:'active',consent:true});assert.match(code,/^[a-f0-9]{32}$/);assert.equal((await call(1,'claim',{id:'active',consent:true})).code,code);assert.equal((await call(2,'list')).offers[0].code,null);await call(2,'redeem',{code,consent:true},409);await call(0,'redeem',{code,consent:true});await call(0,'redeem',{code,consent:true},409);assert.ok((await call(1,'list')).offers[0].redeemed_at);db.prepare('INSERT INTO account_deletions VALUES(?,?,?)').run('2',t,t+120);assert.equal(db.prepare('SELECT count(*) n FROM privilege_codes').get().n,0);env.LUMI_PARTNER_STUDIO='1';env.LUMI_PARTNER_IDS='1';await call(2,'studio-list',undefined,403);const draft=await call(0,'studio-create',{title:'New',terms:'Terms',city:'Berlin',starts_at:t+60,ends_at:t+3600,consent:true});assert.equal(draft.enabled,false);assert.equal((await call(0,'studio-list')).offers.length,4);await call(0,'studio-pause',{id:'active',consent:true});assert.equal((await call(2,'list')).offers.length,0);env.LUMI_PARTNER_STUDIO='0';await call(0,'studio-list',undefined,404);env.LUMI_PRIVILEGES='0';await call(1,'list',undefined,404);
 }finally{db.close()}
});
