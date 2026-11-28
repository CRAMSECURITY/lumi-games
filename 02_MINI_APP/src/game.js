// No answers or scoring authority is accepted from the browser.
export const ROUND_SECONDS = 60;
export const ROUND_COUNT = 5;
const puzzles = [
 {kind:'sequence', title:'Числовой код', question:'2 · 4 · 8 · 16 · ?', options:['24','32','30','36'], answer:1},
 {kind:'math', title:'Математическая дуэль', question:'(7 × 6) − 9 = ?', options:['35','31','33','29'], answer:2},
 {kind:'word', title:'Секретное слово', question:'Собери слово из букв «Г И Н К А»', options:['КНИГА','ГРИВА','НИТКА','КАНАТ'], answer:0},
 {kind:'sequence', title:'Найди закономерность', question:'1 · 1 · 2 · 3 · 5 · ?', options:['7','8','9','10'], answer:1},
 {kind:'logic', title:'Внимательность', question:'Три лампы горят. Две выключили. Сколько ламп осталось?', options:['1','2','3','0'], answer:2},
 {kind:'word', title:'Анаграмма', question:'Собери слово из букв «К О Ш К А»', options:['КОШКА','КОРОВА','КОМАР','КРОШКА'], answer:0},
 {kind:'math', title:'Быстрый счёт', question:'15 + 18 − 7 = ?', options:['24','25','26','27'], answer:2},
 {kind:'logic', title:'Логическая задачка', question:'У двух сестёр по одному брату. Сколько всего детей?', options:['3','4','2','5'], answer:0},
 {kind:'sequence', title:'Числовой ряд', question:'3 · 6 · 12 · 24 · ?', options:['30','36','42','48'], answer:3},
 {kind:'word', title:'Анаграмма', question:'Собери слово из букв «Л У Н А»', options:['ЛИНА','ЛУНА','ЛИАН','ЛАНА'], answer:1},
 {kind:'logic', title:'Кто быстрее?', question:'Какой месяц имеет 28 дней?', options:['Только февраль','Все месяцы','Только январь','Ни один'], answer:1},
 {kind:'math', title:'Считаем устно', question:'(9 + 3) × 2 = ?', options:['21','22','24','26'], answer:2},
 {kind:'sequence', title:'Продолжи ряд', question:'5 · 10 · 20 · 40 · ?', options:['60','70','75','80'], answer:3},
 {kind:'logic', title:'Вопрос с подвохом', question:'Сколько раз можно вычесть 10 из 100?', options:['Один','Два','Десять','Бесконечно'], answer:0},
 {kind:'math', title:'Умножение', question:'8 × 7 − 6 = ?', options:['48','50','52','54'], answer:1}
];
export function getPuzzle(roomId, round) {
 if(!/^[a-f0-9]{24}$/.test(roomId) || round < 0 || round >= ROUND_COUNT) throw new Error('bad puzzle');
 let seed = 0;
 for(let i=0;i<roomId.length;i++) seed=(Math.imul(seed,31)+roomId.charCodeAt(i))>>>0;
 const offset=seed%3;
 const p=puzzles[(round*3+offset)%puzzles.length];
 return {kind:p.kind,title:p.title,question:p.question,options:p.options,answer:p.answer};
}
export function pointsFor(correct, elapsedSeconds) {
 return correct ? 100+Math.max(0, 50-Math.floor(Math.max(0,elapsedSeconds))) : 0;
}
export function publicPuzzle(p) {const {answer,...safe}=p;return safe;}
