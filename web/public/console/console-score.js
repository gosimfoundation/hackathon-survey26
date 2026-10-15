/* Score breakdown panel: renders score_report.json as bilingual tables. */

const COMPONENT_LABELS = {
  sum_best_scores: '观测得分 Sum of best scores',
  required_penalty: '必需目标罚分 Required penalty',
  uniformity_penalty: '均匀性罚分 Uniformity penalty',
  observation_request_reward: '观测请求奖励 Request reward',
  report_settlement: '故障上报结算 Report settlement',
};
const COUNT_LABELS = {
  decisions: '决策数 Decisions', observe_actions: '观测次数 Observe actions',
  observations: '有效观测 Observations', targets_observed: '已观测目标 Targets observed',
  required_missing: '缺失必需目标 Required missing',
  invalidated_observations: '失效观测 Invalidated',
  observation_requests_issued: '已发请求 Requests issued',
  observation_requests_completed: '完成请求 Requests completed',
};
const TERMINATION_LABELS = {
  survey_complete: '巡天完成 Survey complete', agent_finished: '主动结束 Finished by user',
  agent_error: '代理错误 Agent error', wallclock: '超时 Wallclock limit',
};

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

function num(v) {
  return typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : String(v);
}

export function renderScore(el, report) {
  el.replaceChildren();
  const total = document.createElement('div');
  total.className = 'total-line';
  total.textContent = `总分 Total: ${report.total}`;
  el.append(total);

  const term = document.createElement('div');
  const reason = (report.termination && report.termination.reason) || '';
  term.textContent = `结束原因 Termination: ${TERMINATION_LABELS[reason] || reason}` +
    (report.termination && report.termination.detail ? ` — ${report.termination.detail}` : '');
  el.append(term);

  const h1 = document.createElement('h2');
  h1.textContent = '组成 Components';
  el.append(h1);
  table(el, ['项 Item', '值 Value'],
    Object.entries(report.components || {}).map(([k, v]) => [COMPONENT_LABELS[k] || k, num(v)]));

  const h2 = document.createElement('h2');
  h2.textContent = '分类得分 By class';
  el.append(h2);
  table(el, ['类别 Class', '得分 Score'],
    Object.entries(report.by_class || {}).map(([k, v]) => [k, num(v)]));

  const h3 = document.createElement('h2');
  h3.textContent = '计数 Counts';
  el.append(h3);
  table(el, ['项 Item', '值 Value'],
    Object.entries(report.counts || {}).map(([k, v]) => [COUNT_LABELS[k] || k, num(v)]));

  const inv = report.invalidations || [];
  const h4 = document.createElement('h2');
  h4.textContent = `失效记录 Invalidations (${inv.length})`;
  el.append(h4);
  if (inv.length) {
    table(el, ['事件 Event', '说明 Detail'],
      inv.map((x) => [x.event_id || x.trigger_event_id || '', JSON.stringify(x).slice(0, 120)]));
  }

  const reqs = report.observation_requests || [];
  if (reqs.length) {
    const h5 = document.createElement('h2');
    h5.textContent = `观测请求 Requests (${reqs.length})`;
    el.append(h5);
    table(el, ['ID', '状态 Status', '奖励 Reward', '截止 Deadline'],
      reqs.map((r) => [r.request_id, r.status, num(r.reward_delta ?? r.reward ?? 0), r.deadline_utc]));
  }
}
