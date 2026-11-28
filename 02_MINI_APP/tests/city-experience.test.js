import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const html=readFileSync(new URL('../public/index.html',import.meta.url),'utf8');
const css=readFileSync(new URL('../public/places.css',import.meta.url),'utf8');
test('city collection has separate headline and flat supporting copy, four safe external search links',()=>{
assert.match(html,/<h2 id="places-title">ТВОЙ ГОРОД\.<\/h2><p class="city-subtitle">/);
assert.match(css,/\.city-subtitle\{[^}]*font-weight:400[^}]*text-shadow:none/);
const section=html.split('<details id="city-experience"')[1].split('</details>')[0];
assert.equal((section.match(/class="places-item"/g)||[]).length,4);
assert.equal((section.match(/href="https:\/\/www\.google\.com\/maps\/search\/[^\"]+" target="_blank" rel="noopener noreferrer"/g)||[]).length,4);
assert.match(section,/не список проверенных заведений/);
});
