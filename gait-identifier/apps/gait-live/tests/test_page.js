// Tests for assets/index.html + assets/app.js in a simulated browser (jsdom).   npm install jsdom  &&  node test_page.js
const { JSDOM, VirtualConsole } = require('jsdom');
const fs = require('fs');
const path = require('path');
const assets = path.join(__dirname, '..', 'assets');
let problems = 0;
function expect(label, cond, detail) { console.log('  ' + (cond ? 'ok  ' : 'FAIL') + ' ' + label + (detail !== undefined ? '   [' + detail + ']' : '')); if (!cond) problems++; }

function makePage() {
  const html = fs.readFileSync(path.join(assets, 'index.html'), 'utf8').replace(/<script[^>]*><\/script>/g, '');
  const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://board.local:7000/', virtualConsole: new VirtualConsole() });
  const w = dom.window, handlers = {}, emitted = [];
  w.io = () => ({ on: (e, f) => { handlers[e] = f; }, emit: (e, d) => emitted.push([e, d]) });
  w.eval(fs.readFileSync(path.join(assets, 'app.js'), 'utf8'));
  const d = w.document, $ = (id) => d.getElementById(id);
  const click = (e) => e.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  const type = (e, v) => { e.value = v; e.dispatchEvent(new w.Event('input', { bubbles: true })); };
  const emptyTally = () => ({ windows: 0, a_correct: 0, b_correct: 0, by_label: { still: { n: 0, a: 0, b: 0 }, walk: { n: 0, a: 0, b: 0 }, run: { n: 0, a: 0, b: 0 }, bike: { n: 0, a: 0, b: 0 } }, disagree: { n: 0, a_right: 0, b_right: 0 } });
  const base = () => ({ mode: 'live', imu_rate: 100, warm: 1, skipped: 0, smooth: true, truth: null, person: '', tally: emptyTally(),
    segments: [{ label: 'still', lo: null, hi: -0.84 }, { label: 'walk', lo: -0.84, hi: -0.24 }, { label: 'run', lo: -0.24, hi: 0.27 }, { label: 'bike', lo: 0.27, hi: null }],
    gauge: [-1.1, 1.1], labels: ['still', 'walk', 'run', 'bike'], a: 'walk', b: 'walk', raw_a: 'walk', raw_b: 'walk', agree: true, a_name: 'ax_max', a_value: -0.41,
    a_path: [{ name: 'ax_max', text: 'highest ax', unit: 'g', value: -0.41, threshold: -0.84, yes: false }, { name: 'ax_max', text: 'highest ax', unit: 'g', value: -0.41, threshold: 0.27, yes: true }, { name: 'ax_max', text: 'highest ax', unit: 'g', value: -0.41, threshold: -0.24, yes: true }],
    b_path: [{ name: 'ay_min', text: 'lowest ay', unit: 'g', value: -3.2, threshold: -0.5, yes: true }, { name: 'acc_mean', text: 'average total acceleration', unit: 'g', value: 1.1, threshold: 1.22, yes: true },
             { name: 'gyro_std', text: 'spread of rotation speed', unit: 'deg/s', value: 60, threshold: 97, yes: true }, { name: 'gz_min', text: 'lowest gz', unit: 'deg/s', value: -120, threshold: -185, yes: false }],
    recent_ax: [-1, -0.8, -0.4, -1.2, -0.9], recent_g: [10, 120, 300, 80, 20], hist_a: [1, 1, 2], hist_b: [1, 1, 1] });
  const state = (o) => handlers.state(Object.assign(base(), o || {}));
  return { w, d, $, click, type, state, handlers, emitted, base, emptyTally };
}
const last = (p, k) => p.emitted.filter((e) => e[0] === k).pop();

console.log('1. connecting');
let p = makePage();
p.handlers.connect();
expect('"connected" in green, and it asks the board for the state', p.$('conn').textContent === 'connected' && p.$('conn').className.includes('good') && JSON.stringify(last(p, 'cmd')[1]) === '{"action":"refresh"}');
p.handlers.disconnect();
expect('a dropped connection is shown in red', p.$('conn').textContent === 'disconnected' && p.$('conn').className.includes('bad'));

console.log('2. no data and warming up');
p = makePage();
p.state({ mode: 'nodata', imu_rate: 0, a: null, b: null, raw_a: null, raw_b: null, agree: null, a_value: null, a_path: [], b_path: [], hist_a: [], hist_b: [] });
expect('"No IMU data" in the warning style, the chip red, both labels empty, no marker, no paths, no agreement banner',
  p.$('statusText').textContent.startsWith('No IMU data') && p.$('status').classList.contains('bad') && p.$('imu').className.includes('bad') && p.$('labelA').textContent === '—' && p.$('labelB').className === 'label none'
  && !p.d.querySelector('.marker') && p.$('pathA').children.length === 0 && p.$('agree').textContent === '');
p.state({ mode: 'warming', warm: 0.45, a: null, b: null, a_value: null, a_path: [], b_path: [] });
expect('warming up: the message and a progress bar at 45%', p.$('statusText').textContent.includes('first 2 seconds') && !p.$('warmBar').hidden && p.$('warmFill').style.width === '45%');
p.state({});
expect('live: the bar is hidden again and the message says how the labels are made', p.$('warmBar').hidden && p.$('statusText').textContent.includes('smoothed'));
p.state({ skipped: 3, smooth: false });
expect('raw labels and skipped windows are mentioned', p.$('statusText').textContent.includes('raw labels') && p.$('statusText').textContent.includes('skipped for lost samples: 3'));

console.log('3. the two answers');
p = makePage();
p.state({ a: 'walk', b: 'run', raw_a: 'run', raw_b: 'run', agree: false });
expect('each label is shown in its own activity colour class', p.$('labelA').textContent === 'walk' && p.$('labelA').className === 'label l1' && p.$('labelB').textContent === 'run' && p.$('labelB').className === 'label l2');
expect('when the raw answer differs from the smoothed one it says so, otherwise it says nothing', p.$('rawA').textContent === 'this half second: run' && p.$('rawB').textContent === '');
expect('disagreement is announced in amber', p.$('agree').textContent === 'The models disagree' && p.$('agree').className === 'agree warn');
p.state({});
expect('agreement is announced in green', p.$('agree').textContent === 'Both models agree' && p.$('agree').className === 'agree good');

console.log("4. Model A's number line");
const segs = [...p.d.querySelectorAll('#gauge .seg')];
const widths = segs.map((e) => parseFloat(e.style.width));
expect('four stretches in order, coloured and named', segs.map((e) => e.textContent).join() === 'still,walk,run,bike' && segs.map((e) => e.className).join() === 'seg l0,seg l1,seg l2,seg l3');
expect('their widths follow the thresholds: 0.26, 0.60, 0.51 and 0.83 of a 2.2 g line', Math.abs(widths[0] - 11.8) < 0.2 && Math.abs(widths[1] - 27.3) < 0.2 && Math.abs(widths[2] - 23.2) < 0.2 && Math.abs(widths[3] - 37.7) < 0.2 && Math.abs(widths.reduce((a, b) => a + b) - 100) < 0.01, widths.map((v) => v.toFixed(1)).join(' / '));
expect('the marker sits where -0.41 g is (31.4% along) and the value is written', Math.abs(parseFloat(p.d.querySelector('.marker').style.left) - 31.4) < 0.1 && p.$('gaugeValue').textContent === 'ax_max = -0.41 g');
p.state({ a_value: 5 }); expect('a value above the line is held at the right end', p.d.querySelector('.marker').style.left === '100%');
p.state({ a_value: -9 }); expect('a value below it is held at the left end', p.d.querySelector('.marker').style.left === '0%');

console.log('5. how each tree decided');
p.state({});
const liA = [...p.d.querySelectorAll('#pathA li')], liB = [...p.d.querySelectorAll('#pathB li')];
expect('Model A asked 3 questions and Model B 4', liA.length === 3 && liB.length === 4);
expect('a question reads as words, the value, the threshold and the answer', liB[0].textContent === 'lowest ay = -3.2 g  (at most -0.5? yes)' && liA[0].textContent === 'highest ax = -0.41 g  (at most -0.84? no)', liB[0].textContent);
expect('the yes and no answers are marked so they can be coloured', liA[0].querySelector('span.no') && liA[1].querySelector('span.yes'));

console.log('6. the 60 second history strips');
expect('each strip always has 120 blocks', p.$('histA').children.length === 120 && p.$('histB').children.length === 120);
const cells = [...p.$('histA').children];
expect('the newest answers sit at the right edge, the rest are empty', cells.slice(0, 117).every((c) => c.className === 'cell') && cells.slice(117).map((c) => c.className).join() === 'cell l1,cell l1,cell l2');
p.state({ hist_a: [1, -1, 3] });
expect('an answer of -1 (none) is an empty block', [...p.$('histA').children].slice(117).map((c) => c.className).join() === 'cell l1,cell,cell l3');
p.state({ hist_a: new Array(120).fill(0) });
expect('a full minute fills the strip', [...p.$('histA').children].every((c) => c.className === 'cell l0'));

console.log('7. the sensor plot');
const calls = { stroke: 0, dashed: 0, ys: [] }, ctx = { dash: false, setTransform() {}, clearRect() {}, beginPath() {}, moveTo(x, y) { calls.ys.push(y); }, lineTo(x, y) { calls.ys.push(y); },
  setLineDash(d) { this.dash = d.length > 0; }, stroke() { calls.stroke++; if (this.dash) calls.dashed++; }, set strokeStyle(v) { this._c = v; }, get strokeStyle() { return this._c; }, lineWidth: 1 };
p.$('wave').getContext = () => ctx;
p.state({ recent_ax: [-1, -0.5, 0.2, -3.9, 1.5], recent_g: [10, 900, 300, 80, 20] });
expect("Model A's three thresholds are drawn once each as dashed lines, plus the two signal lines", calls.stroke === 5 && calls.dashed === 3, JSON.stringify({ stroke: calls.stroke, dashed: calls.dashed }));
expect('every point is inside the canvas, even a -3.9 g spike and a 900 deg/s burst', calls.ys.every((y) => y >= 0 && y <= 130), 'y from ' + Math.min(...calls.ys).toFixed(1) + ' to ' + Math.max(...calls.ys).toFixed(1));
let threw = null; const q = makePage(); try { q.state({ recent_ax: [1], recent_g: [] }); } catch (e) { threw = e; }
expect('no canvas, or a one-point signal, does not throw', threw === null);

console.log('8. test mode: choosing, naming, switching');
p = makePage(); p.state({});
p.click(p.d.querySelector('[data-truth="run"]'));
expect('tapping an activity tells the board what the person is really doing', JSON.stringify(last(p, 'cmd')[1]) === '{"action":"truth","label":"run"}');
p.click(p.d.querySelector('[data-truth=""]'));
expect('"Not testing" sends an empty choice', JSON.stringify(last(p, 'cmd')[1]) === '{"action":"truth","label":""}');
p.state({ truth: 'run' });
expect('the board\'s current choice is highlighted, and only that one', [...p.d.querySelectorAll('#truth button.on')].map((b) => b.dataset.truth).join() === 'run');
p.state({ truth: null });
expect('with no choice, "Not testing" is highlighted', [...p.d.querySelectorAll('#truth button.on')].map((b) => b.dataset.truth).join() === '');
p.type(p.$('person'), 'Marie');
expect('typing a name sends it', JSON.stringify(last(p, 'cmd')[1]) === '{"action":"person","name":"Marie"}');
p.$('person').focus(); p.state({ person: 'Someone else' });
expect('the name box is not overwritten while you are typing in it', p.$('person').value === 'Marie');
p.$('person').blur(); p.state({ person: 'Someone else' });
expect('but it follows the board when you are not', p.$('person').value === 'Someone else');
p.$('smooth').checked = false; p.$('smooth').dispatchEvent(new p.w.Event('change', { bubbles: true }));
expect('the smoothing switch is sent', JSON.stringify(last(p, 'cmd')[1]) === '{"action":"smooth","on":false}');
p.click(p.$('reset'));
expect('"Clear scores" is sent', JSON.stringify(last(p, 'cmd')[1]) === '{"action":"reset"}');
expect('the log can be downloaded', p.$('logLink').getAttribute('href') === 'data/live_log.csv' && p.$('logLink').hasAttribute('download'));

console.log('9. the scoreboard');
p = makePage();
p.state({ truth: 'walk' });
expect('chosen but nothing scored yet: it says scoring starts soon', p.$('score').textContent.includes('Scoring starts'));
p.state({ truth: null });
expect('nothing chosen: it says what to do', p.$('score').textContent.includes('Choose what the person is really doing'));
const t = p.emptyTally(); Object.assign(t, { windows: 200, a_correct: 140, b_correct: 190, disagree: { n: 50, a_right: 10, b_right: 40 } });
t.by_label.walk = { n: 100, a: 80, b: 99 }; t.by_label.run = { n: 100, a: 60, b: 91 };
p.state({ truth: 'run', tally: t });
const boxes = [...p.d.querySelectorAll('#score div')];
expect('each model gets its percentage and the number of windows', boxes.length === 2 && boxes[0].textContent === '70%Model A · 200 windows' && boxes[1].textContent === '95%Model B · 200 windows', boxes.map((b) => b.textContent).join(' | '));
const rows = [...p.d.querySelectorAll('#byLabel tr')].map((r) => [...r.children].map((c) => c.textContent).join('/'));
expect('a table per activity, with a dash where nothing was scored', rows.length === 5 && rows[2] === 'walk/100/80%/99%' && rows[3] === 'run/100/60%/91%' && rows[1] === 'still/0/—/—' && rows[4] === 'bike/0/—/—', rows.join(' | '));
expect('the disagreement sentence has the shares', p.$('disagree').textContent === 'They disagreed on 25% of the windows. When they did, Model A was right 20% of the time and Model B 80%.', p.$('disagree').textContent);
t.disagree = { n: 0, a_right: 0, b_right: 0 }; p.state({ truth: 'run', tally: t });
expect('no disagreements is said plainly', p.$('disagree').textContent === 'They never disagreed.');

console.log('10. nothing sent by the board is ever treated as HTML');
p = makePage();
p.state({ person: '<img src=x onerror=alert(1)>', b_path: [{ name: 'x', text: '<b>bold</b>', unit: '<i>u</i>', value: 1, threshold: 2, yes: true }], a: '<img src=y>', segments: [{ label: '<u>x</u>', lo: null, hi: null }] });
p.handlers.notice({ level: 'warn', text: '<script>1</script> careful' });
expect('no element was created from a name, a question, a label, a stretch name or a notice',
  !p.d.querySelector('img') && !p.d.querySelector('#pathB b') && !p.d.querySelector('#pathB i') && !p.d.querySelector('script:not([src])') && !p.d.querySelector('#gauge u') && !p.d.querySelector('#notice script'));
expect('they are shown as plain text', p.$('person').value === '<img src=x onerror=alert(1)>' && p.$('notice').textContent === '<script>1</script> careful' && p.$('pathB').textContent.includes('<b>bold</b>'));

console.log('\n' + (problems === 0 ? 'ALL PASSED' : 'SOME FAILED') + ' (' + problems + ' problem' + (problems === 1 ? '' : 's') + ')');
process.exit(problems ? 1 : 0);
