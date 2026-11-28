import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {createHmac} from 'node:crypto';
import worker from '../src/worker.js';
import {getPuzzle} from '../src/game.js';
const token='test:dummy';
function auth(id){const p=new URLSearchParams({auth_date:String(Math.floor(Date.now()/1000)),signature:'fixture',user:JSON.stringify({id})});const key=createHmac('sha256','WebAppData').update(token).digest();p.set('hash',createHmac('sha256',key).update([...p].sort().map(([k,v])=>`${k}=${v}`).join('\n')).digest('hex'));return p.toString()}
test('two players, five rounds, authorization, reconnect and scores using SQLite',async()=>{
 const db=new DatabaseSync(':memory:');try{
 db.exec(readFileSync(new URL('../migrations/0001_init.sql',import.meta.url),'utf8'));
 db.exec(readFileSync(new URL('../migrations/0002_security.sql',import.meta.url),'utf8'));
 db.exec(readFileSync(new URL('../migrations/0003_sessions.sql',import.meta.url),'utf8'));db.exec(readFileSync(new URL('../migrations/0004_global_ban.sql',import.meta.url),'utf8'));db.exec(readFileSync(new URL('../migrations/0005_account_deletion.sql',import.meta.url),'utf8'));
 let beforeRun=null,beforeAll=null;
 const env={LUMI_BAN_SYNC_KEY:'a'.repeat(32),EDGE_RATE:{limit:async()=>({success:true})},BOT_TOKEN:token,DB:{async batch(stmts){db.exec('BEGIN');try{for(const stmt of stmts)await stmt.run();db.exec('COMMIT')}catch(e){db.exec('ROLLBACK');throw e}},prepare(sql){return {bind(...args){const stmt=db.prepare(sql);return {first:async()=>stmt.get(...args),all:async()=>{if(beforeAll)await beforeAll(sql);return {results:stmt.all(...args)}},run:async()=>{if(beforeRun)await beforeRun(sql);return {meta:{changes:Number(stmt.run(...args).changes)}}}}}}}}};
 const sessions=new Map();
 async function login(id){if(!sessions.has(id)){const raw=auth(id);const req=()=>new Request('https://example.test/api/session',{method:'POST',headers:{'x-telegram-init-data':raw}});const res=await worker.fetch(req(),env);assert.equal(res.status,200);const data=await res.json();assert.match(data.token,/^[a-f0-9]{64}$/);assert.equal((await worker.fetch(req(),env)).status,401);sessions.set(id,data.token)}return sessions.get(id)}
 async function call(id,path,body,status=200){const res=await worker.fetch(new Request('https://example.test/api/'+path,{method:body===undefined?'GET':'POST',headers:{'x-lumi-session':await login(id)},body:body===undefined?undefined:JSON.stringify(body)}),env);const data=await res.json();assert.equal(res.status,status,JSON.stringify(data));return data}
 assert.deepEqual(await call(1,'session'),{authenticated:true});
 db.prepare('INSERT INTO global_bans VALUES(?,?,?)').run('1',1,-1);
 await call(1,'session',undefined,403);
 db.prepare('UPDATE global_bans SET expires=0 WHERE user_id=?').run('1');
 await call(1,'session');
 for(let i=0;i<120;i++)await call(99,'session');
 await call(99,'session',undefined,429);
 await call(98,'session');
 const {room}=await call(1,'rooms',{});const code=room.id;assert.equal(room.status,'waiting');
 await call(3,'room?code='+code,undefined,403);
 await call(3,'answer',{code,round:0,choice:0},403);
 await call(3,'join',{code:"' OR 1=1 --"},400);
 await call(3,'room?code='+encodeURIComponent("' OR 1=1 --"),undefined,400);
 assert.equal(db.prepare('SELECT COUNT(*) n FROM rooms').get().n,1);
 assert.equal((await call(2,'join',{code})).room.status,'playing');await call(3,'join',{code},409);
 for(let round=0;round<5;round++){const choice=getPuzzle(code,round).answer;const a=await call(1,'answer',{code,round,choice});assert.equal(a.room.answered,true);const opponent=(await call(2,'room?code='+code)).room;assert.equal(opponent.players.host.score,a.room.players.host.score);if(round===0)assert.equal(opponent.players.host.score,0);await call(1,'answer',{code,round,choice},409);await call(2,'answer',{code,round,choice:(choice+1)%4});}
 const end=(await call(1,'room?code='+code)).room;assert.equal(end.status,'finished');assert.equal(end.winner,'host');assert.equal(end.players.guest.score,0);assert.ok(end.players.host.score>=500);
 // Reopening and repeated join preserve the existing game and score.
 assert.equal((await call(2,'join',{code})).room.status,'finished');
 const second=(await call(1,'rooms',{})).room.id;
 await call(2,'join',{code:second});
 const now=Math.floor(Date.now()/1000);
 db.prepare('UPDATE rooms SET round_started=? WHERE id=?').run(now-125,second);
 const recovered=(await call(1,'room?code='+second)).room;
 assert.equal(recovered.round,2);assert.ok(recovered.seconds_left>=53&&recovered.seconds_left<=55);
 await call(1,'answer',{code:second,round:0,choice:0},409);
 db.prepare('UPDATE rooms SET round_started=? WHERE id=?').run(now-185,second);
 assert.equal((await call(2,'room?code='+second)).room.status,'finished');
 assert.equal((await call(1,'room?code='+second)).room.players.host.score,0);
 await call(1,'morning',{category:'memory',score:300});assert.equal((await call(1,'morning')).results[0].score,300);
 // Malformed payloads never become server errors.
 for(const body of ['{','null','[]','"text"','x'.repeat(4097)]){
  const res=await worker.fetch(new Request('https://example.test/api/join',{method:'POST',headers:{'x-lumi-session':await login(1)},body}),env);
  assert.equal(res.status,body.length>4096?413:400);
 }
 await call(2,'morning',{category:'zen',score:25});
 assert.deepEqual((await call(2,'morning')).results,[{category:'zen',score:25}]);
 assert.deepEqual((await call(1,'morning')).results,[{category:'memory',score:300}]);
 await call(2,'morning',{category:'zen',score:26,user_id:'1'});
 assert.deepEqual((await call(1,'morning')).results,[{category:'memory',score:300}]);
 await call(2,'internal/delete-user',{uid:'1',ts:Math.floor(Date.now()/1000)},401);
 await call(2,'internal/ban-sync',{uid:'1',seq:1,expires:-1,ts:Math.floor(Date.now()/1000)},401);
 const ts=Math.floor(Date.now()/1000),uid='1';
 const signed=(uid,ts)=>createHmac('sha256',token).update(`lumi:delete:v1:${uid}:${ts}`).digest('hex');
 const del=(uid,ts,sig)=>worker.fetch(new Request('https://example.test/api/internal/delete-user',{method:'POST',headers:{'x-lumi-delete-signature':sig},body:JSON.stringify({uid,ts})}),env);
 assert.equal((await del(uid,ts,signed('2',ts))).status,401);
 assert.equal((await del(uid,ts-120,signed(uid,ts-120))).status,401);
 assert.equal((await del(uid,ts,signed(uid,ts))).status,200);
 await call(1,'session',undefined,401);
 assert.equal(db.prepare('SELECT COUNT(*) AS n FROM rooms').get().n,0);
 assert.equal(db.prepare('SELECT COUNT(*) AS n FROM answers').get().n,0);
 assert.equal(db.prepare('SELECT COUNT(*) AS n FROM morning_results WHERE user_id=?').get(uid).n,0);
 assert.equal(db.prepare('SELECT COUNT(*) AS n FROM morning_results WHERE user_id=?').get('2').n,1);
 // A distinct signed launch during the deletion barrier cannot reopen a session.
 const fresh=new URLSearchParams(auth(1));fresh.delete('hash');fresh.set('query_id','new-launch');
 const key=createHmac('sha256','WebAppData').update(token).digest();fresh.set('hash',createHmac('sha256',key).update([...fresh].sort().map(([k,v])=>`${k}=${v}`).join('\n')).digest('hex'));
 assert.equal((await worker.fetch(new Request('https://example.test/api/session',{method:'POST',headers:{'x-telegram-init-data':fresh.toString()}}),env)).status,401);
 // A replay must not touch subsequently written data.
 db.prepare('INSERT INTO morning_results(day,user_id,category,score) VALUES(?,?,?,?)').run('2099-01-01',uid,'zen',99);
 assert.equal((await del(uid,ts,signed(uid,ts))).status,200);
 assert.equal(db.prepare('SELECT score FROM morning_results WHERE user_id=?').get(uid).score,99);
 assert.equal(db.prepare('SELECT COUNT(*) AS n FROM api_rate_limits WHERE user_id=?').get(uid).n,0);
 // Simulate deletion after authentication, immediately before the SQL write.
 for(const [id,path,body,prefix,status] of [
  [101,'morning',{category:'zen',score:40},'INSERT INTO morning_results',401],
  [102,'rooms',{},'INSERT INTO rooms',429],
 ]){
  await login(id);
  beforeRun=async sql=>{if(sql.startsWith(prefix)){beforeRun=null;const stamp=Math.floor(Date.now()/1000);assert.equal((await del(String(id),stamp,signed(String(id),stamp))).status,200);}};
  await call(id,path,body,status);
  assert.equal(beforeRun,null);
  assert.equal(db.prepare('SELECT COUNT(*) n FROM rooms WHERE host_id=?').get(String(id)).n,0);
  assert.equal(db.prepare('SELECT COUNT(*) n FROM morning_results WHERE user_id=?').get(String(id)).n,0);
 }
 // A ban arriving after authentication must prevent the actual write.
 for(const [id,path,body,prefix,status] of [
  [103,'morning',{category:'zen',score:40},'INSERT INTO morning_results',401],
  [104,'rooms',{},'INSERT INTO rooms',429],
 ]){
  await login(id);
  beforeRun=async sql=>{if(sql.startsWith(prefix)){beforeRun=null;db.prepare('INSERT INTO global_bans VALUES(?,?,?)').run(String(id),1,-1);}};
  await call(id,path,body,status);
  assert.equal(beforeRun,null);
  assert.equal(db.prepare('SELECT COUNT(*) n FROM rooms WHERE host_id=?').get(String(id)).n,0);
  assert.equal(db.prepare('SELECT COUNT(*) n FROM morning_results WHERE user_id=?').get(String(id)).n,0);
  await call(id,'session',undefined,403);
 }
 // Revoke access after authentication, while reading private results.
 await call(105,'morning',{category:'zen',score:40});
 beforeAll=async sql=>{if(sql.startsWith('SELECT category,score')){beforeAll=null;db.prepare('INSERT INTO global_bans VALUES(?,?,?)').run('105',1,-1);}};
 const denied=await call(105,'morning',undefined,403);assert.equal(denied.results,undefined);assert.equal(beforeAll,null);
 // Revoke a session before automatic round advancement: no mutation allowed.
 const race=(await call(106,'rooms',{})).room.id;
 await call(107,'join',{code:race});
 db.prepare('UPDATE rooms SET round_started=? WHERE id=?').run(ts-125,race);
 beforeRun=async sql=>{if(sql.startsWith('UPDATE rooms SET round=round+1')){beforeRun=null;db.prepare('UPDATE web_sessions SET expires_at=0 WHERE user_id=?').run('106');}};
 await call(106,'room?code='+race,undefined,401);
 assert.equal(db.prepare('SELECT round FROM rooms WHERE id=?').get(race).round,0);assert.equal(beforeRun,null);
 const old=ts-31*86400;
 db.prepare('INSERT INTO rooms(id,host_id,created_at,updated_at) VALUES(?,?,?,?)').run('old','5',old,old);
 db.prepare('INSERT INTO answers VALUES(?,?,?,?,?,?,?)').run('old',0,'5',0,1,100,old);
 db.prepare('INSERT INTO api_rate_limits VALUES(?,?,?)').run('5',old,1);
 let cleanup;await worker.scheduled({scheduledTime:ts*1000},env,{waitUntil(p){cleanup=p}});await cleanup;
 assert.equal(db.prepare('SELECT COUNT(*) AS n FROM rooms WHERE id=?').get('old').n,0);
 assert.equal(db.prepare('SELECT COUNT(*) AS n FROM answers WHERE room_id=?').get('old').n,0);
 assert.equal(db.prepare('SELECT COUNT(*) AS n FROM api_rate_limits WHERE user_id=?').get('5').n,0);
 }finally{db.close()}
});
