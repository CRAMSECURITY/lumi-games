import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,readdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import worker from '../src/worker.js';
import {validateProfile} from '../src/business.js';
const profile={name:'Alex',role:'founder',sector:'IT',skills:'Design',goal:'partners',consent:true};
test('business profile validation rejects missing consent, contacts, invalid types and extra fields',()=>{assert.ok(validateProfile(profile));for(const bad of [{consent:false},{name:'@handle'},{skills:'https://test.example'},{role:'__proto__'},{sector:123},{name:'a'.repeat(61)},{user_id:'2'},{skills:'\u202eabc'}])assert.equal(validateProfile({...profile,...bad}),null);});
test('business directory consent, moderation, filters, ownership, bans, deletion and feature gate',async()=>{
 const db=new DatabaseSync(':memory:');try{
 for(const name of readdirSync(new URL('../migrations/',import.meta.url)).sort())db.exec(readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8'));
 const t=Math.floor(Date.now()/1000), tokens=['a'.repeat(64),'b'.repeat(64)];
 tokens.forEach((v,i)=>db.prepare('INSERT INTO web_sessions(init_hash,token_hash,user_id,expires_at,retain_until) VALUES(?,?,?,?,?)').run('init'+i,createHash('sha256').update(v).digest('hex'),String(i+1),t+3600,t+3600));
 const env={BOT_TOKEN:'dummy',LUMI_BAN_SYNC_KEY:'a'.repeat(32),LUMI_BUSINESS_DIRECTORY:'1',EDGE_RATE:{limit:async()=>({success:true})},DB:{prepare(sql){return{bind(...args){const stmt=db.prepare(sql);return{first:async()=>stmt.get(...args),all:async()=>({results:stmt.all(...args)}),run:async()=>({meta:{changes:Number(stmt.run(...args).changes)}})}}}}}};
 async function call(i,path,body,status=200){const res=await worker.fetch(new Request('https://example.test/api/business/'+path,{method:body===undefined?'GET':'POST',headers:{'x-lumi-session':tokens[i]||''},body:body===undefined?undefined:JSON.stringify(body)}),env);assert.equal(res.status,status);return res.json()}
 await call(9,'list',undefined,401);await call(0,'submit',{...profile,consent:false},400);await call(0,'submit',profile);assert.deepEqual((await call(1,'list')).profiles,[]);assert.equal((await call(0,'me')).profile.approved,0);assert.equal((await call(1,'me')).profile,null);
 db.exec('UPDATE business_profiles SET approved=1');const visible=(await call(1,'list?goal=partners')).profiles;assert.equal(visible.length,1);assert.equal(visible[0].name,'Alex');assert.ok(!('user_id' in visible[0]));assert.ok(!('revision' in visible[0]));assert.deepEqual((await call(1,'list?goal=startup')).profiles,[]);
 await call(1,'withdraw',{});assert.equal((await call(1,'list')).profiles.length,1);
 db.prepare('INSERT INTO global_bans VALUES(?,?,?)').run('1',1,-1);assert.deepEqual((await call(1,'list')).profiles,[]);await call(0,'me',undefined,403);db.exec('DELETE FROM global_bans');
 await call(0,'submit',{...profile,name:'New'});assert.deepEqual((await call(1,'list')).profiles,[]);await call(0,'withdraw',{});assert.equal((await call(0,'me')).profile,null);
 await call(0,'submit',profile);db.prepare('INSERT INTO account_deletions VALUES(?,?,?)').run('1',t,t+120);assert.equal(db.prepare('SELECT count(*) n FROM business_profiles').get().n,0);
 env.LUMI_BUSINESS_DIRECTORY='0';await call(1,'list',undefined,404);
 }finally{db.close()}
});

test('business connect mutual consent, ownership, cancellation and profile withdrawal',async()=>{
 const db=new DatabaseSync(':memory:');try{
 for(const name of readdirSync(new URL('../migrations/',import.meta.url)).sort())db.exec(readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8'));
 const t=Math.floor(Date.now()/1000), tokens=['a'.repeat(64),'b'.repeat(64),'c'.repeat(64)];
 tokens.forEach((v,i)=>db.prepare('INSERT INTO web_sessions(init_hash,token_hash,user_id,expires_at,retain_until) VALUES(?,?,?,?,?)').run('init'+i,createHash('sha256').update(v).digest('hex'),String(i+1),t+3600,t+3600));
 const env={BOT_TOKEN:'dummy',LUMI_BAN_SYNC_KEY:'a'.repeat(32),LUMI_BUSINESS_DIRECTORY:'1',LUMI_BUSINESS_CONNECT:'1',EDGE_RATE:{limit:async()=>({success:true})},DB:{prepare(sql){return{bind(...args){const stmt=db.prepare(sql);return{first:async()=>stmt.get(...args),all:async()=>({results:stmt.all(...args)}),run:async()=>({meta:{changes:Number(stmt.run(...args).changes)}})}}}}}};
 async function call(i,path,body,status=200){const res=await worker.fetch(new Request('https://example.test/api/business/'+path,{method:body===undefined?'GET':'POST',headers:{'x-lumi-session':tokens[i]||''},body:body===undefined?undefined:JSON.stringify(body)}),env);assert.equal(res.status,status);return res.json()}
 await call(0,'submit',profile);await call(1,'submit',{...profile,name:'Beta'});await call(2,'submit',{...profile,name:'Third'});
 db.exec('UPDATE business_profiles SET approved=1');
 const card=(await call(0,'list')).profiles.find(p=>p.name==='Beta').card_id;
 await call(0,'connect/send',{card_id:card});await call(0,'connect/send',{card_id:card},409);
 const inv=(await call(1,'connect/list')).invites[0];assert.equal(inv.direction,'incoming');assert.equal(inv.state,'pending');
 assert.deepEqual((await call(2,'connect/list')).invites,[]);
 await call(2,'connect/decide',{id:inv.id,state:'accepted'},409);await call(0,'connect/decide',{id:inv.id,state:'accepted'},409);
 await call(1,'connect/decide',{id:inv.id,state:'accepted'});assert.equal((await call(0,'connect/list')).invites[0].state,'accepted');
 await call(0,'connect/decide',{id:inv.id,state:'cancelled'});assert.equal((await call(1,'connect/list')).invites[0].state,'cancelled');
 await call(1,'withdraw',{});assert.deepEqual((await call(0,'connect/list')).invites,[]);await call(0,'connect/send',{card_id:card},409);
 env.LUMI_BUSINESS_CONNECT='0';await call(0,'connect/list',undefined,404);
 }finally{db.close()}
});

test('business safety history survives edits, reports and pair blocks',async()=>{
 const db=new DatabaseSync(':memory:');try{
 for(const name of readdirSync(new URL('../migrations/',import.meta.url)).sort())db.exec(readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8'));
 const t=Math.floor(Date.now()/1000), tokens=['a'.repeat(64),'b'.repeat(64),'c'.repeat(64)];
 tokens.forEach((v,i)=>db.prepare('INSERT INTO web_sessions(init_hash,token_hash,user_id,expires_at,retain_until) VALUES(?,?,?,?,?)').run('init'+i,createHash('sha256').update(v).digest('hex'),String(i+1),t+3600,t+3600));
 const env={BOT_TOKEN:'dummy',LUMI_BAN_SYNC_KEY:'a'.repeat(32),LUMI_BUSINESS_DIRECTORY:'1',LUMI_BUSINESS_CONNECT:'1',EDGE_RATE:{limit:async()=>({success:true})},DB:{prepare(sql){return{bind(...args){const stmt=db.prepare(sql);return{first:async()=>stmt.get(...args),all:async()=>({results:stmt.all(...args)}),run:async()=>({meta:{changes:Number(stmt.run(...args).changes)}})}}}}}};
 async function call(i,path,body,status=200){const res=await worker.fetch(new Request('https://example.test/api/business/'+path,{method:body===undefined?'GET':'POST',headers:{'x-lumi-session':tokens[i]||''},body:body===undefined?undefined:JSON.stringify(body)}),env);assert.equal(res.status,status);return res.json()}
 await call(0,'submit',profile);await call(1,'submit',{...profile,name:'Beta'});await call(2,'submit',{...profile,name:'Third'});
 db.exec('UPDATE business_profiles SET approved=1');
 const card=(await call(0,'list')).profiles.find(p=>p.name==='Beta').card_id;
 await call(0,'connect/send',{card_id:card});
 const inv=(await call(1,'connect/list')).invites[0];
 await call(2,'connect/report',{id:inv.id,reason:'spam'},409);await call(2,'connect/block',{id:inv.id},409);
 await call(1,'connect/report',{id:inv.id,reason:'spam'});await call(1,'connect/report',{id:inv.id,reason:'spam'},409);
 await call(1,'connect/block',{id:inv.id});assert.deepEqual((await call(0,'connect/list')).invites,[]);await call(0,'connect/send',{card_id:card},409);
 const other=(await call(0,'list')).profiles.find(p=>p.name==='Third').card_id;
 for(let j=0;j<9;j++){await call(0,'submit',profile);db.exec('UPDATE business_profiles SET approved=1');await call(0,'connect/send',{card_id:other});}
 await call(0,'submit',profile);db.exec('UPDATE business_profiles SET approved=1');await call(0,'connect/send',{card_id:other},409);
 assert.equal(db.prepare("SELECT count(*) n FROM business_invite_history WHERE sender='1'").get().n,10);
 db.prepare('INSERT INTO account_deletions VALUES(?,?,?)').run('1',t,t+120);
 for(const table of ['business_invite_history','business_blocks','business_reports'])assert.equal(db.prepare('SELECT count(*) n FROM '+table).get().n,0);
 }finally{db.close()}
});

test('moderation role isolation, revision checks and rejection',async()=>{
 const db=new DatabaseSync(':memory:');try{
 for(const name of readdirSync(new URL('../migrations/',import.meta.url)).sort())db.exec(readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8'));
 const t=Math.floor(Date.now()/1000), tokens=['a'.repeat(64),'b'.repeat(64)];
 tokens.forEach((v,i)=>db.prepare('INSERT INTO web_sessions(init_hash,token_hash,user_id,expires_at,retain_until) VALUES(?,?,?,?,?)').run('init'+i,createHash('sha256').update(v).digest('hex'),String(i+1),t+3600,t+3600));
 const env={BOT_TOKEN:'dummy',LUMI_BAN_SYNC_KEY:'a'.repeat(32),LUMI_BUSINESS_DIRECTORY:'1',EDGE_RATE:{limit:async()=>({success:true})},DB:{prepare(sql){return{bind(...args){const stmt=db.prepare(sql);return{first:async()=>stmt.get(...args),all:async()=>({results:stmt.all(...args)}),run:async()=>({meta:{changes:Number(stmt.run(...args).changes)}})}}}}}};
 async function call(i,path,body,status=200){const res=await worker.fetch(new Request('https://example.test/api/business/'+path,{method:body===undefined?'GET':'POST',headers:{'x-lumi-session':tokens[i]||''},body:body===undefined?undefined:JSON.stringify(body)}),env);assert.equal(res.status,status);return res.json()}
 env.LUMI_BUSINESS_MODERATION='1';env.LUMI_BUSINESS_MODERATOR_IDS='2';
 await call(0,'submit',profile);await call(0,'moderation/queue',undefined,403);await call(9,'moderation/queue',undefined,401);
 const old=(await call(1,'moderation/queue')).profiles[0].revision;
 await call(0,'submit',{...profile,name:'Edited'});await call(1,'moderation/decide',{revision:old,decision:'approved'},409);
 const current=(await call(1,'moderation/queue')).profiles[0].revision;
 await call(1,'moderation/decide',{revision:current,decision:'rejected'});assert.equal((await call(0,'me')).profile.moderation_decision,'rejected');assert.deepEqual((await call(1,'moderation/queue')).profiles,[]);
 await call(0,'submit',profile);const next=(await call(1,'moderation/queue')).profiles[0].revision;await call(1,'moderation/decide',{revision:next,decision:'approved'});assert.equal((await call(0,'me')).profile.approved,1);
 await call(1,'moderation/decide',{revision:next,decision:'rejected'},409);
 await call(1,'submit',profile);const self=db.prepare("SELECT revision FROM business_profiles WHERE user_id='2'").get().revision;await call(1,'moderation/decide',{revision:self,decision:'approved'},409);
 db.prepare('INSERT INTO business_reports(invite_id,reporter,reported,reason,created_at) VALUES(?,?,?,?,?)').run(next,'1','3','spam',t);
 assert.equal((await call(1,'moderation/queue')).reports.length,1);await call(0,'moderation/review',{invite_id:next,reporter:'1'},403);await call(1,'moderation/review',{invite_id:next,reporter:'1'});assert.equal((await call(1,'moderation/queue')).reports.length,0);await call(1,'moderation/review',{invite_id:next,reporter:'1'},409);
 env.LUMI_BUSINESS_MODERATION='0';await call(1,'moderation/queue',undefined,404);
 }finally{db.close()}
});
