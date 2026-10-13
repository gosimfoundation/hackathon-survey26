/* AOH human console — main wiring: start screen, engine glue, panels, action bar,
 * assisted-mode controller (Task 3) and end-of-run screen + leaderboard (Task 4). */
import { SkyView } from './console-sky.js';
import { FibrePanel } from './console-fibres.js';
import { renderBulletin, renderForecast, appendDutyLog, renderActiveRequests, renderLastResult } from './console-panels.js';
import { smokePolicy, replayPolicy } from './console-auto.js';
import { AssistController } from './console-assist.js';
import { countSources, recordResult, renderLeaderboard, renderResult } from './console-result.js';

const $ = (id) => document.getElementById(id);
const CARD_LABELS = {
  'console-s1': '短任务 1：两晚 Short task 1: 2 nights',
  'console-s2': '短任务 2：两晚含数据丢失 Short task 2: 2 nights with data loss',
  demo7: '标准公开任务：7晚 Standard public task: 7 nights',
};

const S = {
  engine: null, card: null, mode: 'human', name: '', payload: null,
  msg: null,            // latest snapshot message {seq, snapshot, view, suggested?}
  pending: false,       // the bridge is blocked waiting for our reply
  done: false,
  pointing: null,       // {alt_deg, az_deg}
  policy: null, auto: null, assist: null,
  logSeen: 0, allMessages: [],
  sourceCounts: { human: 0, assistant: 0, human_accept: 0 },
  manifest: null, reference: null, startMs: 0, lastField: null,
  sky: null, fibres: null,
};

function showError(text) {
  const el = $('errbar');
  el.hidden = !text;
  el.textContent = text || '';
}

function exposureSeconds() {
  const exp = (S.payload && S.payload.instrument.exposure) || { min_duration_seconds: 60, max_duration_seconds: 3600 };
  const raw = parseInt($('exposure-in').value, 10) || exp.min_duration_seconds;
  const v = Math.min(exp.max_duration_seconds, Math.max(exp.min_duration_seconds, raw));
  $('exposure-in').value = v;
  return v;
}

/* Commit one final action for the pending decision. */
function commit(action, source) {
  if (!S.pending) return;
  S.sourceCounts[source] = (S.sourceCounts[source] || 0) + 1;
  updateSourceCounts();
  S.engine.sendReply({ type: 'action', action, source });
  S.pending = false;
  if (S.assist) S.assist.noteManualCommit();
  setButtons();
}

function commitSuggestion(source) {
  if (!S.pending) return;
  S.sourceCounts[source] = (S.sourceCounts[source] || 0) + 1;
  updateSourceCounts();
  S.engine.sendReply({ type: 'action', use_suggestion: true, source });
  S.pending = false;
  if (S.assist) S.assist.noteManualCommit();
  setButtons();
}

function updateSourceCounts() {
  $('srccell').hidden = S.mode !== 'assisted';
  const c = S.sourceCounts;
  $('src-counts').textContent = `人 ${c.human + c.human_accept} / 助手 ${c.assistant}`;
}

/* Facade handed to auto policies (smoke/replay). */
function ctx() {
  return {
    view: S.msg && S.msg.view,
    snapshot: S.msg && S.msg.snapshot,
    sendQuery: (q) => S.engine.sendQuery(q),
    sendAction: (action) => commit(action, 'human'),
    finish: () => { S.engine.sendReply(null); S.pending = false; },
    showError,
  };
}

function skyState() {
  return {
    view: S.msg && S.msg.view, snapshot: S.msg && S.msg.snapshot,
    pointing: S.pointing, fovSideDeg: S.payload ? S.payload.instrument.fov_side_deg : 2.5,
    instrument: S.payload ? S.payload.instrument : null,
    field: S.lastField, assignments: S.fibres ? S.fibres.getAssignments() : {},
  };
}

async function boot() {
  const params = new URLSearchParams(location.search);
  S.manifest = await (await fetch('./manifest.json')).json();
  $('engine-sha').textContent = S.manifest.engine_sha || '—';
  try {
    S.reference = await (await fetch('./reference_scores.json')).json();
  } catch { S.reference = null; }
  const sel = $('card-sel');
  for (const c of S.manifest.cards) sel.add(new Option(CARD_LABELS[c] || c, c));
  S.sky = new SkyView($('sky'), (alt, az) => {
    S.pointing = { alt_deg: alt, az_deg: az };
    $('sky-info').textContent = `指向 Pointing: alt ${alt}°, az ${az}°`;
    S.sky.draw();
    if (S.pending && !S.policy) {
      S.engine.sendQuery({ q: 'field', alt_deg: alt, az_deg: az, duration_seconds: exposureSeconds() });
    }
  });
  for (const btn of document.querySelectorAll('.zoom-btn')) {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.zoom-btn').forEach((b) => b.classList.toggle('active', b === btn));
      S.sky.setZoom(btn.dataset.zoom);
    });
  }
  S.fibres = new FibrePanel($('fibre-grid'), () => { if (S.sky) { S.sky.state = skyState(); S.sky.draw(); } });
  if (params.get('card')) sel.value = params.get('card');
  if (params.get('name')) $('name-in').value = params.get('name');
  const reqMode = params.get('mode');
  if (reqMode === 'assisted') document.querySelector('input[name=mode][value=assisted]').checked = true;
  $('start-btn').addEventListener('click', () => {
    const mode = document.querySelector('input[name=mode]:checked').value;
    begin(sel.value, mode, $('name-in').value.trim() || '观测者 Observer', null);
  });
  wireActionBar();
  wireCheckpoint();
  const auto = params.get('auto');
  if (auto && params.get('card')) {
    begin(params.get('card'), params.get('mode') || 'human', params.get('name') || 'auto', auto, params.get('file'));
  }
}

async function begin(card, mode, name, auto, file) {
  S.card = card; S.mode = mode; S.name = name; S.auto = auto;
  S.startMs = performance.now();
  $('who').textContent = name;
  $('start-screen').hidden = true;
  $('loading').hidden = false;
  if (auto === 'smoke') S.policy = smokePolicy();
  if (auto === 'replay') {
    const text = await (await fetch('./' + file)).text();
    const actions = text.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
    S.policy = replayPolicy(actions);
  }
  if (mode === 'assisted') {
    S.assist = new AssistController(
      { commit, commitSuggestion, prefill, showCheckpoint, hideCheckpoint },
      { auto: auto === 'assist' });
    $('pause-btn').hidden = false;
    $('speed-sel').hidden = false;
    $('assist-sep').hidden = false;
    $('srccell').hidden = false;
  }
  S.engine = new ConsoleEngine({
    onProgress: ({ loaded, total }) => {
      $('load-fill').style.width = `${Math.round((100 * loaded) / total)}%`;
      $('load-text').textContent = `${loaded} / ${total}`;
    },
    onInit: (payload) => {
      S.payload = payload;
      S.fibres.setup(payload.instrument);
      $('exposure-in').min = payload.instrument.exposure.min_duration_seconds;
      $('exposure-in').max = payload.instrument.exposure.max_duration_seconds;
      $('loading').hidden = true;
      $('app').hidden = false;
    },
    onMessage: (m) => onMessage(m),
    onDone: (msg) => onDone(msg),
    onError: (err) => { showError(String(err)); document.title = 'RUN ERROR'; },
  });
  S.engine.start(card, mode).catch(() => {});
}

function onMessage(m) {
  if (m.type === 'snapshot') {
    S.msg = m;
    S.pending = true;
    showError('');
    renderAll();
    if (!S.readyMs) {
      S.readyMs = Math.round(performance.now());
      window.__consoleReadyMs = S.readyMs; // Task 5 load-time probe
    }
    setButtons();
    if (S.assist) S.assist.onSnapshot(m);
    else if (S.policy) S.policy.onSnapshot(ctx());
    return;
  }
  // answer message
  if (S.policy) { S.policy.onAnswer(ctx(), m); setButtons(); return; }
  if (m.error) { showError(m.error); return; }
  if (m.q === 'field' && S.pointing &&
      Math.abs(m.alt_deg - S.pointing.alt_deg) < 0.02 && Math.abs(m.az_deg - S.pointing.az_deg) < 0.02) {
    S.lastField = m;
    S.fibres.setCandidates(m.fibres);
    S.sky.state = skyState();
    S.sky.draw();
    const n = Object.values(m.fibres).reduce((a, c) => a + c.length, 0);
    $('sky-info').textContent = `指向 Pointing: alt ${m.alt_deg}°, az ${m.az_deg}° · 候选 candidates ${n}` +
      (m.altitude_ok === false ? ' · ⚠ 指向高度不足 pointing below min-alt during exposure' : '');
  } else if (m.q === 'autofill') {
    S.fibres.setAssignments(m.assignments || {});
  }
}

function renderAll() {
  const v = S.msg.view, snap = S.msg.snapshot;
  $('clock-utc').textContent = v.now_utc;
  $('clock-local').textContent = v.local_time;
  $('night').textContent = v.is_night ? `${v.night.index} / ${v.night.count}` : '白天 Day';
  $('seq').textContent = String(S.msg.seq);
  $('score').textContent = String(snap.running_total);
  S.sky.update(skyState());
  renderBulletin($('bulletin'), snap.latest_bulletin);
  renderForecast($('forecast'), snap.latest_forecast);
  S.allMessages = S.allMessages.concat(snap.new_messages || []);
  S.logSeen = appendDutyLog($('duty-log'), S.allMessages, S.logSeen);
  renderActiveRequests($('requests'), snap.active_requests);
  renderLastResult($('last-result'), snap.last_result);
}

/* --- assisted-mode checkpoint panel ---------------------------------------- */

function describeSuggestion(a) {
  if (!a) return '—';
  if (a.action === 'observe') {
    return `观测 Observe: alt ${a.pointing.alt_deg}°, az ${a.pointing.az_deg}°, ` +
      `${Object.keys(a.assignments || {}).length} 光纤 fibres, ${a.duration_seconds}s, ${a.program}`;
  }
  if (a.action === 'wait') {
    return `等待 Wait: ${a.duration_seconds ? a.duration_seconds + 's' : 'until ' + a.until_utc}`;
  }
  return a.action === 'report' ? '上报故障 Report' : '结束 Finish';
}

function prefill(suggested) {
  if (!suggested) return;
  if (suggested.action === 'observe') {
    S.pointing = { ...suggested.pointing };
    $('exposure-in').value = suggested.duration_seconds;
    $('program-sel').value = suggested.program || 'BACKUP';
    S.fibres.setAssignments(suggested.assignments || {});
    S.sky.state = skyState();
    S.sky.draw();
    if (S.pending) {
      S.engine.sendQuery({ q: 'field', alt_deg: S.pointing.alt_deg, az_deg: S.pointing.az_deg,
                           duration_seconds: suggested.duration_seconds });
    }
  }
}

function showCheckpoint(kind, reason) {
  $('checkpoint').hidden = false;
  $('checkpoint-reason').textContent = reason;
  $('checkpoint-night').hidden = kind !== 'night';
  $('checkpoint-suggestion').textContent =
    `助手建议 Assistant suggests: ${describeSuggestion(S.msg && S.msg.suggested)}`;
  if (kind === 'night') renderForecast($('checkpoint-forecast'), S.msg.snapshot.latest_forecast);
  $('checkpoint').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function hideCheckpoint() {
  $('checkpoint').hidden = true;
  $('pause-btn').textContent = '暂停 Pause';
}

function wireCheckpoint() {
  $('plan-go').addEventListener('click', () => {
    S.assist.callMe = {
      bulletin: $('cm-bulletin').checked, request: $('cm-request').checked, report: $('cm-report').checked,
    };
    const plan = document.querySelector('input[name=nightplan]:checked').value;
    S.assist.applyNightPlan(plan);
    setButtons();
  });
  $('accept-btn').addEventListener('click', () => { S.assist.accept(); setButtons(); });
  $('resume-btn').addEventListener('click', () => { S.assist.resume(); setButtons(); });
}

/* --- end of run (Task 4) ----------------------------------------------------- */

function onDone(msg) {
  S.done = true;
  S.pending = false;
  hideCheckpoint();
  setButtons();
  const report = JSON.parse(msg.scoreReport);
  const counts = countSources(msg.annotatedLogJsonl);
  $('score').textContent = String(report.total);
  $('score-panel').hidden = false;
  $('score-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  renderResult({
    el: $('score-detail'),
    report,
    counts,
    timeUsedMs: performance.now() - S.startMs,
    downloads: [
      ['actions.jsonl', msg.actionsJsonl, `actions-${S.card}.jsonl`],
      ['annotated_log.jsonl', msg.annotatedLogJsonl || '', `annotated-${S.card}.jsonl`],
      ['decisions.csv', msg.decisionsCsv, `decisions-${S.card}.csv`],
      ['score_report.json', msg.scoreReport, `score-${S.card}.json`],
    ],
  });
  if (!S.auto) {
    const rows = recordResult({
      name: S.name, card: S.card, mode: S.mode, total: report.total,
      counts, engineSha: S.manifest.engine_sha,
    });
    renderLeaderboard($('leaderboard'), rows, S.reference, S.card);
  } else {
    renderLeaderboard($('leaderboard'), [], S.reference, S.card);
  }
  $('lb-panel').hidden = false;
  document.title = S.auto === 'smoke' ? `SMOKE DONE ${report.total}`
    : S.auto === 'replay' ? `REPLAY DONE ${report.total}`
    : S.auto === 'assist' ? `ASSIST DONE ${report.total}`
    : `RUN DONE ${report.total}`;
}

function setButtons() {
  const on = S.pending && !S.done;
  for (const id of ['observe-btn', 'wait15-btn', 'wait60-btn', 'waitnight-btn', 'report-btn', 'stop-btn',
                    'autofill-btn', 'clear-btn', 'accept-btn', 'plan-go', 'resume-btn']) {
    $(id).disabled = !on;
  }
  if (S.assist) {
    $('pause-btn').disabled = S.done;
    $('speed-sel').disabled = S.done;
  }
}

function wireActionBar() {
  $('observe-btn').addEventListener('click', () => {
    if (!S.pointing) { showError('先点击天空图选择指向 Tap the sky to set a pointing first'); return; }
    commit({
      action: 'observe',
      pointing: { ...S.pointing },
      assignments: S.fibres.getAssignments(),
      duration_seconds: exposureSeconds(),
      program: $('program-sel').value,
    }, 'human');
  });
  $('wait15-btn').addEventListener('click', () => commit({ action: 'wait', duration_seconds: 900 }, 'human'));
  $('wait60-btn').addEventListener('click', () => commit({ action: 'wait', duration_seconds: 3600 }, 'human'));
  $('waitnight-btn').addEventListener('click', () => {
    const until = (S.msg && S.msg.view.next_night_start_utc) || (S.msg && S.msg.snapshot.survey_end_utc);
    commit({ action: 'wait', until_utc: until }, 'human');
  });
  $('report-btn').addEventListener('click', () => commit({ action: 'report' }, 'human'));
  $('stop-btn').addEventListener('click', () => commit({ action: 'finish' }, 'human'));
  $('autofill-btn').addEventListener('click', () => {
    if (!S.pointing) { showError('先点击天空图选择指向 Tap the sky to set a pointing first'); return; }
    S.engine.sendQuery({ q: 'autofill', alt_deg: S.pointing.alt_deg, az_deg: S.pointing.az_deg, duration_seconds: exposureSeconds() });
  });
  $('clear-btn').addEventListener('click', () => S.fibres.clear());
  $('pause-btn').addEventListener('click', () => {
    if (S.assist) { S.assist.setPaused(true); $('pause-btn').textContent = '已暂停… Paused'; }
  });
  $('speed-sel').addEventListener('change', () => { if (S.assist) S.assist.speed = $('speed-sel').value; });
  document.addEventListener('keydown', (ev) => {
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(ev.target.tagName)) return;
    if (!S.pending || S.done) return;
    if (ev.key === 'o') $('observe-btn').click();
    if (ev.key === 'w') $('wait15-btn').click();
    if (ev.key === 'r') $('report-btn').click();
  });
}

boot().catch((err) => { showError(String(err)); document.title = 'RUN ERROR'; });
