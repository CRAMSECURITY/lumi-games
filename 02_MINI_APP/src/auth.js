export class AuthError extends Error {}
const encoder = new TextEncoder();
const bytesToHex = bytes => [...bytes].map(x=>x.toString(16).padStart(2,'0')).join('');
export async function validateInitData(raw, token, now=Math.floor(Date.now()/1000)) {
 const cleanToken=typeof token==='string'?token.trim():'';
 if(!raw || typeof raw!=='string' || raw.length>8192 || !cleanToken) throw new AuthError('Нет данных Telegram');
 // URLSearchParams silently replaces invalid UTF-8 and accepts broken percent escapes.
 // Reject malformed wire encodings before canonicalizing signed data.
 try { for(const part of raw.split('&')) decodeURIComponent(part.replace(/\+/g,' ')); }
 catch { throw new AuthError('Сессия Telegram недействительна'); }
 const params = new URLSearchParams(raw);
 // HMAC includes signature; only Ed25519 excludes it. Reject ambiguous duplicate keys.
 const seen=new Set();
 for(const [k,v] of params){if(seen.has(k)||!/^[a-zA-Z0-9_]+$/.test(k)||/[\r\n]/.test(v))throw new AuthError('Сессия Telegram недействительна');seen.add(k);}
 const hash=params.get('hash');
 const auth=Number(params.get('auth_date'));
 if(!hash || !/^[0-9a-f]{64}$/i.test(hash) || !Number.isSafeInteger(auth) || now-auth>3600 || auth-now>30 || !/^[0-9]{1,12}$/.test(params.get('auth_date')||'')) throw new AuthError('Сессия Telegram недействительна');
 const values=[];
 for(const [k,v] of params) if(k!=='hash') values.push([k,v]);
 values.sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0);
 const check=values.map(([k,v])=>`${k}=${v}`).join('\n');
 const key1=await crypto.subtle.importKey('raw',encoder.encode('WebAppData'),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const secret=await crypto.subtle.sign('HMAC',key1,encoder.encode(cleanToken));
 const key2=await crypto.subtle.importKey('raw',secret,{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const expected=bytesToHex(new Uint8Array(await crypto.subtle.sign('HMAC',key2,encoder.encode(check))));
 // Fixed-size, constant-time comparison for 64 hex characters.
 let diff=0;for(let i=0;i<64;i++) diff|=expected.charCodeAt(i)^hash.toLowerCase().charCodeAt(i);
 if(diff!==0) throw new AuthError('Неверная подпись Telegram');
 let user;
 try {user=JSON.parse(params.get('user')||'null');}catch{throw new AuthError('Некорректные данные пользователя');}
 if(!user || !Number.isSafeInteger(user.id) || user.id<=0) throw new AuthError('Неизвестный пользователь');
 return {id:String(user.id),first_name:String(user.first_name||'Игрок').slice(0,40)};
}
