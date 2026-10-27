// Tests for assets/index.html + assets/app.js in a simulated browser (jsdom). Run:  npm install jsdom  &&  node test_page.js
const { JSDOM, VirtualConsole } = require('jsdom');
const fs = require('fs');
const path = require('path');
const assets = path.join(__dirname, '..', 'assets');
let problems = 0;
function expect(label, cond, detail) { console.log('  ' + (cond ? 'ok  ' : 'FAIL') + ' ' + label + (detail !== undefined ? '   [' + detail + ']' : '')); if (!cond) problems++; }

function makePage(confirmAnswer) {
  const html = fs.readFileSync(path.join(assets, 'index.html'), 'utf8').replace(/<script[^>]*><\/script>/g, '');
  const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://board.local:7000/', virtualConsole: new VirtualConsole() });
  const w = dom.window;
  const handlers = {}, emitted = [];
  w.io = () => ({ on: (e, f) => { handlers[e] = f; }, emit: (e, d) => emitted.push([e, d]) });
  w.confirm = () => confirmAnswer !== false;
  w.eval(fs.readFileSync(path.join(assets, 'app.js'), 'utf8'));
  const d = w.document;
  const $ = (id) => d.getElementById(id);
  const click = (el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  const type = (el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', { bubbles: true })); };
  const state = (o) => handlers.state(Object.assign({ mode: 'idle', label: '', subject: '', duration: 60, imu_rate: 100, imu_ok: true, samples: 0, countdown_left: 0, remaining: 0, progress: 0, recent_a: [1, 1.2, 2.5, 1], recent_g: [10, 20, 300, 5] }, o));
  return { w, d, $, click, type, state, handlers, emitted };
}
const last = (p, kind) => p.emitted.filter((e) => e[0] === kind).pop();

console.log('1. on load and connecting');
let p = makePage();
expect('four activity buttons', p.d.querySelectorAll('#labels button').length === 4);
expect('the page starts as "connecting" with START disabled', p.$('conn').textContent === 'connecting…' && p.$('start').disabled);
p.handlers.connect();
expect('connecting shows "connected" and asks the board to refresh', p.$('conn').textContent === 'connected' && p.$('conn').className.includes('good') && JSON.stringify(last(p, 'cmd')[1]) === '{"action":"refresh"}');
p.handlers.disconnect();
expect('a dropped connection shows "disconnected" in red', p.$('conn').textContent === 'disconnected' && p.$('conn').className.includes('bad'));

console.log('2. setting up a recording');
p = makePage();
p.state({});
expect('IMU chip shows the rate in green and the status says Ready', p.$('imu').textContent === 'IMU: 100/s' && p.$('imu').className.includes('good') && p.$('big').textContent === 'Ready');
expect('START is disabled with nothing chosen', p.$('start').disabled);
p.type(p.$('subject'), 'kendrick');
expect('...and with a person but no activity', p.$('start').disabled);
p.click(p.d.querySelector('[data-label="walk"]'));
expect('choosing Walking highlights it and enables START', p.d.querySelector('[data-label="walk"]').classList.contains('on') && !p.d.querySelector('[data-label="run"]').classList.contains('on') && !p.$('start').disabled);
p.click(p.d.querySelector('[data-seconds="120"]'));
expect('the 120 s quick button fills the duration', p.$('duration').value === '120');
p.type(p.$('note'), 'air-bike');
p.click(p.$('start'));
expect('START sends exactly what was chosen', JSON.stringify(last(p, 'cmd')[1]) === JSON.stringify({ action: 'start', subject: 'kendrick', label: 'walk', note: 'air-bike', duration: 120 }), JSON.stringify(last(p, 'cmd')[1]));
expect('the choices are remembered for next time', p.w.localStorage.getItem('gait.subject') === 'kendrick' && p.w.localStorage.getItem('gait.label') === 'walk');

console.log('3. countdown, recording, stop');
p.state({ mode: 'countdown', label: 'walk', subject: 'kendrick', countdown_left: 4 });
expect('the countdown number is shown big', p.$('big').textContent === '4' && p.$('sub').textContent.includes('walking'));
expect('during the countdown STOP works and the form is locked', !p.$('stop').disabled && p.$('start').disabled && p.$('subject').disabled && p.d.querySelector('[data-label="run"]').disabled);
p.state({ mode: 'recording', label: 'walk', subject: 'kendrick', remaining: 30, progress: 0.5, samples: 3000 });
expect('while recording: seconds left in red, bar half full, who and what are shown', p.$('big').textContent === '30' && p.$('big').classList.contains('rec') && p.$('fill').style.width === '50%' && p.$('sub').textContent.includes('Recording walking for kendrick') && p.$('sub').textContent.includes('3000 samples'));
p.click(p.$('stop'));
expect('STOP sends stop', JSON.stringify(last(p, 'cmd')[1]) === '{"action":"stop"}');
p.state({});
expect('back to idle: the form is unlocked again', !p.$('subject').disabled && p.$('stop').disabled && p.$('fill').style.width === '0%');

console.log('4. no IMU data');
p = makePage();
p.type(p.$('subject'), 'a'); p.click(p.d.querySelector('[data-label="run"]'));
p.state({ imu_rate: 0, imu_ok: false });
expect('"No IMU data" is shown in warning style, the chip is red, START is disabled', p.$('big').textContent === 'No IMU data' && p.$('big').classList.contains('warn') && p.$('imu').className.includes('bad') && p.$('start').disabled);

console.log('5. notices');
p.handlers.notice({ level: 'ok', text: 'Saved a__run__x.csv (60 s).' });
expect('a notice appears with its level', p.$('notice').textContent === 'Saved a__run__x.csv (60 s).' && p.$('notice').className === 'notice ok');

console.log('6. the file list, totals, delete');
const files = [
  { file: 'kendrick__walk__20261027-140007.csv', subject: 'kendrick', label: 'walk', note: 'fast', seconds: 60, samples: 6000, dropped: 0, lost_pct: 0, flagged: false },
  { file: 'kendrick__run__20261027-141000.csv', subject: 'kendrick', label: 'run', note: '', seconds: 30, samples: 2800, dropped: 200, lost_pct: 6.67, flagged: true }];
p.handlers.files({ files, totals: { kendrick: { walk: 60 }, ann: { still: 90, bike: 30.5 } }, zip: null });
const items = p.d.querySelectorAll('#files li.file');
expect('one row per file', items.length === 2);
expect('each has a download link under data/', items[0].querySelector('a').getAttribute('href') === 'data/kendrick__walk__20261027-140007.csv' && items[0].querySelector('a').hasAttribute('download'));
expect('a flagged file is marked and says to record again', items[1].classList.contains('flag') && items[1].textContent.includes('RECORD AGAIN') && !items[0].textContent.includes('RECORD AGAIN'));
expect('the row shows person, activity, length, samples and % lost', items[0].querySelector('.meta').textContent.includes('kendrick · walking · 60 s · 6000 samples · 0% lost'));
const rows = [...p.d.querySelectorAll('#totals tr')].map((tr) => [...tr.children].map((c) => c.textContent));
expect('totals: a header and one row per person with numbers for each activity', rows.length === 3 && rows[0].join() === 'person,still,walk,run,bike' && rows[1].join() === 'ann,90,0,0,30.5' && rows[2].join() === 'kendrick,0,60,0,0', JSON.stringify(rows));
p.click(items[1].querySelector('button'));
expect('Delete (confirmed) sends the file name', JSON.stringify(last(p, 'cmd')[1]) === JSON.stringify({ action: 'delete', file: files[1].file }));
const before = p.emitted.length; const q = makePage(false); q.handlers.files({ files, totals: {}, zip: null }); q.click(q.d.querySelector('#files li.file button'));
expect('Delete (not confirmed) sends nothing', !q.emitted.some((e) => e[1] && e[1].action === 'delete'));
p.handlers.files({ files: [], totals: {}, zip: null });
expect('an empty list says so', p.$('files').textContent === 'Nothing recorded yet.' && p.d.querySelector('#totals td').textContent === 'No data yet.');

console.log('7. a hostile file name is shown as text, never as HTML');
p.handlers.files({ files: [{ file: '<img src=x onerror=alert(1)>.csv', subject: '<b>x</b>', label: 'walk', note: '<script>1</script>', seconds: 5, samples: 500, dropped: 0, lost_pct: 0, flagged: false }], totals: { '<i>z</i>': { walk: 5 } }, zip: null });
expect('no element was created from it', !p.d.querySelector('#files img') && !p.d.querySelector('#files b') && !p.d.querySelector('#files script') && !p.d.querySelector('#totals i'));
expect('it is visible as plain text and the link is URL-encoded', p.$('files').textContent.includes('<img src=x onerror=alert(1)>.csv') && p.d.querySelector('#files a').getAttribute('href').startsWith('data/%3Cimg'));

console.log('8. the zip');
p.click(p.$('zip'));
expect('the zip button asks the board for a zip', JSON.stringify(last(p, 'cmd')[1]) === '{"action":"zip"}' && p.$('zipLink').hidden);
p.handlers.files({ files, totals: {}, zip: 'all_data.zip' });
expect('when it is ready the download link appears', !p.$('zipLink').hidden && p.$('zipLink').getAttribute('href') === 'data/all_data.zip');

console.log('9. the live plot');
p = makePage();
let threw = null;
try { p.state({ recent_a: [1, 2, 3], recent_g: [1, 2, 3] }); } catch (e) { threw = e; }
expect('with no canvas support (as in this simulated browser) a state message does not throw', threw === null, threw && threw.message);
const calls = { move: 0, line: 0, stroke: 0, ys: [], colors: [] };
const ctx = { setTransform() {}, clearRect() {}, beginPath() {}, moveTo(x, y) { calls.move++; calls.ys.push(y); }, lineTo(x, y) { calls.line++; calls.ys.push(y); }, stroke() { calls.stroke++; calls.colors.push(this.strokeStyle); }, set strokeStyle(v) { this._c = v; }, get strokeStyle() { return this._c; }, lineWidth: 1 };
p.$('wave').getContext = () => ctx;
const a = [1, 1.1, 0.9, 3.5, 6.5, 1.2, 1.0], g = [5, 10, 40, 800, 1200, 30, 8];
p.state({ recent_a: a, recent_g: g });
expect('it draws two lines (acceleration and rotation) with a point for every sample', calls.stroke === 2 && calls.move === 2 && calls.line === (a.length - 1) + (g.length - 1), JSON.stringify({ stroke: calls.stroke, move: calls.move, line: calls.line }));
expect('every point is inside the 120 px tall canvas, even a 6.5 g peak and a 1200 deg/s spike', calls.ys.every((y) => y >= 0 && y <= 120), 'y from ' + Math.min(...calls.ys).toFixed(1) + ' to ' + Math.max(...calls.ys).toFixed(1));
expect('the two lines have different colours', calls.colors[0] !== calls.colors[1], calls.colors.join(' / '));
const strokesBefore = calls.stroke; let threw2 = null;
try { p.state({ recent_a: [1], recent_g: [] }); } catch (e) { threw2 = e; }
expect('a plot with one point, or none, is skipped without error and draws no line', threw2 === null && calls.stroke === strokesBefore, threw2 && threw2.message);

console.log('\n' + (problems === 0 ? 'ALL PASSED' : 'SOME FAILED') + ' (' + problems + ' problem' + (problems === 1 ? '' : 's') + ')');
process.exit(problems ? 1 : 0);
