/* Assisted mode controller (Task 3): the official basic-example planner runs routine
 * exposures; the human sets the plan and is called back at checkpoints.
 *
 * Checkpoints (run pauses, suggestion pre-filled in the action form):
 *   1. start of each night — nightly plan form (assistant / closed / by hand) plus
 *      "call me when" switches (bulletin, observation request, report — default on);
 *   2. a checked key event arrives, or the assistant's suggestion is `report`;
 *   3. the human pressed 暂停 Pause (takes effect at the next decision).
 * Otherwise the assistant's suggestion is committed automatically (source "assistant")
 * after a speed-controlled delay. auto=assist (headless test) always lets the
 * assistant run and auto-accepts every checkpoint.
 *
 * Hooks supplied by console-main.js:
 *   commit(action, source)         — send a final action for the pending decision
 *   commitSuggestion(source)       — commit the suggestion verbatim (use_suggestion)
 *   prefill(suggestion)            — fill pointing/fibres/exposure/program form
 *   showCheckpoint(kind, reason)   — reveal the checkpoint panel
 *   hideCheckpoint()               — hide it
 *   forecast()                     — latest forecast snapshot field (for the panel)
 */

export const SPEEDS = { '1': 1200, '10': 120, max: 0 };

export class AssistController {
  constructor(hooks, { auto = false } = {}) {
    this.h = hooks;
    this.auto = auto;
    this.speed = 'max';
    this.paused = false;
    this.callMe = { bulletin: true, request: true, report: true };
    this.plan = null;          // plan for the current night: 'assistant'|'closed'|'manual'
    this.planNight = null;     // night index the plan belongs to
    this.seenNight = null;     // last night index we have checkpointed
    this.msg = null;
  }

  delayMs() { return this.auto ? 0 : SPEEDS[this.speed] ?? 0; }

  setPaused(on) { this.paused = on; }

  /* Choose the nightly plan from the form and act on it for THIS decision. */
  applyNightPlan(plan) {
    const night = this.msg && this.msg.view.night;
    this.plan = plan;
    this.planNight = night ? night.index : null;
    if (plan === 'assistant') {
      this.h.hideCheckpoint();
      this._autoCommit();
    } else if (plan === 'closed') {
      this.h.hideCheckpoint();
      const until = this.msg.view.next_night_start_utc || this.msg.snapshot.survey_end_utc;
      this.h.commit({ action: 'wait', until_utc: until }, 'human');
    } else { // manual: stay on the checkpoint, form is pre-filled
      this.h.showCheckpoint('manual', '我来手动 Manual this night — 每个决策都需要你确认 every decision is yours');
    }
  }

  /* Human accepted the pre-filled suggestion at a checkpoint. */
  accept() {
    this.h.hideCheckpoint();
    this.h.commitSuggestion('human_accept');
  }

  /* Human committed something else via the action bar during a checkpoint. */
  noteManualCommit() { this.h.hideCheckpoint(); }

  resume() {
    this.paused = false;
    this.h.hideCheckpoint();
    this._autoCommit(); // commit the pending suggestion as assistant and carry on
  }

  onSnapshot(m) {
    this.msg = m;
    const v = m.view;
    const nightIndex = v.night ? v.night.index : null;
    if (this.planNight !== nightIndex) this.plan = null; // plan expired with the night

    if (this.auto) { this._autoCommit(); return; }

    if (v.is_night && nightIndex !== this.seenNight) {
      this.seenNight = nightIndex;
      this.h.prefill(m.suggested);
      this.h.showCheckpoint('night', `第 ${nightIndex} 夜开始 Night ${nightIndex} begins — 选择今晚的计划 choose the plan`);
      return;
    }
    if (this.paused) {
      this.h.prefill(m.suggested);
      this.h.showCheckpoint('pause', '已暂停 Paused — 确认或修改助手建议 review the suggestion');
      return;
    }
    if (this.plan === 'manual') {
      this.h.prefill(m.suggested);
      this.h.showCheckpoint('manual', '手动夜 Manual night — 确认或修改 confirm or edit');
      return;
    }
    if (this.plan === 'closed') {
      const until = v.next_night_start_utc || m.snapshot.survey_end_utc;
      this.h.commit({ action: 'wait', until_utc: until }, 'human');
      return;
    }
    const event = this._keyEvent(m);
    if (event) {
      this.h.prefill(m.suggested);
      this.h.showCheckpoint('event', event);
      return;
    }
    this._autoCommit();
  }

  _keyEvent(m) {
    if (!this.plan && this.seenNight === null) return null; // pre-first-night handled above
    if (this.plan === 'closed') return null; // sleeping through the night on purpose
    const kinds = new Set((m.snapshot.new_messages || []).map((x) => x.record_type));
    if (this.callMe.bulletin && (kinds.has('bulletin') || kinds.has('state_resync'))) {
      return '新快报/数据失效 New bulletin or data invalidation';
    }
    if (this.callMe.request && kinds.has('observation_request')) {
      return '新观测请求 New observation request';
    }
    if (this.callMe.report && m.suggested && m.suggested.action === 'report') {
      return '助手想上报故障 Assistant wants to report a fault';
    }
    return null;
  }

  _autoCommit() {
    const go = () => { if (this.msg) this.h.commitSuggestion('assistant'); };
    const d = this.delayMs();
    if (d > 0) setTimeout(go, d); else go();
  }
}
