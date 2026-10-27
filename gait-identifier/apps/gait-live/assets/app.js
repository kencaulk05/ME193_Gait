// Gait Live page. Talks to main.py through socket.io: it sends 'cmd' and receives 'state' and 'notice'.
(function () {
  const socket = io(window.location.origin);
  const $ = (id) => document.getElementById(id);
  const LABELS = ['still', 'walk', 'run', 'bike'];
  const HISTORY = 120;
  const pct = (x) => Math.round(100 * x);
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }

  // ---- what the page sends ----
  document.querySelectorAll('#truth button').forEach((b) => b.addEventListener('click', () => socket.emit('cmd', { action: 'truth', label: b.dataset.truth })));
  $('person').addEventListener('input', () => socket.emit('cmd', { action: 'person', name: $('person').value }));
  $('smooth').addEventListener('change', () => socket.emit('cmd', { action: 'smooth', on: $('smooth').checked }));
  $('reset').addEventListener('click', () => socket.emit('cmd', { action: 'reset' }));

  // ---- what the board sends ----
  socket.on('connect', () => { $('conn').textContent = 'connected'; $('conn').className = 'chip good'; socket.emit('cmd', { action: 'refresh' }); });
  socket.on('disconnect', () => { $('conn').textContent = 'disconnected'; $('conn').className = 'chip bad'; });
  socket.on('notice', (n) => { const e = $('notice'); e.className = 'notice ' + (n.level || 'info'); e.textContent = n.text; });
  socket.on('state', (s) => {
    $('imu').textContent = 'IMU: ' + s.imu_rate + '/s';
    $('imu').className = 'chip ' + (s.imu_rate >= 80 ? 'good' : 'bad');
    renderStatus(s); renderModels(s); renderAgree(s); renderHistory(s); renderPlot(s); renderTest(s);
  });

  function renderStatus(s) {
    const box = $('status'), text = $('statusText');
    box.className = 'status';
    $('warmBar').hidden = true;
    if (s.mode === 'nodata') { box.classList.add('bad'); text.textContent = 'No IMU data: check the sensor and the board.'; }
    else if (s.mode === 'warming') { text.textContent = 'Collecting the first 2 seconds of data…'; $('warmBar').hidden = false; $('warmFill').style.width = pct(s.warm) + '%'; }
    else { text.textContent = 'Live: a new answer every half second (' + (s.smooth ? 'big labels smoothed over 1.5 s' : 'raw labels') + ')' + (s.skipped ? ' · windows skipped for lost samples: ' + s.skipped : ''); }
  }

  function setLabel(id, rawId, shown, raw, live) {
    const i = LABELS.indexOf(shown);
    $(id).className = 'label ' + (i >= 0 ? 'l' + i : 'none');
    $(id).textContent = i >= 0 ? shown : '—';
    $(rawId).textContent = live && raw && raw !== shown ? 'this half second: ' + raw : '';
  }

  function renderPath(listId, steps) {
    const ol = $(listId);
    ol.textContent = '';
    steps.forEach((st) => {
      const li = el('li');
      li.appendChild(document.createTextNode(st.text + ' = ' + st.value + (st.unit ? ' ' + st.unit : '') + '  (at most ' + st.threshold + '? '));
      li.appendChild(el('span', st.yes ? 'yes' : 'no', st.yes ? 'yes' : 'no'));
      li.appendChild(document.createTextNode(')'));
      ol.appendChild(li);
    });
  }

  function renderModels(s) {
    const live = s.mode === 'live';
    setLabel('labelA', 'rawA', s.a, s.raw_a, live);
    setLabel('labelB', 'rawB', s.b, s.raw_b, live);
    const gauge = $('gauge'), g = s.gauge || [-1, 1], span = g[1] - g[0];
    gauge.textContent = '';
    (s.segments || []).forEach((seg) => {
      const lo = seg.lo === null ? g[0] : Math.max(seg.lo, g[0]), hi = seg.hi === null ? g[1] : Math.min(seg.hi, g[1]);
      const d = el('div', 'seg l' + LABELS.indexOf(seg.label), seg.label);
      d.style.width = ((hi - lo) / span * 100) + '%';
      gauge.appendChild(d);
    });
    if (live && s.a_value !== null) {
      const m = el('div', 'marker');
      m.style.left = (Math.min(1, Math.max(0, (s.a_value - g[0]) / span)) * 100) + '%';
      gauge.appendChild(m);
      $('gaugeValue').textContent = s.a_name + ' = ' + s.a_value.toFixed(2) + ' g';
    } else { $('gaugeValue').textContent = ''; }
    renderPath('pathA', live ? s.a_path : []);
    renderPath('pathB', live ? s.b_path : []);
  }

  function renderAgree(s) {
    const e = $('agree');
    if (s.mode !== 'live') { e.className = 'agree'; e.textContent = ''; return; }
    e.className = 'agree ' + (s.agree ? 'good' : 'warn');
    e.textContent = s.agree ? 'Both models agree' : 'The models disagree';
  }

  function renderHistory(s) {
    [['histA', s.hist_a || []], ['histB', s.hist_b || []]].forEach(([id, h]) => {
      const box = $(id);
      while (box.children.length < HISTORY) box.appendChild(el('div', 'cell'));
      for (let i = 0; i < HISTORY; i++) {
        const k = i - (HISTORY - h.length);
        box.children[i].className = 'cell' + (k >= 0 && h[k] >= 0 ? ' l' + h[k] : '');
      }
    });
  }

  function renderPlot(s) {
    const canvas = $('wave');
    const ctx = canvas.getContext ? canvas.getContext('2d') : null;
    if (!ctx) return;
    const ratio = window.devicePixelRatio || 1, w = canvas.clientWidth || 300, h = 130;
    canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const css = getComputedStyle(document.documentElement);
    const color = (name, fallback) => (css.getPropertyValue(name) || fallback).trim();
    const LO = -3, HI = 2;                                          // the range of the ax plot, in g
    const yAx = (v) => h - 4 - (Math.min(HI, Math.max(LO, v)) - LO) / (HI - LO) * (h - 8);
    if (ctx.setLineDash) ctx.setLineDash([4, 4]);
    ctx.strokeStyle = color('--muted', '#5d6676'); ctx.lineWidth = 1;
    const thresholds = new Set();                                    // each threshold is the top of one stretch and the bottom of the next: draw it once
    (s.segments || []).forEach((seg) => { [seg.lo, seg.hi].forEach((t) => { if (t !== null) thresholds.add(t); }); });
    thresholds.forEach((t) => { ctx.beginPath(); ctx.moveTo(0, yAx(t)); ctx.lineTo(w, yAx(t)); ctx.stroke(); });
    if (ctx.setLineDash) ctx.setLineDash([]);
    function line(values, y, stroke) {
      if (values.length < 2) return;
      ctx.beginPath();
      values.forEach((v, i) => { const x = (i / (values.length - 1)) * w; if (i) ctx.lineTo(x, y(v)); else ctx.moveTo(x, y(v)); });
      ctx.strokeStyle = stroke; ctx.lineWidth = 2; ctx.stroke();
    }
    const g = s.recent_g || [], top = Math.max(500, ...g);
    line(g, (v) => h - 4 - Math.min(v, top) / top * (h - 8), color('--gyro', '#d1862b'));
    line(s.recent_ax || [], yAx, color('--accel', '#1f6feb'));
  }

  function renderTest(s) {
    if (document.activeElement !== $('person')) $('person').value = s.person || '';
    if (document.activeElement !== $('smooth')) $('smooth').checked = !!s.smooth;
    document.querySelectorAll('#truth button').forEach((b) => b.classList.toggle('on', b.dataset.truth === (s.truth || '')));
    const t = s.tally, score = $('score'), body = document.querySelector('#byLabel tbody');
    score.textContent = ''; body.textContent = '';
    if (!t || !t.windows) {
      score.appendChild(el('div', '', s.truth ? 'Scoring starts with the next half second.' : 'Choose what the person is really doing to start scoring.'));
      $('disagree').textContent = '';
      return;
    }
    [['Model A', t.a_correct], ['Model B', t.b_correct]].forEach(([name, correct]) => {
      const d = el('div', '', name + ' · ' + t.windows + ' windows');
      d.insertBefore(el('b', '', pct(correct / t.windows) + '%'), d.firstChild);
      score.appendChild(d);
    });
    const head = el('tr');
    ['really doing', 'windows', 'Model A right', 'Model B right'].forEach((h) => head.appendChild(el('th', '', h)));
    body.appendChild(head);
    LABELS.forEach((l) => {
      const r = t.by_label[l], tr = el('tr');
      tr.appendChild(el('td', '', l)); tr.appendChild(el('td', '', String(r.n)));
      tr.appendChild(el('td', '', r.n ? pct(r.a / r.n) + '%' : '—')); tr.appendChild(el('td', '', r.n ? pct(r.b / r.n) + '%' : '—'));
      body.appendChild(tr);
    });
    const d = t.disagree;
    $('disagree').textContent = d.n
      ? 'They disagreed on ' + pct(d.n / t.windows) + '% of the windows. When they did, Model A was right ' + pct(d.a_right / d.n) + '% of the time and Model B ' + pct(d.b_right / d.n) + '%.'
      : 'They never disagreed.';
  }
})();
