/* Scripted auto-play policies for headless tests.
 * smoke:  autofill + observe through the first night, then wait to survey end.
 * replay: feed a recorded action log through the full UI path (mode human).
 * A policy gets a ctx facade: { view, snapshot, sendQuery, sendAction, finish, showError }.
 */

export function smokePolicy() {
  let awaiting = false;
  let pointing = null;
  const DURATION = 600;
  return {
    onSnapshot(ctx) {
      const v = ctx.view;
      const snap = ctx.snapshot;
      if (!v.is_night || (v.night && v.night.index > 1)) {
        // First night is over (or daytime): wait straight to the end of the survey.
        ctx.sendAction({ action: 'wait', until_utc: snap.survey_end_utc });
        return;
      }
      const rows = v.targets || [];
      if (!rows.length) {
        ctx.sendAction({ action: 'wait', duration_seconds: 900 });
        return;
      }
      // Point near the highest observable target.
      const t = rows.reduce((a, b) => (b[1] > a[1] ? b : a));
      pointing = {
        alt_deg: Math.min(80, Math.max(v.min_alt_deg + 5, Math.round(t[1] * 100) / 100)),
        az_deg: t[2],
      };
      awaiting = true;
      ctx.sendQuery({ q: 'autofill', alt_deg: pointing.alt_deg, az_deg: pointing.az_deg, duration_seconds: DURATION });
    },
    onAnswer(ctx, answer) {
      if (answer.error) {
        awaiting = false;
        ctx.sendAction({ action: 'wait', duration_seconds: 900 });
        return;
      }
      if (answer.q === 'autofill' && awaiting && pointing) {
        awaiting = false;
        const assignments = answer.assignments || {};
        if (Object.keys(assignments).length === 0) {
          ctx.sendAction({ action: 'wait', duration_seconds: 900 });
        } else {
          ctx.sendAction({
            action: 'observe',
            pointing: { alt_deg: pointing.alt_deg, az_deg: pointing.az_deg },
            assignments,
            duration_seconds: DURATION,
            program: 'BACKUP',
          });
        }
      }
    },
  };
}

export function replayPolicy(actions) {
  const queue = actions.slice();
  return {
    onSnapshot(ctx) {
      const action = queue.shift();
      if (action) ctx.sendAction(action);
      else ctx.finish();
    },
    onAnswer(ctx, answer) {
      // A validation error during replay means UI and engine disagree; stop cleanly.
      if (answer.error) {
        ctx.showError(`replay action rejected: ${answer.error}`);
        ctx.finish();
      }
    },
  };
}
