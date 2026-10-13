/* End-of-run screen (Task 4): official score_report breakdown, human vs assistant
 * counts, time used, downloads (Blob + <a download>, no server), and the local
 * leaderboard (localStorage only, wrapped in try/catch — the page must work even
 * when storage throws). actions.jsonl downloads use the Python-serialised
 * actionsJsonl text verbatim — never re-serialised in JS — so they replay exactly.
 */
import { renderScore } from './console-score.js';

export const LB_KEY = 'aoh-console-leaderboard-v1';

export function loadLeaderboard() {
  try {
    const rows = JSON.parse(localStorage.getItem(LB_KEY) || '[]');
    return Array.isArray(rows) ? rows : [];
  } catch {
    return [];
  }
}

function saveLeaderboard(rows) {
  try {
    localStorage.setItem(LB_KEY, JSON.stringify(rows));
  } catch { /* storage unavailable — the page keeps working */ }
}

export function countSources(annotatedLogJsonl) {
  const counts = { human: 0, assistant: 0, human_accept: 0 };
  for (const line of (annotatedLogJsonl || '').split('\n')) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line);
      counts[row.source] = (counts[row.source] || 0) + 1;
    } catch { /* ignore partial lines */ }
  }
  return counts;
}

export function recordResult({ name, card, mode, total, counts, engineSha }) {
  const rows = loadLeaderboard();
  const row = {
    name, card, mode, total,
    human_actions: (counts.human || 0) + (counts.human_accept || 0),
    assistant_actions: counts.assistant || 0,
    date: new Date().toISOString().slice(0, 19) + 'Z',
    engine_sha: engineSha || '',
  };
  rows.push(row);
  saveLeaderboard(rows);
  return rows;
}

const MODE_LABELS = { human: '手动 Manual', assisted: '辅助 Assisted' };

function table(parent, headCells, rows) {
  const t = document.createElement('table');
  const tr = document.createElement('tr');
  for (const h of headCells) {
    const th = document.createElement('th');
    th.textContent = h;
    tr.append(th);
  }
  t.append(tr);
  for (const cells of rows) {
    const r = document.createElement('tr');
    for (const c of cells) {
      const td = document.createElement('td');
      td.textContent = c;
      r.append(td);
    }
    t.append(r);
  }
  parent.append(t);
}

/* Local leaderboard: per-card tables sorted by total desc, with the fixed
 * probe-agent / basic-example reference rows labelled 参考 AI Reference. */
export function renderLeaderboard(el, rows, reference, card) {
  el.replaceChildren();
  const note = document.createElement('div');
  note.className = 'lb-note';
  note.textContent = '本地排行榜，仅保存在本机浏览器 Local leaderboard, stored only in this browser';
  el.append(note);
  const cards = card ? [card] : Object.keys((reference && reference.cards) || {});
  for (const c of cards) {
    const h = document.createElement('h3');
    h.textContent = c;
    el.append(h);
    const body = [];
    const ref = reference && reference.cards && reference.cards[c];
    if (ref) {
      body.push(['参考 AI Reference (probe 官方探测代理)', '—', ref.probe, '', '', '', 'ref']);
      body.push(['参考 AI Reference (basic example 官方示例)', '—', ref.basic_example, '', '', '', 'ref']);
    }
    const mine = rows.filter((r) => r.card === c)
      .map((r) => [r.name, MODE_LABELS[r.mode] || r.mode, r.total, r.human_actions,
                   r.assistant_actions, (r.date || '').slice(0, 10), '']);
    body.push(...mine);
    body.sort((a, b2) => (b2[2] ?? -Infinity) - (a[2] ?? -Infinity));
    table(el, ['玩家 Player', '模式 Mode', '总分 Total', '手动动作 Human', '助手动作 Assistant', '日期 Date', ''],
      body.map((row) => row.slice(0, 6).concat(row[6] === 'ref' ? ['固定 fixed'] : [''])));
  }
}

/* Full result screen. `opts`: { el, report, counts, timeUsedMs, downloads, engineSha }. */
export function renderResult(opts) {
  const { el, report, counts, timeUsedMs } = opts;
  el.replaceChildren();
  renderScore(el, report);
  const meta = document.createElement('div');
  meta.className = 'row';
  const secs = Math.round((timeUsedMs || 0) / 1000);
  meta.textContent = `动作来源 Action sources — 手动 human ${counts.human || 0} · ` +
    `接受建议 human_accept ${counts.human_accept || 0} · 助手 assistant ${counts.assistant || 0}` +
    ` · 用时 time used ${Math.floor(secs / 60)}m${secs % 60}s`;
  el.append(meta);

  const links = document.createElement('div');
  links.className = 'downloads';
  for (const [label, text, fname] of opts.downloads) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    a.download = fname;
    a.textContent = `下载 ${label}`;
    links.append(a, document.createTextNode(' '));
  }
  const replay = document.createElement('a');
  replay.href = './replay.html';
  replay.textContent = '回放 Replay →';
  links.append(replay);
  const hint = document.createElement('div');
  hint.className = 'lb-note';
  hint.textContent = '回放：打开 replay.html，选择任务并载入下载的 actions.jsonl ' +
    'To replay: open replay.html, pick the card, load the downloaded actions.jsonl';
  links.append(hint);
  el.append(links);
}
