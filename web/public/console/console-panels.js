/* Conditions / forecast / duty log / last-result panels. All rendering via
 * textContent (no innerHTML with data). Bilingual labels throughout. */

export const EVENT_KINDS = {
  rain: '降雨 Rain', overcast: '阴天 Overcast', haze: '霾 Haze',
  earthquake: '地震 Earthquake', terrain_obstruction: '地形遮挡 Terrain',
  cloud: '云 Cloud', wind: '大风 Wind', lightning: '雷电 Lightning',
  cold_snap: '寒潮 Cold snap', rocket_launch: '火箭发射 Rocket launch', storm: '风暴 Storm',
  humidity: '高湿 Humidity', data_loss: '数据丢失 Data loss',
  instrument_fault: '仪器故障 Fault', dust: '沙尘 Dust',
};
export const DIRECTIONS = {
  N: '北 N', NE: '东北 NE', E: '东 E', SE: '东南 SE',
  S: '南 S', SW: '西南 SW', W: '西 W', NW: '西北 NW', ALL: '全天 ALL',
};
const KIND_CLASS = { earthquake: 'bad', data_loss: 'bad', instrument_fault: 'bad', rain: 'warn', overcast: 'warn' };

function tag(text, cls = '') {
  const s = document.createElement('span');
  s.className = `kind-tag ${cls}`;
  s.textContent = text;
  return s;
}

export function renderBulletin(el, bulletin) {
  el.replaceChildren();
  if (!bulletin) { el.textContent = '暂无快报 No bulletin yet'; return; }
  const head = document.createElement('div');
  head.textContent = `最新快报 Bulletin ${bulletin.slot_id || ''} @ ${bulletin.issued_at_utc}`;
  el.append(head);
  for (const n of bulletin.notices || []) {
    el.append(tag(`${EVENT_KINDS[n.event_kind] || n.event_kind} · ${DIRECTIONS[n.direction] || n.direction}`,
      KIND_CLASS[n.event_kind] || ''));
  }
}

export function renderForecast(el, forecast) {
  el.replaceChildren();
  if (!forecast) { el.textContent = '暂无预报 No forecast yet'; return; }
  const byNight = new Map();
  for (const n of forecast.notices || []) {
    for (const night of n.nights || ['—']) {
      if (!byNight.has(night)) byNight.set(night, []);
      byNight.get(night).push(n);
    }
  }
  const head = document.createElement('div');
  head.className = 'row';
  head.textContent = `预报 Forecast @ ${forecast.issued_at_utc} (${forecast.coverage_start_utc} → ${forecast.coverage_end_utc})`;
  el.append(head);
  for (const [night, notices] of [...byNight.entries()].sort()) {
    const row = document.createElement('div');
    row.className = 'row';
    row.append(tag(`夜 Night ${night}`));
    for (const n of notices) {
      row.append(tag(`${EVENT_KINDS[n.event_kind] || n.event_kind} ${DIRECTIONS[n.direction] || n.direction}`,
        KIND_CLASS[n.event_kind] || ''));
    }
    el.append(row);
  }
}

function describeMessage(m) {
  if (m.record_type === 'bulletin') {
    const ns = (m.notices || []).map((n) => `${EVENT_KINDS[n.event_kind] || n.event_kind}@${DIRECTIONS[n.direction] || n.direction}`);
    return `快报 Bulletin: ${ns.join(', ')}`;
  }
  if (m.record_type === 'forecast') return `预报 Forecast: ${(m.notices || []).length} 条 notices`;
  if (m.record_type === 'observation_request') {
    return `观测请求 Request ${m.request_id}: ${m.target_ids.length} 个目标 targets, 至少 ${m.minimum_completed}, 截止 ${m.deadline_utc} (${m.reason || ''})`;
  }
  if (m.record_type === 'observation_request_result') {
    return `请求结果 Request ${m.request_id}: ${m.status === 'completed' ? '完成 completed' : '过期 expired'}, 奖励 reward ${m.reward_delta ?? m.score_delta ?? ''}`;
  }
  if (m.record_type === 'report_result') {
    return `故障上报 Report: ${m.correct ? '正确 correct' : '误报 false'}, 结算 delta ${m.score_delta}`;
  }
  if (m.record_type === 'state_resync') {
    return `状态同步 Resync: 数据失效 data invalidated (event ${m.trigger_event_id})`;
  }
  return `${m.record_type || 'message'}`;
}

/* Append new messages chronologically; `seen` = number already rendered. */
export function appendDutyLog(el, messages, seen) {
  for (const m of messages.slice(seen)) {
    const row = document.createElement('div');
    row.className = 'row';
    const t = document.createElement('span');
    t.className = 't';
    t.textContent = m.issued_at_utc || '';
    row.append(t, document.createTextNode(describeMessage(m)));
    el.append(row);
  }
  el.scrollTop = el.scrollHeight;
  return messages.length;
}

export function renderActiveRequests(el, requests) {
  el.replaceChildren();
  for (const r of requests || []) {
    const div = document.createElement('div');
    div.className = 'req';
    const head = document.createElement('div');
    const rid = document.createElement('span');
    rid.className = 'rid';
    rid.textContent = r.request_id;
    head.append(rid, document.createTextNode(` 截止 deadline ${r.deadline_utc}`));
    const body = document.createElement('div');
    body.textContent = `进度 progress ${r.completed_count}/${r.minimum_completed} · 目标 targets: ${r.target_ids.slice(0, 8).join(', ')}${r.target_ids.length > 8 ? '…' : ''}`;
    div.append(head, body);
    el.append(div);
  }
}

export function renderLastResult(el, lr) {
  el.replaceChildren();
  if (!lr) { el.textContent = '尚无动作 No action yet'; return; }
  if (lr.action === 'observe') {
    const lines = [`观测完成 Observe #${lr.observe_index}: 分配 assigned ${lr.assigned_count}, 命中 hits ${lr.hit_count}`];
    for (const h of (lr.hits || []).slice(0, 20)) lines.push(`${h.target_id}  +${h.score}`);
    el.textContent = lines.join('\n');
    el.style.whiteSpace = 'pre-wrap';
  } else if (lr.action === 'wait') {
    el.textContent = '等待完成 Wait done';
  } else if (lr.action === 'report') {
    el.textContent = `故障上报 Report: ${lr.correct ? '正确 correct' : '误报 false'}, delta ${lr.score_delta}`;
  } else {
    el.textContent = JSON.stringify(lr);
  }
}
