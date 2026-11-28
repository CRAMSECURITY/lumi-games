export function validateEvent(b,t){
 const keys=['title','city','kind','starts_at','venue','description','consent','capacity'];
 if(!b||typeof b!=='object'||Array.isArray(b)||Object.keys(b).some(k=>!keys.includes(k))||b.consent!==true||!['network','startup','culture','conference'].includes(b.kind)||!Number.isSafeInteger(b.starts_at)||b.starts_at<=t||b.starts_at>t+366*86400)return null;
 const capacity=b.capacity===undefined?20:b.capacity;if(!Number.isSafeInteger(capacity)||capacity<1||capacity>500)return null;
 const clean=(v,n)=>typeof v==='string'&&v.length<=n&&!/[\p{Cc}\p{Cf}<>]/u.test(v)&&!/(https?:|www\.|t\.me\/|@)/iu.test(v)?v.normalize('NFC').trim():'';
 const title=clean(b.title,100),city=clean(b.city,80),venue=clean(b.venue,120),description=clean(b.description,400);
 return title&&city&&venue&&description?{title,city,venue,description,kind:b.kind,starts_at:b.starts_at,capacity}:null;
}
