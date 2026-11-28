export const roles=['founder','investor','expert','mentor','other'];
export const goals=['partners','startup','learning'];
const fields=['name','role','sector','skills','goal','consent'];
export function validateProfile(b){
 if(!b||typeof b!=='object'||Array.isArray(b)||Object.keys(b).some(k=>!fields.includes(k))||b.consent!==true||!roles.includes(b.role)||!goals.includes(b.goal))return null;
 const clean=(v,max)=>{if(typeof v!=='string'||v.length>max||/[\p{Cc}\p{Cf}]/u.test(v))return null;const s=v.normalize('NFC').trim().replace(/\s+/gu,' ');return s.length<=max&&!/(https?:|www\.|t\.me\/|@|[<>]|\b\d{7,}\b)/iu.test(s)?s:null;};
 const name=clean(b.name,60),sector=clean(b.sector,80),skills=clean(b.skills,180);
 return name&&sector&&skills!==null?{name,role:b.role,sector,skills,goal:b.goal}:null;
}
