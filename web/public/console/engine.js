/* AOH console engine — main-thread wrapper around worker.js (classic script).
 *
 *   const engine = new ConsoleEngine({ onProgress, onInit, onMessage, onSnapshot,
 *                                      onDone, onError });
 *   const done = await engine.start(card, mode, { actions }); // actions: replay only
 *   engine.sendQuery({ q: 'field', alt_deg, az_deg });        // human/assisted only
 *   engine.sendAction(action, 'human');                       // human/assisted only
 *   engine.sendReply(null);                                   // end the run early
 *   engine.terminate();
 *
 * Worker messages routed to handlers:
 *   progress -> onProgress({ loaded, total })
 *   init     -> onInit(payload)               (human/assisted, once per start)
 *   msg      -> onMessage(message)            message.type 'snapshot' | 'answer';
 *               snapshots also fire onSnapshot(message) for Task-1 compatibility
 *   done     -> onDone(msg) and resolves start(): { card, scoreReport, decisionsCsv,
 *               actions, actionsJsonl, annotatedLogJsonl }
 *   error    -> onError(err) and rejects start()
 *
 * Human/assisted protocol: each snapshot must eventually be answered with exactly one
 * sendAction (or sendReply(null) to finish); any number of sendQuery calls may precede
 * it. Each query is answered by an onMessage({ type:'answer', ... }) (possibly with an
 * 'error' field when the query or a submitted action is invalid — the run keeps
 * waiting in that case).
 */
class ConsoleEngine {
  constructor(handlers = {}) {
    this.onProgress = handlers.onProgress || (() => {});
    this.onInit = handlers.onInit || (() => {});
    this.onMessage = handlers.onMessage || (() => {});
    this.onSnapshot = handlers.onSnapshot || (() => {});
    this.onDone = handlers.onDone || (() => {});
    this.onError = handlers.onError || ((err) => console.error(err));
    this.worker = null;
    this.bridge = null;
    this._encoder = new TextEncoder();
    this._resolve = null;
    this._reject = null;
  }

  start(card, mode, options = {}) {
    if (!this.worker) {
      this.worker = new Worker('./worker.js');
      this.worker.onmessage = (event) => this._route(event.data);
      this.worker.onerror = (event) => this._fail(new Error(event.message || 'worker error'));
    }
    const done = new Promise((resolve, reject) => {
      this._resolve = resolve;
      this._reject = reject;
    });
    this.worker.postMessage({ type: 'start', card, mode, actions: options.actions || null,
                              observe: !!options.observe });
    return done;
  }

  /* Write one reply JSON into the bridge: {type:'query',...} or
   * {type:'action', action, source}; null/empty ends the run (agent returns None). */
  sendReply(reply) {
    if (!this.bridge) throw new Error('no bridge: worker is not in human/assisted mode');
    const bytes = reply == null ? new Uint8Array(0) : this._encoder.encode(JSON.stringify(reply));
    if (bytes.length > this.bridge.u8.length) throw new Error('reply JSON exceeds bridge capacity');
    this.bridge.u8.set(bytes);
    Atomics.store(this.bridge.i32, 1, bytes.length);
    Atomics.store(this.bridge.i32, 0, 1);
    Atomics.notify(this.bridge.i32, 0);
  }

  sendQuery(query) {
    this.sendReply({ type: 'query', ...query });
  }

  sendAction(action, source = 'human') {
    this.sendReply({ type: 'action', action, source });
  }

  terminate() {
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
      this.bridge = null;
    }
  }

  _route(msg) {
    if (msg.type === 'progress') {
      this.onProgress(msg);
    } else if (msg.type === 'init') {
      this.onInit(msg.payload);
    } else if (msg.type === 'bridge') {
      this.bridge = { i32: new Int32Array(msg.sab, 0, 2), u8: new Uint8Array(msg.sab, 8) };
    } else if (msg.type === 'msg') {
      if (msg.message.type === 'snapshot') this.onSnapshot(msg.message);
      this.onMessage(msg.message);
    } else if (msg.type === 'snapshot') { // legacy worker shape (kept for golden.v1 tooling)
      this.onSnapshot(msg.snapshot);
      this.onMessage({ type: 'snapshot', snapshot: msg.snapshot });
    } else if (msg.type === 'done') {
      this.onDone(msg);
      if (this._resolve) this._resolve(msg);
    } else if (msg.type === 'error') {
      this._fail(new Error(msg.message));
    }
  }

  _fail(err) {
    this.onError(err);
    if (this._reject) this._reject(err);
  }
}
