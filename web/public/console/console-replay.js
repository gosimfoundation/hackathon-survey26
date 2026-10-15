/* replay.html driver (Task 4): load a downloaded actions.jsonl, replay it through the
 * engine in mode=replay (authoritative score), buffer the per-decision snapshot stream
 * the worker emits (observe flag), then animate the sky with a speed slider. */
import { SkyView } from './console-sky.js';
import { renderScore } from './console-score.js';

const $ = (id) => document.getElementById(id);

const R = {
  engine: null, card: null, payload: null,
  frames: [],        // buffered {seq, snapshot, view} messages
  actions: [],       // parsed actions.jsonl rows (action i belongs to frame i)
  idx: 0, playing: false, timer: null, sky: null,
};

function status(text) { $('replay-status').textContent = text; }

async function boot() {
  const manifest = await (await fetch('./manifest.json')).json();
  $('engine-sha').textContent = manifest.engine_sha || '—';
  const sel = $('card-sel');
  for (const c of manifest.cards) sel.add(new Option(c, c));
  const params = new URLSearchParams(location.search);
  if (params.get('card')) sel.value = params.get('card');
  $('file-in').addEventListener('change', () => {
    const name = ($('file-in').files[0] && $('file-in').files[0].name) || '';
    const m = name.match(/actions-([a-z0-9-]+)\.jsonl/i);
    if (m && manifest.cards.includes(m[1])) sel.value = m[1];
  });
  R.sky = new SkyView($('replay-sky'), () => {});
  $('start-btn').addEventListener('click', () => {
    const file = $('file-in').files[0];
    if (!file) { status('请先选择 actions.jsonl 文件 Choose an actions.jsonl file first'); return; }
    file.text().then((text) => runText($('card-sel').value, text));
  });
  $('play-btn').addEventListener('click', togglePlay);
  $('prev-btn').addEventListener('click', () => step(-1));
  $('next-btn').addEventListener('click', () => step(1));
  $('speed-in').addEventListener('input', () => { if (R.playing) { pause(); play(); } });
  // ?file=golden/<card>/actions.jsonl&card=<card> — replay straight from the repo (also the headless hook)
  if (params.get('file')) {
    const fileCard = params.get('card') || (params.get('file').match(/golden\/([a-z0-9-]+)\//) || [])[1];
    if (fileCard && manifest.cards.includes(fileCard)) sel.value = fileCard;
    const text = await (await fetch('./' + params.get('file'))).text();
    runText(sel.value, text);
  }
}

async function runText(card, text) {
  R.card = card;
  const lines = text.split('\n').filter((l) => l.trim());
  R.actions = lines.map((l) => JSON.parse(l));
  R.frames = [];
  R.idx = 0;
  $('play-panel').hidden = true;
  $('score-panel').hidden = true;
  status('回放运行中… Replaying through the engine…');
  R.engine = new ConsoleEngine({
    onInit: (payload) => { R.payload = payload; },
    onMessage: (m) => { if (m.type === 'snapshot') R.frames.push(m); },
    onDone: (msg) => onDone(msg),
    onError: (err) => { status('错误 Error: ' + err); document.title = 'REPLAY ERROR'; },
  });
  // raw JSON array text keeps fibre-id key order — never re-serialised in JS
  const actions = '[' + lines.join(',') + ']';
  R.engine.start(R.card, 'replay', { actions, observe: true }).catch(() => {});
}

function onDone(msg) {
  const report = JSON.parse(msg.scoreReport);
  $('score').textContent = String(report.total);
  $('score-panel').hidden = false;
  renderScore($('score-detail'), report);
  status(`回放完成 Replay done — ${R.frames.length} 决策帧 decision frames, ` +
         `${R.actions.length} 动作 actions, total ${report.total}`);
  $('play-panel').hidden = false;
  showFrame(0);
  document.title = `REPLAY DONE ${report.total}`;
}

function pointingAt(idx) {
  const a = R.actions[idx];
  return a && a.action === 'observe' && a.pointing ? { ...a.pointing } : null;
}

function showFrame(idx) {
  if (!R.frames.length) return;
  R.idx = Math.max(0, Math.min(R.frames.length - 1, idx));
  const f = R.frames[R.idx];
  const a = R.actions[R.idx] || null;
  $('clock-utc').textContent = f.view.now_utc;
  $('night').textContent = f.view.is_night ? `${f.view.night.index} / ${f.view.night.count}` : '白天 Day';
  $('frame').textContent = `${R.idx + 1} / ${R.frames.length}`;
  $('score').textContent = String(f.snapshot.running_total);
  $('action-line').textContent = a ? `动作 Action: ${JSON.stringify(a).slice(0, 160)}` : '—';
  R.sky.update({
    view: f.view, snapshot: f.snapshot,
    pointing: pointingAt(R.idx),
    fovSideDeg: R.payload ? R.payload.instrument.fov_side_deg : 2.5,
    instrument: R.payload ? R.payload.instrument : null,
    assignments: (a && a.assignments) || {},
  });
}

function step(d) { showFrame(R.idx + d); }

function play() {
  R.playing = true;
  $('play-btn').textContent = '暂停 Pause';
  const delay = parseInt($('speed-in').value, 10);
  R.timer = setInterval(() => {
    if (R.idx + 1 >= R.frames.length) { pause(); return; }
    showFrame(R.idx + 1);
  }, Math.max(16, delay));
}

function pause() {
  R.playing = false;
  $('play-btn').textContent = '播放 Play';
  if (R.timer) { clearInterval(R.timer); R.timer = null; }
}

function togglePlay() { (R.playing ? pause : play)(); }

boot().catch((err) => { status('错误 Error: ' + err); document.title = 'REPLAY ERROR'; });
