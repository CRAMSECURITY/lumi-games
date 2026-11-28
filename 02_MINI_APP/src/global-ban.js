export async function blocked(env,uid,t){
 const row=await env.DB.prepare('SELECT expires FROM global_bans WHERE user_id=?').bind(uid).first();
 return !!row&&(row.expires===-1||row.expires>t);
}
export async function syncBan(env,b,sig,t){
 if(typeof env.LUMI_BAN_SYNC_KEY!=='string'||env.LUMI_BAN_SYNC_KEY.length<32)return 503;
 if(!Number.isSafeInteger(b.seq)||b.seq<=0||typeof b.uid!=='string'||!/^([1-9][0-9]{0,15})$/.test(b.uid)||!Number.isSafeInteger(Number(b.uid))||!Number.isSafeInteger(b.expires)||b.expires< -1||!Number.isSafeInteger(b.ts)||Math.abs(t-b.ts)>60||! /^[a-f0-9]{64}$/.test(sig))return 401;
 const enc=new TextEncoder(),key=await crypto.subtle.importKey('raw',enc.encode(env.LUMI_BAN_SYNC_KEY),{name:'HMAC',hash:'SHA-256'},false,['verify']);
 if(!await crypto.subtle.verify('HMAC',key,Uint8Array.from(sig.match(/../g),x=>parseInt(x,16)),enc.encode(`lumi:ban:v1:${b.seq}:${b.uid}:${b.expires}:${b.ts}`)))return 401;
 await env.DB.prepare('INSERT INTO global_bans(user_id,seq,expires) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET seq=excluded.seq,expires=excluded.expires WHERE excluded.seq>global_bans.seq').bind(b.uid,b.seq,b.expires).run();
 return 200;
}
