import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const html=readFileSync(new URL('../public/index.html',import.meta.url),'utf8');
test('create and join errors appear in the visible home screen',()=>{
 assert.match(html,/id="duel-error"/);
 assert.match(html,/\.catch\(e=>showDuelError\(/);
 assert.match(html,/function clearDuelError/);
});
