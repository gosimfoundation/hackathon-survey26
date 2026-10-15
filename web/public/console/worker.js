/* AOH console engine worker: Pyodide + the official challenge simulator/scorer.
 *
 * Messages in:  {type:'start', card, mode, actions?}
 *   mode 'replay'           -> actions[] replayed, no UI round trip (golden test)
 *   mode 'human'/'assisted' -> every decision blocks on the main thread via a
 *                              SharedArrayBuffer bridge (see engine.js sendAction)
 * Messages out: {type:'progress', loaded, total}       boot progress (file fetches)
 *               {type:'init', card, payload}           human/assisted only, once per start
 *               {type:'bridge', sab}                   human/assisted only, once per start
 *               {type:'msg', message}                  human/assisted: message.type is
 *                                                      'snapshot' (decision request, with
 *                                                      seq/snapshot/view) or 'answer'
 *                                                      (query answer or validation error)
 *               {type:'done', card, scoreReport, decisionsCsv, actions, actionsJsonl,
 *                            annotatedLogJsonl}
 *               {type:'error', card, message}
 */
importScripts('./vendor/pyodide/pyodide.js');

const PYODIDE_URL = './vendor/pyodide/';
const BRIDGE_CAPACITY = 1 << 20; // 1 MiB for one reply JSON
let pyodidePromise = null;

async function boot() {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      const pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
      const manifest = await (await fetch('./manifest.json')).json();
      let loaded = 0;
      const total = manifest.files.length;
      postMessage({ type: 'progress', loaded, total });
      await Promise.all(manifest.files.map(async (rel) => {
        const bytes = new Uint8Array(await (await fetch('./' + rel)).arrayBuffer());
        const dest = '/app/' + rel;
        pyodide.FS.mkdirTree(dest.slice(0, dest.lastIndexOf('/')));
        pyodide.FS.writeFile(dest, bytes);
        postMessage({ type: 'progress', loaded: ++loaded, total });
      }));
      const driver = await (await fetch('./py/console_driver.py')).text();
      await pyodide.runPythonAsync(driver);
      return pyodide;
    })();
  }
  return pyodidePromise;
}

/* Blocking bridge: Python calls exchange(messageJson); we post the parsed message to the
 * main thread, then Atomics.wait until sendAction() writes the reply and notifies.
 * The reply is JSON text: {"type":"query",...} or {"type":"action","action":{...}};
 * empty reply -> agent returns None (run ends). */
function makeExchange() {
  const sab = new SharedArrayBuffer(8 + BRIDGE_CAPACITY);
  const i32 = new Int32Array(sab, 0, 2); // [0]=ready flag, [1]=reply byte length
  const u8 = new Uint8Array(sab, 8);
  postMessage({ type: 'bridge', sab });
  const decoder = new TextDecoder();
  return function exchange(messageJson) {
    postMessage({ type: 'msg', message: JSON.parse(messageJson) });
    Atomics.wait(i32, 0, 0);
    Atomics.store(i32, 0, 0);
    const len = i32[1];
    // TextDecoder refuses views onto shared memory — copy into a normal buffer first.
    return len > 0 ? decoder.decode(u8.slice(0, len)) : '';
  };
}

onmessage = async (event) => {
  const msg = event.data || {};
  if (msg.type !== 'start') return;
  const { card, mode } = msg;
  try {
    const pyodide = await boot();
    pyodide.globals.set('__card', card);
    pyodide.globals.set('__mode', mode);
    // replay actions may arrive as raw JSON text so fibre-id key order survives (see console_driver.py)
    pyodide.globals.set('__actions', typeof msg.actions === 'string' ? msg.actions : JSON.stringify(msg.actions || []));
    pyodide.globals.set('__exchange', mode === 'replay' ? null : makeExchange());
    // replay animation stream (replay.html): non-blocking snapshot posts, same view shape
    pyodide.globals.set('__observer', mode === 'replay' && msg.observe
      ? (text) => postMessage({ type: 'msg', message: JSON.parse(text) })
      : null);
    if (mode !== 'replay' || msg.observe) {
      const initJson = await pyodide.runPythonAsync('init_payload_json(__card)');
      postMessage({ type: 'init', card, payload: JSON.parse(initJson) });
    }
    const resultJson = await pyodide.runPythonAsync(
      'run_card(__card, __mode, __actions, __exchange, __observer)'
    );
    const result = JSON.parse(resultJson);
    postMessage({
      type: 'done',
      card,
      scoreReport: result.score_report,
      decisionsCsv: result.decisions_csv,
      actions: result.actions,
      actionsJsonl: result.actions_jsonl,
      annotatedLogJsonl: result.annotated_log_jsonl,
    });
  } catch (err) {
    postMessage({ type: 'error', card, message: String((err && err.message) || err) });
  }
};
