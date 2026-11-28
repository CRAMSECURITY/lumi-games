import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const code='a'.repeat(24), key='lumi_room_v2_42';
const script=readFileSync(new URL('../public/index.html',import.meta.url),'utf8').split('<script>')[1].split('</script>')[0];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function boot({failFirst=false,status=0}={}){
 const els=new Map(), storage=new Map([[key,code]]), callbacks={}, intervals=new Map();let seq=0, requests=0, share='';
 const element=()=>({classList:{toggle(){}},style:{},children:[],replaceChildren(){this.children=[]},append(b){this.children.push(b)},scrollIntoView(){}});
 const get=id=>{if(!els.has(id))els.set(id,element());return els.get(id)};
 const localStorage={getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
 const tg={initData:'fixture',initDataUnsafe:{user:{id:42}},openTelegramLink:url=>share=url};
 const room={id:code,status:'playing',round:2,total:5,seconds_left:25,you:'host',players:{host:{score:120},guest:{score:80}},puzzle:{title:'Puzzle',question:'Question',options:['a','b','c','d']},answered:false};
 vm.runInNewContext(script,{window:{Telegram:{WebApp:tg},addEventListener:(n,f)=>callbacks[n]=f},document:{getElementById:get,createElement:element,addEventListener:(n,f)=>callbacks[n]=f},localStorage,sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},location:{href:'https://example.test'},URL,encodeURIComponent,AbortSignal,performance:{now:()=>1000},setInterval:(f,ms)=>{intervals.set(++seq,{f,ms});return seq},clearInterval:id=>intervals.delete(id),fetch:async path=>{if(path==='/api/session')return {ok:true,json:async()=>({authenticated:true,token:"fixture-session"})};requests++;if(failFirst&&requests===1)throw Error('offline');if(status)return {ok:false,status,json:async()=>({error:'denied'})};return {ok:true,json:async()=>({room})}}});
 return {get,storage,callbacks,intervals,requests:()=>requests,share:()=>share};
}
test('saved room recovers after transient network error, restores score and shares code',async()=>{
 const b=boot({failFirst:true});await flush();assert.equal(b.storage.get(key),code);assert.match(b.get('duel-error').textContent,/Связь потеряна/);b.callbacks.online();await flush();assert.equal(b.get('myscore').textContent,120);assert.equal(b.get('round-num').textContent,'Раунд 3/5');b.get('invite').onclick();assert.match(decodeURIComponent(b.share()),new RegExp(code));b.get('leave').onclick();assert.equal(b.storage.has(key),false);b.callbacks.online();await flush();assert.equal(b.requests(),2);
});
test('invalid saved room is cleared only for permanent denial',async()=>{const b=boot({status:403});await flush();assert.equal(b.storage.has(key),false);assert.equal(b.get('duel-error').textContent,'denied')});
test('expired authorization preserves saved room for reopening',async()=>{const b=boot({status:401});await flush();assert.equal(b.storage.get(key),code);assert.match(b.get('duel-error').textContent,/Сессия истекла/);assert.equal([...b.intervals.values()].filter(x=>x.ms===2500).length,0)});
