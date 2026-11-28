import test from 'node:test';import assert from 'node:assert/strict';
import {getPuzzle,publicPuzzle,pointsFor,ROUND_COUNT} from '../src/game.js';
const code='ab12cd34ef56ab12cd34ef56';
test('deterministic five puzzles with valid choices',()=>{
 for(let i=0;i<ROUND_COUNT;i++){
  const p=getPuzzle(code,i);assert.equal(p.options.length,4);assert.ok(p.answer>=0&&p.answer<4);
  assert.deepEqual(getPuzzle(code,i),p);
  assert.equal(Object.hasOwn(publicPuzzle(p),'answer'),false);
 }
});
test('server scoring bounds',()=>{assert.equal(pointsFor(false,0),0);assert.equal(pointsFor(true,0),150);assert.equal(pointsFor(true,100),100);});
