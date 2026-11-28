import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {Script} from 'node:vm';
import {resolve, dirname, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../public/',import.meta.url));
const read=name=>readFileSync(resolve(root,name),'utf8');
const html=read('index.html');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
function asset(url, from='index.html'){
 if (/^(?:https?:|data:|blob:|#)/i.test(url)) return;
 const path=resolve(url.startsWith('/')?root:dirname(resolve(root,from)),url.replace(/^\//,'').split(/[?#]/)[0]);
 assert.ok(path.startsWith(resolve(root)+sep),`asset outside public: ${url}`);
 assert.ok(statSync(path).isFile(),`missing asset: ${url}`);
}
test('HTML IDs are unique and static JavaScript DOM targets exist',()=>{
 assert.equal(new Set(ids).size,ids.length);
 for(const name of readdirSync(root).filter(n=>n.endsWith('.js'))){
  for(const [,id] of read(name).matchAll(/getElementById\(\s*['"]([^'"]+)['"]\s*\)/g)) assert.ok(ids.includes(id),`${name}: ${id}`);
 }
 for(const id of ['home-dating','home-duel','home-games','open-collection','home-gift','home-invite','home-safety','tab-home','tab-duel','tab-morning','tab-heroes','tab-about']) assert.ok(ids.includes(id),id);
});
test('local HTML and CSS assets are shipped',()=>{
 for(const [,url] of html.matchAll(/<(?:script|img|link)\b[^>]*?\b(?:src|href)="([^"]+)"/g)) asset(url);
 for(const name of readdirSync(root).filter(n=>n.endsWith('.css'))){
  for(const [,url] of read(name).matchAll(/url\(([^)]+)\)/g)) asset(url.trim().replace(/^['"]|['"]$/g,''),name);
 }
});
test('inline scripts parse and match CSP hashes',()=>{
 const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
 assert.ok(scripts.length);
 const policy=read('_headers').match(/Content-Security-Policy:([^\n]+)/)[1];
 const directive=policy.split(';').find(v=>v.trim().startsWith('script-src '));
 assert.ok(directive);
 for(const source of scripts){new Script(source);assert.ok(directive.includes(`'sha256-${createHash('sha256').update(source).digest('base64')}'`));}
 assert.ok(!directive.includes("'unsafe-inline'"));
});
