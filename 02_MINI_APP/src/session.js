import {blocked} from './global-ban.js';
import {validateInitData,AuthError} from './auth.js';
const hex=b=>Array.from(b,v=>v.toString(16).padStart(2,'0')).join('');
const digest=async s=>hex(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s))));
export async function exchange(env,raw,t){
 const user=await validateInitData(raw,env.BOT_TOKEN,t);
 if(await blocked(env,user.id,t))throw new AuthError('Telegram: аккаунт ограничен');
 const p=new URLSearchParams(raw), issued=Number(p.get('auth_date'));
 if(t-issued>300)throw new AuthError('Открой LUMI заново через Telegram');
 const fingerprint=p.get('hash').toLowerCase();
 const token=hex(crypto.getRandomValues(new Uint8Array(32)));
 const expires=issued+3600;
 const row=await env.DB.prepare('INSERT INTO web_sessions(init_hash,token_hash,user_id,expires_at,retain_until) SELECT ?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM account_deletions WHERE user_id=? AND (block_until>=? OR block_until>=?)) AND NOT EXISTS (SELECT 1 FROM global_bans WHERE user_id=? AND (expires=-1 OR expires>?)) ON CONFLICT(init_hash) DO NOTHING RETURNING init_hash').bind(fingerprint,await digest(token),user.id,expires,issued+3600,user.id,t,issued,user.id,t).first();
 return row?{authenticated:true,token,expires_at:expires}:null;
}
export async function sessionUser(env,token,t){
 if(typeof token!=='string'||!/^[a-f0-9]{64}$/.test(token))return null;
 const hash=await digest(token);
 const row=await env.DB.prepare('SELECT user_id FROM web_sessions WHERE token_hash=? AND expires_at>? AND user_id IS NOT NULL').bind(hash,t).first();
 return row?{id:row.user_id,hash}:null;
}
