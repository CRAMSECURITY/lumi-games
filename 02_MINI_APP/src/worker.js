import {buildPlan} from '../public/date-planner.js';
import {validateEvent} from './organizer.js';
import {validateProfile,goals as businessGoals} from './business.js';
import {observeResponse} from './threat-monitor.js';
import {AuthError} from './auth.js';
import {blocked,syncBan} from './global-ban.js';
import {exchange,sessionUser} from './session.js';
import {ROUND_COUNT, ROUND_SECONDS,getPuzzle,publicPuzzle,pointsFor} from './game.js';
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer','x-frame-options':'DENY'}});
const fail=(message,status=400)=>json({error:message},status);
const unavailable=()=>json({error:'Сервис временно недоступен. Попробуй позже.'},503);
const now=()=>Math.floor(Date.now()/1000);
const RELEASE='LUMI-GAMES-2.2-ZERO-TRUST-ACCESS-012.8';
async function readiness(env){
 const hasToken=typeof env.BOT_TOKEN==='string' && env.BOT_TOKEN.trim().length>0;
 const ban=typeof env.LUMI_BAN_SYNC_KEY==='string' && env.LUMI_BAN_SYNC_KEY.length>=32;
 const edge=typeof env.EDGE_RATE?.limit==='function';
 let database=false;
 try {
  const row=await env.DB.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name IN ('rooms','answers','morning_results','api_rate_limits','web_sessions','global_bans','account_deletions')").first();
  if(row?.n===7){
   // Prepare real column references; a table name alone does not establish readiness.
   for(const sql of [
    'SELECT id,host_id,guest_id,status,round,round_started,created_at,updated_at FROM rooms LIMIT 0',
    'SELECT room_id,round,user_id,choice,correct,points,answered_at FROM answers LIMIT 0',
    'SELECT day,user_id,category,score FROM morning_results LIMIT 0',
    'SELECT user_id,window_start,hits FROM api_rate_limits LIMIT 0',
    'SELECT init_hash,token_hash,user_id,expires_at,retain_until FROM web_sessions LIMIT 0',
    'SELECT user_id,seq,expires FROM global_bans LIMIT 0',
    'SELECT user_id,request_ts,block_until FROM account_deletions LIMIT 0'
   ]) await env.DB.prepare(sql).first();
   if(env.LUMI_BUSINESS_MODERATION==='1'){await env.DB.prepare('SELECT moderation_decision FROM business_profiles LIMIT 0').first();await env.DB.prepare('SELECT reviewed_at FROM business_reports LIMIT 0').first();}
   if(env.LUMI_BUSINESS_DIRECTORY==='1')await env.DB.prepare('SELECT user_id,name,role,sector,skills,goal,revision,approved,updated_at,moderation_decision FROM business_profiles LIMIT 0').first();
   if(env.LUMI_BUSINESS_DIRECTORY==='1'&&env.LUMI_BUSINESS_CONNECT==='1'){for(const q of ['SELECT id,sender,recipient,state,created_at FROM business_invites LIMIT 0','SELECT id,sender,created_at FROM business_invite_history LIMIT 0','SELECT blocker,blocked FROM business_blocks LIMIT 0','SELECT invite_id,reporter,reported,reason,created_at FROM business_reports LIMIT 0'])await env.DB.prepare(q).first();}
   if(env.LUMI_EVENT_ORGANIZER==='1')await env.DB.prepare('SELECT id,owner,title,city,kind,starts_at,venue,description,state,created_at FROM organizer_events LIMIT 0').first();
   if(env.LUMI_EVENT_ORGANIZER==='1'&&env.LUMI_EVENT_REGISTRATION==='1'){await env.DB.prepare('SELECT capacity FROM organizer_events LIMIT 0').first();await env.DB.prepare('SELECT event_id,user_id,created_at FROM event_registrations LIMIT 0').first();}
   if(env.LUMI_PRIVILEGES==='1'){await env.DB.prepare("SELECT id,merchant_id,enabled,ends_at FROM partner_privileges LIMIT 0").first();await env.DB.prepare("SELECT code,redeemed_at FROM privilege_codes LIMIT 0").first();}
   if(env.LUMI_DATE_CONNECT==='1'){await env.DB.prepare('SELECT blocker,blocked FROM date_blocks LIMIT 0').first();await env.DB.prepare('SELECT code,owner,expires_at FROM date_keys LIMIT 0').first();await env.DB.prepare('SELECT id,sender,recipient,place_id,day,time,state,created_at FROM date_plans LIMIT 0').first();}
   database=true;
  }
 } catch { /* No database details are disclosed. */ }
 return {ok:database&&hasToken&&ban&&edge,database,telegram_auth:hasToken,ban_sync_configured:ban,edge_configured:edge,release:RELEASE};
}
const RATE_LIMIT=120;
const activeSession='EXISTS (SELECT 1 FROM web_sessions WHERE token_hash=? AND user_id=? AND expires_at>?) AND NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=? AND (expires=-1 OR expires>?))';
const sessionArgs=user=>{const t=now();return [user.hash,user.id,t,user.id,t];};
async function consumeRate(env,user,t){
 const uid=user.id;
 const window=Math.floor(t/60)*60;
 const row=await env.DB.prepare(`INSERT INTO api_rate_limits(user_id,window_start,hits) SELECT ?,?,1 WHERE ${activeSession} ON CONFLICT(user_id,window_start) DO UPDATE SET hits=hits+1 WHERE hits<? RETURNING hits`).bind(uid,window,...sessionArgs(user),RATE_LIMIT).first();
 return !!row;
}
async function cleanup(env,t){
 if(env.LUMI_DATE_CONNECT==='1')await env.DB.batch([env.DB.prepare('DELETE FROM date_keys WHERE expires_at<=?').bind(t),env.DB.prepare('DELETE FROM date_plans WHERE created_at<?').bind(t-90*86400)]);
 if(env.LUMI_BUSINESS_DIRECTORY==='1'&&env.LUMI_BUSINESS_CONNECT==='1')await env.DB.batch([env.DB.prepare('DELETE FROM business_invite_history WHERE created_at<=?').bind(t-86400),env.DB.prepare('DELETE FROM business_reports WHERE created_at<=?').bind(t-90*86400)]);
 if(env.LUMI_EVENT_ORGANIZER==='1'&&env.LUMI_EVENT_REGISTRATION==='1')await env.DB.prepare('DELETE FROM event_registrations WHERE event_id IN (SELECT id FROM organizer_events WHERE starts_at<?)').bind(t-30*86400).run();
 await env.DB.batch([env.DB.prepare('DELETE FROM account_deletions WHERE block_until<?').bind(t-3600),env.DB.prepare('DELETE FROM web_sessions WHERE retain_until<=?').bind(t),env.DB.prepare('DELETE FROM api_rate_limits WHERE window_start<?').bind(t-3600),env.DB.prepare('DELETE FROM answers WHERE room_id IN (SELECT id FROM rooms WHERE updated_at<?)').bind(t-30*86400),env.DB.prepare('DELETE FROM rooms WHERE updated_at<?').bind(t-30*86400)]);
}
class RequestError extends Error {constructor(message,status=400){super(message);this.status=status;}}
const BODY_LIMIT=4096;
function checkBodyLength(req){
 const declared=req.headers.get('content-length');
 if(declared!==null && !/^[0-9]+$/.test(declared))throw new RequestError('Некорректная длина запроса');
 if(declared!==null && Number(declared)>BODY_LIMIT)throw new RequestError('Слишком большой запрос',413);
}
export async function readBoundedBody(req, timeoutMs=5000){
 checkBodyLength(req);
 const reader=req.body?.getReader();
 if(!reader)return new Uint8Array(0);
 const bytes=new Uint8Array(BODY_LIMIT);let size=0, chunks=0, timer, complete=false;
 const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>reject(new RequestError('Время ожидания запроса истекло',408)),timeoutMs);});
 try{
  while(true){
   let part;try{part=await Promise.race([reader.read(),deadline]);}catch(e){if(e instanceof RequestError)throw e;throw new RequestError('Не удалось прочитать запрос');}
   const {done,value}=part;
   if(done){complete=true;break;}
   if(++chunks>8192)throw new RequestError('Слишком много частей запроса',413);
   if(value.byteLength>BODY_LIMIT-size)throw new RequestError('Слишком большой запрос',413);
   bytes.set(value,size);size+=value.byteLength;
  }
  return bytes.subarray(0,size);
 }finally{
  clearTimeout(timer);
  if(!complete){try{void reader.cancel().catch(()=>{});}catch{}}
  reader.releaseLock();
 }
}
async function bodyOf(req){
 const bytes=await readBoundedBody(req);
 let data;try{data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)||'{}');}catch{throw new RequestError('Некорректный JSON');}
 if(!data||typeof data!=='object'||Array.isArray(data))throw new RequestError('Ожидается объект JSON');
 return data;
}
async function deleteGameData(env,uid,ts,t){
 await env.DB.batch([
 env.DB.prepare('INSERT INTO account_deletions(user_id,request_ts,block_until) VALUES(?,?,?)').bind(uid,ts,t+120),
 env.DB.prepare('DELETE FROM answers WHERE room_id IN (SELECT id FROM rooms WHERE host_id=? OR guest_id=?) OR user_id=?').bind(uid,uid,uid),
 env.DB.prepare('DELETE FROM rooms WHERE host_id=? OR guest_id=?').bind(uid,uid),
 env.DB.prepare('DELETE FROM morning_results WHERE user_id=?').bind(uid),
 env.DB.prepare('DELETE FROM api_rate_limits WHERE user_id=?').bind(uid),
 env.DB.prepare('UPDATE web_sessions SET user_id=NULL,token_hash=NULL,expires_at=0 WHERE user_id=?').bind(uid)
 ]);
}
async function verifyDeletion(req,env,t){
 const b=await bodyOf(req);
 if(typeof b.uid!=='string'||!/^([1-9][0-9]{0,15})$/.test(b.uid)||!Number.isSafeInteger(Number(b.uid))||!Number.isSafeInteger(b.ts)||Math.abs(t-b.ts)>60)return fail('Неверный запрос',401);
 const sig=req.headers.get('x-lumi-delete-signature')||'';
 if(!/^[a-f0-9]{64}$/.test(sig))return fail('Нет доступа',401);
 const enc=new TextEncoder();
 const key=await crypto.subtle.importKey('raw',enc.encode(env.BOT_TOKEN.trim()),{name:'HMAC',hash:'SHA-256'},false,['verify']);
 const valid=await crypto.subtle.verify('HMAC',key,Uint8Array.from(sig.match(/../g),x=>parseInt(x,16)),enc.encode(`lumi:delete:v1:${b.uid}:${b.ts}`));
 if(!valid)return fail('Нет доступа',401);
 // The receipt and all deletions commit together; a replay cannot delete again.
 const receipt=()=>env.DB.prepare('SELECT request_ts FROM account_deletions WHERE user_id=? AND request_ts=?').bind(b.uid,b.ts).first();
 if(await receipt())return json({deleted:true});
 try{await deleteGameData(env,b.uid,b.ts,t);}catch(e){if(!await receipt())throw e;}
 return json({deleted:true});
}
const isCode=code=>typeof code==='string'&&/^[a-f0-9]{24}$/.test(code);
const roomQuery='SELECT id,host_id,guest_id,status,round,round_started,created_at FROM rooms WHERE id=?';
async function getRoom(env,code){return env.DB.prepare(roomQuery).bind(code).first();}
async function participants(env,room){return env.DB.prepare('SELECT user_id,round,points,correct FROM answers WHERE room_id=? ORDER BY round').bind(room.id).all();}
async function requireActive(env,user){
 const t=now();
 if(await blocked(env,user.id,t))throw new RequestError("Аккаунт ограничен",403);
 const row=await env.DB.prepare(`SELECT 1 AS ok WHERE ${activeSession}`).bind(...sessionArgs(user)).first();
 if(!row)throw new RequestError("Сессия истекла. Открой LUMI заново через Telegram",401);
}
async function advance(env,room,t,user){
 if(!room)throw new RequestError('Комната больше недоступна',409);
 // Expired rounds advance on their original deadlines, even if both clients were offline.
 for(let step=0;step<ROUND_COUNT && room.status==='playing';step++){
  const rows=(await env.DB.prepare('SELECT user_id FROM answers WHERE room_id=? AND round=?').bind(room.id,room.round).all()).results;
  const expires=room.round_started+ROUND_SECONDS;
  if(rows.length<2 && t<expires)return room;
  if(room.round+1>=ROUND_COUNT){
   await env.DB.prepare(`UPDATE rooms SET status=?,updated_at=? WHERE id=? AND status=? AND round=? AND (host_id=? OR guest_id=?) AND ${activeSession}`).bind('finished',t,room.id,'playing',room.round,user.id,user.id,...sessionArgs(user)).run();
  }else{
   await env.DB.prepare(`UPDATE rooms SET round=round+1,round_started=?,updated_at=? WHERE id=? AND status=? AND round=? AND (host_id=? OR guest_id=?) AND ${activeSession}`).bind(Math.min(t,expires),t,room.id,'playing',room.round,user.id,user.id,...sessionArgs(user)).run();
  }
  await requireActive(env,user);
  room=await getRoom(env,room.id);
  if(!room)throw new RequestError('Комната больше недоступна',409);
 }
 return room;
}
async function state(env,room,user,t){
 const uid=user.id;
 await requireActive(env,user);
 if(!room)throw new RequestError('Комната больше недоступна',409);
 if(uid!==room.host_id&&uid!==room.guest_id)throw new RequestError('Нет доступа',403);
 room=await advance(env,room,t,user);
 if(uid!==room.host_id&&uid!==room.guest_id)throw new RequestError('Нет доступа',403);
 const answers=(await participants(env,room)).results;
 await requireActive(env,user);
 const score=id=>answers.filter(a=>a.user_id===id&&(room.status==='finished'||a.round<room.round)).reduce((s,a)=>s+a.points,0);
 const mine=answers.find(a=>a.round===room.round&&a.user_id===uid);
 const opp=answers.find(a=>a.round===room.round&&a.user_id!==(uid));
 const guest=room.guest_id;
 let lastRound=null;
 if(room.round>0 || room.status==='finished'){
  const prev=room.status==='finished'?room.round:room.round-1;
  lastRound={round:prev,correct_answer:getPuzzle(room.id,prev).answer,answers:answers.filter(a=>a.round===prev).map(a=>({who:a.user_id===room.host_id?'host':'guest',correct:!!a.correct,points:a.points}))};
 }
 return {id:room.id,status:room.status,round:room.round,total:ROUND_COUNT,seconds_left:room.status==='playing'?Math.max(0,ROUND_SECONDS-(t-room.round_started)):null,
  you:uid===room.host_id?'host':'guest',players: {host:{present:true,score:score(room.host_id)},guest:{present:!!guest,score:guest?score(guest):0}},
  puzzle:room.status==='playing'?publicPuzzle(getPuzzle(room.id,room.round)):null,
  answered:!!mine,opponent_answered:!!opp,
  lastRound,
  winner:room.status==='finished'?(score(room.host_id)===score(guest)?'draw':score(room.host_id)>score(guest)?'host':'guest'):null};
}
async function handle(req,env){
 const u=new URL(req.url),route=u.pathname,t=now();
 if(!env.DB)return unavailable();
 if(typeof env.BOT_TOKEN!=='string'||!env.BOT_TOKEN.trim())return unavailable();
 if(req.method==='POST' && route==='/api/internal/delete-user')return verifyDeletion(req,env,t);
 if(req.method==='POST' && route==='/api/internal/ban-sync'){const status=await syncBan(env,await bodyOf(req),req.headers.get('x-lumi-ban-signature')||'',t);return status===200?json({accepted:true}):fail('Нет доступа',status);}
 if(req.method==='POST' && route==='/api/session'){
  let result;try{result=await exchange(env,req.headers.get('x-telegram-init-data'),t);}catch(e){if(e instanceof AuthError)return fail('Открой LUMI заново через Telegram',401);throw e;}
  return result?json(result):fail('Сессия уже использована. Открой LUMI заново через Telegram',401);
 }
 const user=await sessionUser(env,req.headers.get('x-lumi-session'),t);
 if(user && await blocked(env,user.id,t))return fail('Аккаунт ограничен',403);
 if(!user)return fail('Сессия истекла. Открой LUMI заново через Telegram',401);
 if(!await consumeRate(env,user,t))return new Response(JSON.stringify({error:'Слишком много запросов. Попробуй позже.'}),{status:429,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store','retry-after':String(60-t%60),'x-content-type-options':'nosniff'}});
 if(req.method==='GET' && route==='/api/session'){await requireActive(env,user);return json({authenticated:true});}
 if(route.startsWith('/api/date-connect/')){
  if(env.LUMI_DATE_CONNECT!=='1')return fail('Совместные планы пока отключены',404);
  const keyOk=v=>typeof v==='string'&&/^[a-f0-9]{32}$/.test(v);
  const otherActive=`NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=CASE WHEN sender=? THEN recipient ELSE sender END AND (expires=-1 OR expires>?))`;
  const noBlock=`NOT EXISTS (SELECT 1 FROM date_blocks WHERE (blocker=sender AND blocked=recipient) OR (blocker=recipient AND blocked=sender))`;
  if(req.method==='GET'&&route==='/api/date-connect/list'){
   const rows=(await env.DB.prepare(`SELECT id,place_id,day,time,state,CASE WHEN sender=? THEN 'outgoing' ELSE 'incoming' END AS direction FROM date_plans WHERE (sender=? OR recipient=?) AND ${otherActive} AND ${noBlock} AND ${activeSession} ORDER BY created_at DESC LIMIT 50`).bind(user.id,user.id,user.id,user.id,t,...sessionArgs(user)).all()).results;
   await requireActive(env,user);return json({plans:rows});
  }
  if(req.method!=='POST')return fail('Маршрут не найден',404);
  const b=await bodyOf(req);if(b.consent!==true)return fail('Требуется подтверждение');
  if(route==='/api/date-connect/key'){
   const code=Array.from(crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,'0')).join('');
   const r=await env.DB.prepare(`INSERT INTO date_keys(code,owner,expires_at) SELECT ?,?,? WHERE ${activeSession} ON CONFLICT(owner) DO UPDATE SET code=excluded.code,expires_at=excluded.expires_at`).bind(code,user.id,t+600,...sessionArgs(user)).run();return r.meta.changes?json({code,expires_at:t+600}):fail('Сессия истекла',401);
  }
  if(route==='/api/date-connect/revoke'){
   await env.DB.prepare(`DELETE FROM date_keys WHERE owner=? AND ${activeSession}`).bind(user.id,...sessionArgs(user)).run();await requireActive(env,user);return json({revoked:true});
  }
  if(route==='/api/date-connect/block'){
   if(typeof b.id!=='string')return fail('Некорректный план');
   const r=await env.DB.prepare(`INSERT INTO date_blocks(blocker,blocked) SELECT ?,CASE WHEN sender=? THEN recipient ELSE sender END FROM date_plans WHERE id=? AND (sender=? OR recipient=?) AND ${activeSession} ON CONFLICT DO NOTHING`).bind(user.id,user.id,b.id,user.id,user.id,...sessionArgs(user)).run();return r.meta.changes?json({blocked:true}):fail('План недоступен',409);
  }
  if(route==='/api/date-connect/send'){
   if(!keyOk(b.code)||!buildPlan({placeId:b.place_id,date:b.day,time:b.time},new Date(t*1000)))return fail('Некорректный план');
   const id=crypto.randomUUID();
   const r=await env.DB.prepare(`INSERT INTO date_plans(id,sender,recipient,place_id,day,time,state,created_at) SELECT ?,?,owner,?,?,?,'pending',? FROM date_keys WHERE code=? AND owner<>? AND expires_at>? AND NOT EXISTS(SELECT 1 FROM global_bans WHERE user_id=date_keys.owner AND (expires=-1 OR expires>?)) AND NOT EXISTS(SELECT 1 FROM date_blocks WHERE (blocker=? AND blocked=date_keys.owner) OR (blocker=date_keys.owner AND blocked=?)) AND ${activeSession} AND (SELECT COUNT(*) FROM date_plans WHERE sender=? AND created_at>?)<5`).bind(id,user.id,b.place_id,b.day,b.time,t,b.code,user.id,t,t,user.id,user.id,...sessionArgs(user),user.id,t-86400).run();return r.meta.changes?json({id,state:'pending'}):fail('Код недоступен или достигнут лимит',409);
  }
  if(route==='/api/date-connect/decide'){
   if(typeof b.id!=='string'||!['accepted','declined','cancelled'].includes(b.state))return fail('Некорректное решение');
   const row=await env.DB.prepare(`SELECT place_id,day,time FROM date_plans WHERE id=? AND (sender=? OR recipient=?) AND ${activeSession}`).bind(b.id,user.id,user.id,...sessionArgs(user)).first();
   if(!row||(b.state==='accepted'&&!buildPlan({placeId:row.place_id,date:row.day,time:row.time},new Date(t*1000))))return fail('План недоступен',409);
   const r=await env.DB.prepare(`UPDATE date_plans SET state=? WHERE id=? AND ((recipient=? AND state='pending' AND ? IN ('accepted','declined')) OR ((sender=? OR recipient=?) AND state IN ('pending','accepted') AND ?='cancelled')) AND (?='cancelled' OR (${otherActive} AND ${noBlock})) AND ${activeSession}`).bind(b.state,b.id,user.id,b.state,user.id,user.id,b.state,b.state,user.id,t,...sessionArgs(user)).run();return r.meta.changes?json({state:b.state}):fail('План недоступен',409);
  }
  return fail('Маршрут не найден',404);
 }
 if(route.startsWith('/api/privileges/')){
  if(env.LUMI_PRIVILEGES!=='1')return fail('Привилегии пока отключены',404);
  const eligible="p.enabled=1 AND p.starts_at<=? AND p.ends_at>? AND NOT EXISTS(SELECT 1 FROM global_bans WHERE user_id=p.merchant_id AND (expires=-1 OR expires>?))";
  if(route.startsWith('/api/privileges/studio-')){
   if(env.LUMI_PARTNER_STUDIO!=='1')return fail('Кабинет пока отключён',404);
   if(!String(env.LUMI_PARTNER_IDS||'').split(',').map(x=>x.trim()).includes(user.id))return fail('Нет доступа',403);
   if(req.method==='GET'&&route==='/api/privileges/studio-list'){
    const offers=(await env.DB.prepare(`SELECT p.id,p.title,p.terms,p.city,p.starts_at,p.ends_at,p.enabled,(SELECT COUNT(*) FROM privilege_codes c WHERE c.offer_id=p.id) AS issued,(SELECT COUNT(*) FROM privilege_codes c WHERE c.offer_id=p.id AND c.redeemed_at IS NOT NULL) AS redeemed FROM partner_privileges p WHERE p.merchant_id=? AND ${activeSession} ORDER BY p.ends_at DESC LIMIT 50`).bind(user.id,...sessionArgs(user)).all()).results;
    await requireActive(env,user);return json({offers});
   }
   if(req.method==='POST'&&route==='/api/privileges/studio-create'){
    const b=await bodyOf(req), valid=(v,n)=>typeof v==='string'&&v.trim().length>0&&v.trim().length<=n;
    if(!b||!valid(b.title,80)||!valid(b.terms,400)||!valid(b.city,80)||!Number.isSafeInteger(b.starts_at)||!Number.isSafeInteger(b.ends_at)||b.starts_at<t||b.ends_at<=b.starts_at||b.ends_at>t+366*86400||b.consent!==true)return fail('Проверь данные предложения');
    const id=crypto.randomUUID();
    const r=await env.DB.prepare(`INSERT INTO partner_privileges(id,merchant_id,title,terms,city,starts_at,ends_at,enabled) SELECT ?,?,?,?,?,?,?,0 WHERE ${activeSession} AND (SELECT COUNT(*) FROM partner_privileges WHERE merchant_id=? AND ends_at>?)<20`).bind(id,user.id,b.title.trim(),b.terms.trim(),b.city.trim(),b.starts_at,b.ends_at,...sessionArgs(user),user.id,t).run();
    return r.meta.changes?json({id,enabled:false}):fail('Лимит предложений или сессия недоступна',409);
   }
   if(req.method==='POST'&&route==='/api/privileges/studio-pause'){
    const b=await bodyOf(req);if(!b||typeof b.id!=='string'||b.id.length>64||b.consent!==true)return fail('Подтверди остановку');
    const r=await env.DB.prepare(`UPDATE partner_privileges SET enabled=0 WHERE id=? AND merchant_id=? AND enabled=1 AND ${activeSession}`).bind(b.id,user.id,...sessionArgs(user)).run();return r.meta.changes?json({paused:true}):fail('Предложение недоступно',409);
   }
   return fail('Маршрут не найден',404);
  }
  if(req.method==='GET'&&route==='/api/privileges/list'){
   const rows=(await env.DB.prepare(`SELECT p.id,p.title,p.terms,p.city,p.ends_at,c.code,c.redeemed_at FROM partner_privileges p LEFT JOIN privilege_codes c ON c.offer_id=p.id AND c.user_id=? WHERE ${eligible} AND ${activeSession} ORDER BY p.ends_at,p.id LIMIT 50`).bind(user.id,t,t,t,...sessionArgs(user)).all()).results;await requireActive(env,user);return json({offers:rows});
  }
  if(req.method==='POST'&&route==='/api/privileges/claim'){
   const b=await bodyOf(req);if(!b||typeof b.id!=='string'||!/^[a-zA-Z0-9_-]{1,64}$/.test(b.id)||b.consent!==true)return fail('Подтверди получение предложения');
   const code=crypto.randomUUID().replaceAll('-','');
   await env.DB.prepare(`INSERT INTO privilege_codes(offer_id,user_id,code,issued_at) SELECT p.id,?,?,? FROM partner_privileges p WHERE p.id=? AND p.merchant_id<>? AND ${eligible} AND ${activeSession} ON CONFLICT(offer_id,user_id) DO NOTHING`).bind(user.id,code,t,b.id,user.id,t,t,t,...sessionArgs(user)).run();
   const row=await env.DB.prepare(`SELECT c.code,c.redeemed_at FROM privilege_codes c JOIN partner_privileges p ON p.id=c.offer_id WHERE c.offer_id=? AND c.user_id=? AND ${eligible} AND ${activeSession}`).bind(b.id,user.id,t,t,t,...sessionArgs(user)).first();await requireActive(env,user);return row?json(row):fail('Предложение недоступно',409);
  }
  if(req.method==='POST'&&route==='/api/privileges/redeem'){
   const b=await bodyOf(req);if(!b||typeof b.code!=='string'||!/^[a-f0-9]{32}$/.test(b.code)||b.consent!==true)return fail('Некорректный код');
   const r=await env.DB.prepare(`UPDATE privilege_codes SET redeemed_at=? WHERE code=? AND redeemed_at IS NULL AND EXISTS(SELECT 1 FROM partner_privileges p WHERE p.id=offer_id AND p.merchant_id=? AND ${eligible}) AND NOT EXISTS(SELECT 1 FROM global_bans WHERE user_id=privilege_codes.user_id AND (expires=-1 OR expires>?)) AND ${activeSession}`).bind(t,b.code,user.id,t,t,t,t,...sessionArgs(user)).run();return r.meta.changes?json({redeemed:true}):fail('Код недоступен',409);
  }
  return fail('Маршрут не найден',404);
 }
 if(route.startsWith('/api/events/')){
  if(env.LUMI_EVENT_ORGANIZER!=='1')return fail('Раздел пока отключён',404);
  const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
  const columns='id,title,city,kind,starts_at,venue,description,state';
  if(route.startsWith('/api/events/registration/')){
   if(env.LUMI_EVENT_REGISTRATION!=='1')return fail('Регистрация пока отключена',404);
   const eligible=`e.state='approved' AND e.starts_at>? AND NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=e.owner AND (expires=-1 OR expires>?))`;
   const fields=`e.id,e.title,e.city,e.kind,e.starts_at,e.venue,e.description,e.state,e.capacity,MAX(0,e.capacity-(SELECT COUNT(*) FROM event_registrations r WHERE r.event_id=e.id)) AS remaining,EXISTS(SELECT 1 FROM event_registrations r WHERE r.event_id=e.id AND r.user_id=?) AS joined,e.owner=? AS own_event`;
   if(req.method==='GET'&&['/api/events/registration/list','/api/events/registration/mine'].includes(route)){
    const mine=route.endsWith('/mine');const condition=mine?`EXISTS(SELECT 1 FROM event_registrations r WHERE r.event_id=e.id AND r.user_id=?) AND e.starts_at>?` : eligible;
    const rows=(await env.DB.prepare(`SELECT ${fields},NOT EXISTS(SELECT 1 FROM global_bans WHERE user_id=e.owner AND (expires=-1 OR expires>?)) AS organizer_active FROM organizer_events e WHERE ${condition} AND ${activeSession} ORDER BY e.starts_at,e.id LIMIT 50`).bind(user.id,user.id,t,...(mine?[user.id,t]:[t,t]),...sessionArgs(user)).all()).results;await requireActive(env,user);return json({events:rows});
   }
   if(req.method==='POST'&&['/api/events/registration/join','/api/events/registration/leave'].includes(route)){
    const b=await bodyOf(req);if(!b||!uuid(b.id))return fail('Некорректное событие');
    if(route.endsWith('/leave')){await env.DB.prepare(`DELETE FROM event_registrations WHERE event_id=? AND user_id=? AND ${activeSession}`).bind(b.id,user.id,...sessionArgs(user)).run();await requireActive(env,user);return json({joined:false});}
    if(b.consent!==true)return fail('Подтверди участие');
    const r=await env.DB.prepare(`INSERT INTO event_registrations(event_id,user_id,created_at) SELECT e.id,?,? FROM organizer_events e WHERE e.id=? AND e.owner<>? AND ${eligible} AND ${activeSession} AND (SELECT COUNT(*) FROM event_registrations r WHERE r.event_id=e.id)<e.capacity ON CONFLICT(event_id,user_id) DO NOTHING`).bind(user.id,t,b.id,user.id,t,t,...sessionArgs(user)).run();
    return r.meta.changes?json({joined:true}):fail('Нет свободных мест или событие недоступно; обнови список',409);
   }
   return fail('Маршрут не найден',404);
  }
  if(route==='/api/events/list'&&req.method==='GET'){
   const rows=(await env.DB.prepare(`SELECT ${columns} FROM organizer_events e WHERE state='approved' AND starts_at>? AND NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=e.owner AND (expires=-1 OR expires>?)) AND ${activeSession} ORDER BY starts_at,id LIMIT 50`).bind(t,t,...sessionArgs(user)).all()).results;await requireActive(env,user);return json({events:rows});
  }
  if(route==='/api/events/mine'&&req.method==='GET'){
   const rows=(await env.DB.prepare(`SELECT ${columns} FROM organizer_events WHERE owner=? AND ${activeSession} ORDER BY created_at DESC LIMIT 50`).bind(user.id,...sessionArgs(user)).all()).results;await requireActive(env,user);return json({events:rows});
  }
  if(route==='/api/events/submit'&&req.method==='POST'){
   const b=validateEvent(await bodyOf(req),t);if(!b)return fail('Проверь данные события');
   if(env.LUMI_EVENT_REGISTRATION==='1'){const id=crypto.randomUUID();const r=await env.DB.prepare(`INSERT INTO organizer_events(id,owner,title,city,kind,starts_at,venue,description,state,created_at,capacity) SELECT ?,?,?,?,?,?,?,?,'pending',?,? WHERE ${activeSession} AND (SELECT COUNT(*) FROM organizer_events WHERE owner=? AND created_at>?)<5 AND (SELECT COUNT(*) FROM organizer_events WHERE owner=? AND state IN ('pending','approved') AND starts_at>?)<20`).bind(id,user.id,b.title,b.city,b.kind,b.starts_at,b.venue,b.description,t,b.capacity,...sessionArgs(user),user.id,t-86400,user.id,t).run();if(!r.meta.changes)return fail('Лимит событий или сессия истекла',409);return json({id,state:'pending'});}
   const id=crypto.randomUUID();const r=await env.DB.prepare(`INSERT INTO organizer_events(id,owner,title,city,kind,starts_at,venue,description,state,created_at) SELECT ?,?,?,?,?,?,?,?,'pending',? WHERE ${activeSession} AND (SELECT COUNT(*) FROM organizer_events WHERE owner=? AND created_at>?)<5 AND (SELECT COUNT(*) FROM organizer_events WHERE owner=? AND state IN ('pending','approved') AND starts_at>?)<20`).bind(id,user.id,b.title,b.city,b.kind,b.starts_at,b.venue,b.description,t,...sessionArgs(user),user.id,t-86400,user.id,t).run();if(!r.meta.changes)return fail('Лимит событий или сессия истекла',409);return json({id,state:'pending'});
  }
  if(route==='/api/events/cancel'&&req.method==='POST'){
   const b=await bodyOf(req);if(!b||!uuid(b.id))return fail('Некорректное событие');const r=await env.DB.prepare(`UPDATE organizer_events SET state='cancelled' WHERE id=? AND owner=? AND state IN ('pending','approved') AND ${activeSession}`).bind(b.id,user.id,...sessionArgs(user)).run();return r.meta.changes?json({cancelled:true}):fail('Событие недоступно',409);
  }
  if(route.startsWith('/api/events/moderation/')){
   const ids=typeof env.LUMI_BUSINESS_MODERATOR_IDS==='string'?env.LUMI_BUSINESS_MODERATOR_IDS.split(',').map(x=>x.trim()):[];
   if(env.LUMI_BUSINESS_MODERATION!=='1'||!ids.length||ids.some(x=>!(/^[1-9][0-9]{0,15}$/).test(x))||!ids.includes(user.id))return fail('Нет доступа',403);
   if(route==='/api/events/moderation/list'&&req.method==='GET'){
    const rows=(await env.DB.prepare(`SELECT ${columns} FROM organizer_events WHERE state='pending' AND owner<>? AND starts_at>? AND ${activeSession} ORDER BY created_at,id LIMIT 50`).bind(user.id,t,...sessionArgs(user)).all()).results;await requireActive(env,user);return json({events:rows});
   }
   if(route==='/api/events/moderation/decide'&&req.method==='POST'){
    const b=await bodyOf(req);if(!b||!uuid(b.id)||!['approved','rejected'].includes(b.state))return fail('Некорректное решение');const r=await env.DB.prepare(`UPDATE organizer_events SET state=? WHERE id=? AND owner<>? AND state='pending' AND starts_at>? AND ${activeSession} AND NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=organizer_events.owner AND (expires=-1 OR expires>?))`).bind(b.state,b.id,user.id,t,...sessionArgs(user),t).run();return r.meta.changes?json({state:b.state}):fail('Событие недоступно',409);
   }
  }
  return fail('Маршрут не найден',404);
 }
 if(route.startsWith('/api/business/')){
  if(env.LUMI_BUSINESS_DIRECTORY!=='1')return fail('Деловой каталог пока отключён',404);
  if(route.startsWith('/api/business/moderation/')){
   if(env.LUMI_BUSINESS_MODERATION!=='1')return fail('Маршрут не найден',404);
   const ids=typeof env.LUMI_BUSINESS_MODERATOR_IDS==='string'?env.LUMI_BUSINESS_MODERATOR_IDS.split(',').map(x=>x.trim()):[];
   if(!ids.length||ids.some(x=>!(/^[1-9][0-9]{0,15}$/).test(x))||!ids.includes(user.id))return fail('Нет доступа',403);
   const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
   if(route.endsWith('/queue')&&req.method==='GET'){
    const profiles=(await env.DB.prepare(`SELECT revision,name,role,sector,skills,goal,updated_at FROM business_profiles WHERE approved=0 AND moderation_decision='pending' AND user_id<>? AND ${activeSession} ORDER BY updated_at,revision LIMIT 50`).bind(user.id,...sessionArgs(user)).all()).results;
    const reports=(await env.DB.prepare(`SELECT invite_id,reporter,reported,reason,created_at FROM business_reports WHERE reviewed_at IS NULL AND reporter<>? AND reported<>? AND ${activeSession} ORDER BY created_at,invite_id LIMIT 50`).bind(user.id,user.id,...sessionArgs(user)).all()).results;
    await requireActive(env,user);return json({profiles,reports});
   }
   if(route.endsWith('/decide')&&req.method==='POST'){
    const b=await bodyOf(req);if(Object.keys(b).length!==2||!uuid(b.revision)||!['approved','rejected'].includes(b.decision))return fail('Некорректное решение');
    const r=await env.DB.prepare(`UPDATE business_profiles SET approved=?,moderation_decision=? WHERE revision=? AND user_id<>? AND approved=0 AND moderation_decision='pending' AND ${activeSession} AND NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=business_profiles.user_id AND (expires=-1 OR expires>?))`).bind(b.decision==='approved'?1:0,b.decision,b.revision,user.id,...sessionArgs(user),t).run();
    await requireActive(env,user);return r.meta.changes===1?json({updated:true}):fail('Заявка недоступна или изменена',409);
   }
   if(route.endsWith('/review')&&req.method==='POST'){
    const b=await bodyOf(req);if(Object.keys(b).length!==2||!uuid(b.invite_id)||typeof b.reporter!=='string'||!(/^[1-9][0-9]{0,15}$/).test(b.reporter))return fail('Некорректная жалоба');
    const r=await env.DB.prepare(`UPDATE business_reports SET reviewed_at=? WHERE invite_id=? AND reporter=? AND reviewed_at IS NULL AND reporter<>? AND reported<>? AND ${activeSession}`).bind(t,b.invite_id,b.reporter,user.id,user.id,...sessionArgs(user)).run();
    await requireActive(env,user);return r.meta.changes===1?json({reviewed:true}):fail('Жалоба недоступна',409);
   }
   return fail('Маршрут не найден',404);
  }
  if(route==='/api/business/me'&&req.method==='GET'){
   const profile=await env.DB.prepare(`SELECT name,role,sector,skills,goal,approved,moderation_decision FROM business_profiles WHERE user_id=? AND ${activeSession}`).bind(user.id,...sessionArgs(user)).first();
   await requireActive(env,user);return json({profile:profile||null});
  }
  if(route==='/api/business/submit'&&req.method==='POST'){
   const p=validateProfile(await bodyOf(req));if(!p)return fail('Проверь поля визитки и согласие на публикацию');
   const revision=crypto.randomUUID();
   const result=await env.DB.prepare(`INSERT INTO business_profiles(user_id,name,role,sector,skills,goal,revision,approved,updated_at) SELECT ?,?,?,?,?,?,?,0,? WHERE ${activeSession} ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,role=excluded.role,sector=excluded.sector,skills=excluded.skills,goal=excluded.goal,revision=excluded.revision,approved=0,moderation_decision='pending',updated_at=excluded.updated_at`).bind(user.id,p.name,p.role,p.sector,p.skills,p.goal,revision,t,...sessionArgs(user)).run();
   if(result.meta.changes!==1)return fail('Сессия истекла',401);return json({pending:true});
  }
  if(route==='/api/business/withdraw'&&req.method==='POST'){
   await env.DB.prepare(`DELETE FROM business_profiles WHERE user_id=? AND ${activeSession}`).bind(user.id,...sessionArgs(user)).run();await requireActive(env,user);return json({withdrawn:true});
  }
  if(route==='/api/business/list'&&req.method==='GET'){
   const goal=u.searchParams.get('goal')||'all';if(u.searchParams.getAll('goal').length>1||!(goal==='all'||businessGoals.includes(goal)))return fail('Некорректная цель');
   const rows=(await env.DB.prepare(`SELECT name,role,sector,skills,goal${env.LUMI_BUSINESS_CONNECT==='1'?',revision AS card_id':''} FROM business_profiles p WHERE approved=1 AND (?='all' OR goal=?) AND NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=p.user_id AND (expires=-1 OR expires>?)) AND ${activeSession} ORDER BY updated_at DESC,user_id LIMIT 20`).bind(goal,goal,t,...sessionArgs(user)).all()).results;
   await requireActive(env,user);return json({profiles:rows});
  }
  if(route.startsWith('/api/business/connect/')){
   if(env.LUMI_BUSINESS_CONNECT!=='1')return fail('Деловые приглашения пока отключены',404);
   const eligible=(alias)=>`${alias}.approved=1 AND NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=${alias}.user_id AND (expires=-1 OR expires>?))`;
   const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
   if(route.endsWith('/send')&&req.method==='POST'){
    const b=await bodyOf(req);if(Object.keys(b).length!==1||!uuid(b.card_id))return fail('Некорректная визитка');
    const r=await env.DB.prepare(`INSERT INTO business_invites(id,sender,recipient,state,created_at) SELECT ?,a.user_id,p.user_id,'pending',? FROM business_profiles a,business_profiles p WHERE a.user_id=? AND p.revision=? AND a.user_id<>p.user_id AND ${eligible('a')} AND ${eligible('p')} AND ${activeSession} AND (SELECT COUNT(*) FROM business_invite_history WHERE sender=a.user_id AND created_at>?)<10 AND NOT EXISTS (SELECT 1 FROM business_blocks WHERE (blocker=a.user_id AND blocked=p.user_id) OR (blocker=p.user_id AND blocked=a.user_id)) AND NOT EXISTS (SELECT 1 FROM business_invites WHERE sender=p.user_id AND recipient=a.user_id) ON CONFLICT(sender,recipient) DO NOTHING`).bind(crypto.randomUUID(),t,user.id,b.card_id,t,t,...sessionArgs(user),t-86400).run();
    await requireActive(env,user);return r.meta.changes===1?json({sent:true}):fail('Приглашение недоступно или уже существует',409);
   }
   if(route.endsWith('/list')&&req.method==='GET'){
    const rows=(await env.DB.prepare(`SELECT i.id,i.state,CASE WHEN i.sender=? THEN 'outgoing' ELSE 'incoming' END AS direction,CASE WHEN i.sender=? THEN p.name ELSE a.name END AS name FROM business_invites i JOIN business_profiles a ON a.user_id=i.sender JOIN business_profiles p ON p.user_id=i.recipient WHERE (i.sender=? OR i.recipient=?) AND ${eligible('a')} AND ${eligible('p')} AND ${activeSession} ORDER BY i.created_at DESC LIMIT 50`).bind(user.id,user.id,user.id,user.id,t,t,...sessionArgs(user)).all()).results;
    await requireActive(env,user);return json({invites:rows});
   }
   if(route==='/api/business/connect/block'&&req.method==='POST'){
    const b=await bodyOf(req);if(Object.keys(b).length!==1||!uuid(b.id))return fail('Некорректное приглашение');
    const r=await env.DB.prepare(`INSERT INTO business_blocks(blocker,blocked) SELECT ?,CASE WHEN sender=? THEN recipient ELSE sender END FROM business_invites WHERE id=? AND (sender=? OR recipient=?) AND ${activeSession} ON CONFLICT DO NOTHING`).bind(user.id,user.id,b.id,user.id,user.id,...sessionArgs(user)).run();
    await requireActive(env,user);return r.meta.changes===1?json({blocked:true}):fail('Приглашение недоступно',409);
   }
   if(route==='/api/business/connect/report'&&req.method==='POST'){
    const b=await bodyOf(req);if(Object.keys(b).length!==2||!uuid(b.id)||!['spam','fraud','harassment','other'].includes(b.reason))return fail('Некорректная жалоба');
    const r=await env.DB.prepare(`INSERT INTO business_reports(invite_id,reporter,reported,reason,created_at) SELECT id,?,CASE WHEN sender=? THEN recipient ELSE sender END,?,? FROM business_invites WHERE id=? AND (sender=? OR recipient=?) AND ${activeSession} ON CONFLICT DO NOTHING`).bind(user.id,user.id,b.reason,t,b.id,user.id,user.id,...sessionArgs(user)).run();
    await requireActive(env,user);return r.meta.changes===1?json({reported:true}):fail('Жалоба уже отправлена или приглашение недоступно',409);
   }
   if(route.endsWith('/decide')&&req.method==='POST'){
    const b=await bodyOf(req);if(Object.keys(b).length!==2||!uuid(b.id)||!['accepted','declined','cancelled'].includes(b.state))return fail('Некорректное решение');
    const r=await env.DB.prepare(`UPDATE business_invites SET state=? WHERE id=? AND ((recipient=? AND state='pending' AND ? IN ('accepted','declined')) OR ((sender=? OR recipient=?) AND state IN ('pending','accepted') AND ?='cancelled')) AND EXISTS (SELECT 1 FROM business_profiles a,business_profiles p WHERE a.user_id=business_invites.sender AND p.user_id=business_invites.recipient AND ${eligible('a')} AND ${eligible('p')}) AND ${activeSession}`).bind(b.state,b.id,user.id,b.state,user.id,user.id,b.state,t,t,...sessionArgs(user)).run();
    await requireActive(env,user);return r.meta.changes===1?json({updated:true}):fail('Приглашение недоступно',409);
   }
  }
  return fail('Маршрут не найден',404);
 }
 if(req.method==='POST' && route==='/api/rooms'){
  const id=Array.from(crypto.getRandomValues(new Uint8Array(12)),v=>v.toString(16).padStart(2,'0')).join('');
  const created=await env.DB.prepare(`INSERT INTO rooms(id,host_id,created_at,updated_at) SELECT ?,?,?,? WHERE (SELECT COUNT(*) FROM rooms WHERE host_id=? AND created_at>?)<5 AND ${activeSession}`).bind(id,user.id,t,t,user.id,t-600,...sessionArgs(user)).run();
  if(created.meta.changes!==1)return fail('Не больше пяти новых комнат за 10 минут. Попробуй позже.',429);
  return json({room:await state(env,await getRoom(env,id),user,t)});
 }
 if(req.method==='POST' && route==='/api/join'){
  const b=await bodyOf(req);if(!isCode(b.code))return fail('Некорректный код комнаты');
  let room=await getRoom(env,b.code);if(!room)return fail('Комната не найдена',404);
  if(room.host_id===user.id||room.guest_id===user.id)return json({room:await state(env,room,user,t)});
  if(room.status!=='waiting' || t-room.created_at>86400)return fail('Комната заполнена или устарела',409);
  const upd=await env.DB.prepare(`UPDATE rooms SET guest_id=?,status='playing',round_started=?,updated_at=? WHERE id=? AND guest_id IS NULL AND status='waiting' AND ${activeSession}`).bind(user.id,t,t,room.id,...sessionArgs(user)).run();
  if(upd.meta.changes!==1)return fail('Другой игрок уже присоединился',409);
  room=await getRoom(env,room.id);
  return json({room:await state(env,room,user,t)});
 }
 if(req.method==='GET' && route==='/api/room'){
  const code=u.searchParams.get('code');if(u.searchParams.getAll('code').length!==1||!isCode(code))return fail('Неверная комната');
  const room=await getRoom(env,code);if(!room)return fail('Комната не найдена',404);
  if(user.id!==room.host_id&&user.id!==room.guest_id)return fail('Это не твоя комната',403);
  return json({room:await state(env,room,user,t)});
 }
 if(req.method==='POST'&&route==='/api/answer'){
  const b=await bodyOf(req);if(!isCode(b.code)||!Number.isInteger(b.round)||b.round<0||b.round>=ROUND_COUNT||!Number.isInteger(b.choice)||b.choice<0||b.choice>3)return fail('Некорректный ответ');
  let room=await getRoom(env,b.code);if(!room)return fail('Комната не найдена',404);
  if(user.id!==room.host_id&&user.id!==room.guest_id)return fail('Нет доступа',403);
  room=await advance(env,room,t,user);
  if(room.status!=='playing'||b.round!==room.round)return fail('Раунд уже завершён',409);
  if(t-room.round_started>=ROUND_SECONDS)return fail('Время вышло',409);
  const p=getPuzzle(room.id,room.round),correct=b.choice===p.answer;
  const points=pointsFor(correct,t-room.round_started);
  const result=await env.DB.prepare(`INSERT OR IGNORE INTO answers(room_id,round,user_id,choice,correct,points,answered_at) SELECT ?,?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM rooms WHERE id=? AND status='playing' AND round=? AND round_started=? AND (host_id=? OR guest_id=?)) AND ${activeSession}`).bind(room.id,room.round,user.id,b.choice,correct?1:0,points,t,room.id,room.round,room.round_started,user.id,user.id,...sessionArgs(user)).run();
  if(result.meta.changes!==1)return fail('Ты уже отвечал в этом раунде',409);
  return json({room:await state(env,await getRoom(env,room.id),user,t)});
 }
 if(req.method==='POST' && route==='/api/morning'){
  const b=await bodyOf(req);if(!['memory','zen'].includes(b.category))return fail('Неверная игра');
  if(!Number.isInteger(b.score)||b.score<0||b.score>1000)return fail('Недопустимое значение');
  // Casual, untrusted client scores. Never exchange for premium, rankings or tangible rewards.
  const day=new Date().toISOString().slice(0,10);
  const saved=await env.DB.prepare(`INSERT INTO morning_results(day,user_id,category,score) SELECT ?,?,?,? WHERE ${activeSession} ON CONFLICT(day,user_id,category) DO UPDATE SET score=MAX(score,excluded.score)`).bind(day,user.id,b.category,b.score,...sessionArgs(user)).run();
  if(saved.meta.changes!==1)return fail('Сессия истекла. Открой LUMI заново через Telegram',401);
  return json({saved:true,day,unranked:true});
 }
 if(req.method==='GET'&&route==='/api/morning'){
  const day=new Date().toISOString().slice(0,10);
  const rows=(await env.DB.prepare('SELECT category,score FROM morning_results WHERE user_id=? AND day=?').bind(user.id,day).all()).results;
  await requireActive(env,user);
  return json({day,results:rows});
 }
 return fail('Маршрут не найден',404);
}
const worker = {async scheduled(controller,env,ctx){ctx.waitUntil(cleanup(env,Math.floor(controller.scheduledTime/1000)).catch(()=>{console.error('LUMI scheduled cleanup failed');throw new Error('LUMI scheduled cleanup failed');}));},async fetch(request,env){
 try{
  const u=new URL(request.url);
  if(u.pathname==='/api'||u.pathname.startsWith('/api/')){
   if(!['GET','POST'].includes(request.method))return fail('Метод не поддерживается',405);
   // Cloudflare edge limiter runs before signature verification or D1 access.
   if(!env.EDGE_RATE || typeof env.EDGE_RATE.limit!=='function')return unavailable();
   const ip=request.headers.get('cf-connecting-ip')||'unknown';
   let limited;try{limited=await env.EDGE_RATE.limit({key:'api:'+ip});}catch{console.error('LUMI edge limiter failed');return unavailable();}
   if(typeof limited?.success!=='boolean')return unavailable();
   if(!limited.success)return new Response(JSON.stringify({error:'Слишком много запросов. Попробуй позже.'}),{status:429,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store','retry-after':'60','x-content-type-options':'nosniff'}});
   if(request.method==='POST')checkBodyLength(request);
   if(u.pathname==='/api/health' && request.method==='GET'){const data=await readiness(env);return json(data,data.ok?200:503);}
   return await handle(request,env);
  }
  return await env.ASSETS.fetch(request);
 }catch(e){if(e instanceof RequestError)return fail(e.message,e.status);console.error('LUMI API error');return fail('Внутренняя ошибка. Повтори действие.',500);}
}};

// Observe only API responses; no attacker-controlled fields enter telemetry.
export default {scheduled:worker.scheduled, async fetch(request,env){
 const response=await worker.fetch(request,env);
 const path=new URL(request.url).pathname;
 return path==='/api'||path.startsWith('/api/') ? observeResponse(response) : response;
}};
