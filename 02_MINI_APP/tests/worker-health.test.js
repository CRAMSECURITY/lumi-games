import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker from '../src/worker.js';
const request=()=>new Request('https://lumi-games.example/api/health');
const base=()=>({BOT_TOKEN:'fixture-token',LUMI_BAN_SYNC_KEY:'x'.repeat(32),EDGE_RATE:{limit:async()=>({success:true})}});
test('readiness verifies actual migrations and fails closed on missing schema',async()=>{
 const db=new DatabaseSync(':memory:');try{
 const env={...base(),DB:{prepare(sql){return {first:async()=>db.prepare(sql).get()}}}};
 for(const name of ['0001_init','0002_security','0003_sessions'])db.exec(readFileSync(new URL('../migrations/'+name+'.sql',import.meta.url),'utf8'));
 let r=await worker.fetch(request(),env);assert.equal(r.status,503);assert.equal((await r.json()).database,false);
 db.exec(readFileSync(new URL('../migrations/0004_global_ban.sql',import.meta.url),'utf8'));
 r=await worker.fetch(request(),env);assert.equal(r.status,503);
 db.exec(readFileSync(new URL('../migrations/0005_account_deletion.sql',import.meta.url),'utf8'));
 r=await worker.fetch(request(),env);assert.equal(r.status,200);assert.equal((await r.json()).ok,true);
 for(const key of ['BOT_TOKEN','LUMI_BAN_SYNC_KEY','EDGE_RATE']){r=await worker.fetch(request(),{...env,[key]:undefined});assert.equal(r.status,503);}
 }finally{db.close()}
});
test('readiness hides database errors and secrets',async()=>{
 const r=await worker.fetch(request(),{...base(),DB:{prepare(){throw Error('private database details')}}});
 assert.equal(r.status,503);const data=await r.text();assert.ok(!data.includes('private database details'));assert.ok(!data.includes('fixture-token'));assert.equal(JSON.parse(data).ok,false);
});
test('health is subject to edge rate limit before database access',async()=>{
 const r=await worker.fetch(request(),{...base(),EDGE_RATE:{limit:async()=>({success:false})},DB:{prepare(){assert.fail('unexpected DB access')}}});assert.equal(r.status,429);
});

test('readiness rejects existing tables with missing required columns',async()=>{
 const db=new DatabaseSync(':memory:');try{
 for(const name of ['0001_init','0002_security','0003_sessions','0004_global_ban','0005_account_deletion'])db.exec(readFileSync(new URL('../migrations/'+name+'.sql',import.meta.url),'utf8'));
 db.exec('ALTER TABLE web_sessions RENAME COLUMN expires_at TO wrong_column');
 const env={...base(),DB:{prepare(sql){return {first:async()=>db.prepare(sql).get()}}}};
 const r=await worker.fetch(request(),env);assert.equal(r.status,503);assert.equal((await r.json()).database,false);
 }finally{db.close()}
});
