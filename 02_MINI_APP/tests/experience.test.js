import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read=n=>readFileSync(new URL('../public/'+n,import.meta.url),'utf8');
test('experience layer loads after signature styles and respects motion preferences',()=>{
 const html=read('index.html'),css=read('experience.css');
 assert.ok(html.indexOf('/experience.css?v=0260')>html.indexOf('/places.css?v=0255'));
 assert.match(css,/prefers-reduced-motion:no-preference/);
 assert.match(css,/prefers-reduced-motion:reduce/);
 assert.match(css,/--lumi-touch:44px/);
 assert.match(css,/:focus-visible/);
 assert.match(css,/font-weight:400;text-shadow:none/);
 assert.doesNotMatch(css,/clip-path|rotate:|transform:/);
});
