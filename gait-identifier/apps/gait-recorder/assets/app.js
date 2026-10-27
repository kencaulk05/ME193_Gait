// Gait Recorder page. Talks to main.py through socket.io: it sends 'cmd' and receives 'state', 'files' and 'notice'.
(function () {
  const socket = io(window.location.origin);
  const $ = (id) => document.getElementById(id);
  const NAMES = { still: 'standing still', walk: 'walking', run: 'running', bike: 'biking' };
  const store = {
    get(k, d) { try { const v = window.localStorage.getItem('gait.' + k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { window.localStorage.setItem('gait.' + k, v); } catch (e) { /* private mode: just do not remember */ } }
  };
  let label = store.get('label', '');
  let mode = 'idle';
  let imuOk = false;

  // ---- the form ----
  $('subject').value = store.get('subject', '');
  $('duration').value = store.get('duration', '60');
  $('note').value = store.get('note', '');
  function showLabel() {
    document.querySelectorAll('#labels button').forEach((b) => b.classList.toggle('on', b.dataset.label === label));
    updateButtons();
  }
  document.querySelectorAll('#labels button').forEach((b) => b.addEventListener('click', () => { label = b.dataset.label; store.set('label', label); showLabel(); }));
  document.querySelectorAll('.quick button').forEach((b) => b.addEventListener('click', () => { $('duration').value = b.dataset.seconds; store.set('duration', b.dataset.seconds); }));
  ['subject', 'duration', 'note'].forEach((id) => $(id).addEventListener('input', () => { store.set(id, $(id).value); updateButtons(); }));

  function updateButtons() {
    const idle = mode === 'idle';
    $('start').disabled = !(idle && label && $('subject').value.trim() && imuOk);
    $('stop').disabled = idle;
    document.querySelectorAll('#setup input, #setup button').forEach((el) => { el.disabled = !idle; });
  }

  $('start').addEventListener('click', () => {
    socket.emit('cmd', { action: 'start', subject: $('subject').value.trim(), label: label, note: $('note').value.trim(), duration: Number($('duration').value) });
  });
  $('stop').addEventListener('click', () => socket.emit('cmd', { action: 'stop' }));
  $('zip').addEventListener('click', () => { $('zipLink').hidden = true; socket.emit('cmd', { action: 'zip' }); });

  // ---- messages from the board ----
  socket.on('connect', () => { $('conn').textContent = 'connected'; $('conn').className = 'chip good'; socket.emit('cmd', { action: 'refresh' }); });
  socket.on('disconnect', () => { $('conn').textContent = 'disconnected'; $('conn').className = 'chip bad'; });

  socket.on('state', (s) => {
    mode = s.mode;
    imuOk = !!s.imu_ok;
    $('imu').textContent = 'IMU: ' + s.imu_rate + '/s';
    $('imu').className = 'chip ' + (imuOk ? 'good' : 'bad');
    const big = $('big'), sub = $('sub');
    big.className = 'big';
    if (s.mode === 'countdown') {
      big.textContent = String(s.countdown_left);
      sub.textContent = 'Get into position: ' + (NAMES[s.label] || s.label) + ' starts when this reaches 0.';
      $('fill').style.width = '0%';
    } else if (s.mode === 'recording') {
      big.textContent = String(s.remaining);
      big.classList.add('rec');
      sub.textContent = 'Recording ' + (NAMES[s.label] || s.label) + ' for ' + s.subject + '. ' + s.samples + ' samples.';
      $('fill').style.width = Math.round(s.progress * 100) + '%';
    } else {
      $('fill').style.width = '0%';
      if (imuOk) { big.textContent = 'Ready'; sub.textContent = 'Pick a person and an activity, then press START.'; }
      else { big.textContent = 'No IMU data'; big.classList.add('warn'); sub.textContent = 'Nothing is arriving from the sensor: check the wiring and the board.'; }
    }
    updateButtons();
    drawWave(s.recent_a || [], s.recent_g || []);
  });

  socket.on('notice', (n) => { const el = $('notice'); el.className = 'notice ' + (n.level || 'info'); el.textContent = n.text; });

  socket.on('files', (m) => {
    renderFiles(m.files || []);
    renderTotals(m.totals || {});
    if (m.zip) { const a = $('zipLink'); a.href = 'data/' + m.zip; a.hidden = false; }
  });

  function renderFiles(files) {
    const ul = $('files');
    ul.textContent = '';
    if (!files.length) { const li = document.createElement('li'); li.textContent = 'Nothing recorded yet.'; ul.appendChild(li); return; }
    files.forEach((f) => {
      const li = document.createElement('li');
      li.className = 'file' + (f.flagged ? ' flag' : '');
      const a = document.createElement('a');
      a.href = 'data/' + encodeURIComponent(f.file);
      a.download = f.file;
      a.textContent = f.file;
      const meta = document.createElement('span');
      meta.className = 'meta';
      meta.textContent = f.subject + ' · ' + (NAMES[f.label] || f.label) + ' · ' + f.seconds + ' s · ' + f.samples + ' samples · ' + f.lost_pct + '% lost' + (f.flagged ? ' · RECORD AGAIN' : '') + (f.note ? ' · ' + f.note : '');
      const del = document.createElement('button');
      del.type = 'button';
      del.textContent = 'Delete';
      del.addEventListener('click', () => { if (window.confirm('Delete ' + f.file + '?')) socket.emit('cmd', { action: 'delete', file: f.file }); });
      li.appendChild(a); li.appendChild(meta); li.appendChild(del);
      ul.appendChild(li);
    });
  }

  function renderTotals(totals) {
    const body = document.querySelector('#totals tbody');
    body.textContent = '';
    const people = Object.keys(totals).sort();
    const head = document.createElement('tr');
    ['person', 'still', 'walk', 'run', 'bike'].forEach((h) => { const th = document.createElement('th'); th.textContent = h; head.appendChild(th); });
    body.appendChild(head);
    if (!people.length) { const tr = document.createElement('tr'); const td = document.createElement('td'); td.colSpan = 5; td.textContent = 'No data yet.'; tr.appendChild(td); body.appendChild(tr); return; }
    people.forEach((p) => {
      const tr = document.createElement('tr');
      const first = document.createElement('td'); first.textContent = p; tr.appendChild(first);
      ['still', 'walk', 'run', 'bike'].forEach((l) => { const td = document.createElement('td'); td.textContent = String(totals[p][l] || 0); tr.appendChild(td); });
      body.appendChild(tr);
    });
  }

  // ---- the live plot ----
  function drawWave(a, g) {
    const canvas = $('wave');
    const ctx = canvas.getContext ? canvas.getContext('2d') : null;
    if (!ctx) return;
    const ratio = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 300, h = 120;
    canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const style = getComputedStyle(document.documentElement);
    function line(values, top, color) {
      if (values.length < 2) return;
      ctx.beginPath();
      values.forEach((v, i) => { const x = (i / (values.length - 1)) * w, y = h - 4 - (Math.min(v, top) / top) * (h - 8); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    }
    line(g, Math.max(500, ...g), (style.getPropertyValue('--gyro') || '#d1862b').trim());
    line(a, Math.max(4, ...a), (style.getPropertyValue('--accel') || '#1f6feb').trim());
  }

  showLabel();
  updateButtons();
})();
