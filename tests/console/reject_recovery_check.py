#!/usr/bin/env python3
"""Human console: after the engine rejects an action, the controls must come back (no reload needed).

Usage: python3 tests/console/reject_recovery_check.py [CONSOLE_BASE_URL]
  default base: http://localhost:8791 (serve web/public/console with COOP/COEP headers).
Exit code 0 only if the rejected action leaves the buttons enabled and a following legal wait advances.
Steps: start -> LEGAL wait15 -> ILLEGAL observe w/o pointing (client-side reject)
       -> set pointing -> autofill -> ILLEGAL duplicate-target observe (engine reject)
       -> page-aliveness probes. Screenshots saved next to this script (v2-*.png).
"""
import asyncio, base64, json, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
import websockets

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8791').rstrip('/')
URL = f'{BASE}/index.html?card=console-s1&mode=human'
OUT = Path(tempfile.mkdtemp(prefix='console-reject-'))
PORT = 19666
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

report = []


async def main():
    prof = tempfile.mkdtemp(prefix='cdp-c2v2-')
    p = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
                          f'--user-data-dir={prof}', '--no-first-run', '--disable-gpu',
                          '--window-size=1400,1000', 'about:blank'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    exceptions, console_errors = [], []
    try:
        tabs = None
        for _ in range(60):
            try:
                tabs = json.load(op.open(f'http://127.0.0.1:{PORT}/json/list')); break
            except Exception:
                time.sleep(0.25)
        tab = [t for t in tabs if t['type'] == 'page'][0]
        async with websockets.connect(tab['webSocketDebuggerUrl'], max_size=None) as ws:
            n = 0

            async def cmd(method, params=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({'id': n, 'method': method, 'params': params or {}}))
                while True:
                    r = json.loads(await ws.recv())
                    m = r.get('method')
                    if m == 'Runtime.consoleAPICalled' and r['params'].get('type') in ('error', 'warning'):
                        console_errors.append(' '.join(str(a.get('value', a.get('description', '')))
                                                       for a in r['params']['args'])[:300])
                    if m == 'Runtime.exceptionThrown':
                        exceptions.append(json.dumps(r['params']['exceptionDetails'])[:400])
                    if r.get('id') == n:
                        return r

            async def js(expr):
                r = await cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True,
                                                   'awaitPromise': True})
                res = r.get('result', {})
                if 'exceptionDetails' in res:
                    return f'__JSERR__ {json.dumps(res["exceptionDetails"])[:600]}'
                return res.get('result', {}).get('value')

            async def wait_js(expr, timeout, label):
                t0 = time.time()
                while time.time() - t0 < timeout:
                    v = await js(expr)
                    if v and not (isinstance(v, str) and v.startswith('__JSERR__')):
                        return v
                    await asyncio.sleep(1.0)
                raise TimeoutError(f'{label} after {timeout}s')

            async def shot(name):
                r = await cmd('Page.captureScreenshot', {'format': 'png'})
                (OUT / name).write_bytes(base64.b64decode(r['result']['data']))
                report.append(f'screenshot: {name}')

            async def state(tag):
                s = await js("""(()=>({title:document.title,
                    seq:(document.getElementById('seq')||{}).textContent,
                    score:(document.getElementById('score')||{}).textContent,
                    errbar:(document.getElementById('errbar')||{hidden:true}).hidden ? '' :
                           document.getElementById('errbar').innerText,
                    wait15_disabled:(document.getElementById('wait15-btn')||{}).disabled,
                    app_hidden:(document.getElementById('app')||{}).hidden}))()""")
                report.append(f'[{tag}] {json.dumps(s, ensure_ascii=False)}')
                return s

            await cmd('Runtime.enable'); await cmd('Page.enable')
            await cmd('Page.navigate', {'url': URL})

            # 1. start screen -> click Start (retry until boot() listener catches it)
            await wait_js("!!document.getElementById('start-btn')", 60, 'start-btn')
            await shot('v2-01-start-screen.png')
            t0 = time.time()
            while time.time() - t0 < 120:
                await js("document.getElementById('start-btn').click(); 1")
                await asyncio.sleep(3)
                if await js("document.getElementById('start-screen').hidden"):
                    break
            else:
                raise TimeoutError('start-screen never hidden after repeated clicks')

            # 2. wait for app ready (cold Pyodide load can take a while)
            await wait_js("!document.getElementById('app').hidden && "
                          "document.getElementById('wait15-btn').disabled === false && "
                          "document.getElementById('seq').textContent", 600, 'app ready')
            s0 = await state('loaded')
            seq0 = s0['seq']
            await shot('v2-02-loaded.png')

            # 3. LEGAL action: wait 15 min
            await js("document.getElementById('wait15-btn').click(); 1")
            await wait_js(f"document.getElementById('seq').textContent !== {json.dumps(seq0)} && "
                          "document.getElementById('wait15-btn').disabled === false", 180,
                          'seq advance after legal wait')
            s1 = await state('after LEGAL wait15')
            report.append(f"LEGAL wait15 accepted: seq {seq0} -> {s1['seq']}, score {s0['score']} -> {s1['score']}")
            await shot('v2-03-legal-wait.png')

            # 4. ILLEGAL action #1 (client-side): observe with no pointing set
            await js("document.getElementById('observe-btn').click(); 1")
            await asyncio.sleep(2)
            s2 = await state('after ILLEGAL observe w/o pointing')
            rej1 = bool(s2['errbar'])
            report.append(f"ILLEGAL#1 no-pointing observe rejected={rej1}: errbar={s2['errbar']!r}, "
                          f"seq still {s2['seq']} (unchanged={s2['seq'] == s1['seq']}), "
                          f"buttons still enabled={s2['wait15_disabled'] is False}")
            await shot('v2-04-illegal-no-pointing.png')

            # 5. set a pointing by clicking the sky canvas centre
            rect = await wait_js("(()=>{const c=document.getElementById('sky'); if(!c) return null;"
                                 "const r=c.getBoundingClientRect(); if(!r.width) return null;"
                                 "return {x:r.left+r.width/2, y:r.top+r.height/2};})()", 60, 'sky canvas rect')
            report.append(f'sky canvas centre: {rect}')
            for t in ('mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent', {'type': t, 'x': rect['x'], 'y': rect['y'],
                                                       'button': 'left', 'clickCount': 1})
            info = await wait_js("document.getElementById('sky-info').textContent.includes('候选') && "
                                 "document.getElementById('sky-info').textContent", 120, 'field candidates')
            report.append(f'pointing set: {info}')

            # 6. autofill legal assignments, then corrupt: same target on two fibres
            await js("document.getElementById('autofill-btn').click(); 1")
            await wait_js("[...document.querySelectorAll('#fibre-grid select')].filter(s=>s.value).length >= 2",
                          120, 'autofill filled >=2 fibres')
            dup = await js("""(()=>{
              const filled=[...document.querySelectorAll('#fibre-grid select')].filter(s=>s.value);
              const v=filled[0].value, s2=filled[1];
              if(![...s2.options].some(o=>o.value===v)) s2.add(new Option(v,v));
              s2.value=v; s2.dispatchEvent(new Event('change'));
              const a={}; for(const s of document.querySelectorAll('#fibre-grid select')) if(s.value) a[s.dataset.fid]=s.value;
              return a;})()""")
            n_filled = await js("[...document.querySelectorAll('#fibre-grid select')].filter(s=>s.value).length")
            report.append(f'autofill filled {n_filled} fibres; corrupted to duplicate-target: {dup}')
            await shot('v2-05-illegal-dup-form.png')

            # 7. ILLEGAL action #2 (engine-side): submit duplicate-target observe
            seq_pre = (await state('before ILLEGAL dup observe'))['seq']
            score_pre = (await js("document.getElementById('score').textContent"))
            await js("document.getElementById('observe-btn').click(); 1")
            t0 = time.time(); err2 = ''
            while time.time() - t0 < 120:
                v = await js("!document.getElementById('errbar').hidden && "
                             "document.getElementById('errbar').innerText")
                if v and '指向' not in v:  # ignore the earlier client-side message if still shown
                    err2 = v; break
                await asyncio.sleep(1.0)
            s3 = await state('after ILLEGAL dup observe')
            report.append(f"ILLEGAL#2 duplicate-target rejected={bool(err2)}: errbar={err2!r}, "
                          f"seq still {s3['seq']} (unchanged={s3['seq'] == seq_pre}), "
                          f"score unchanged={s3['score'] == score_pre}")
            await shot('v2-06-illegal-dup-rejected.png')

            # 8. page-aliveness probes after engine rejection
            alive = {'title_ok': s3['title'] not in ('RUN ERROR', ''),
                     'app_visible': s3['app_hidden'] is False,
                     'exceptions': len(exceptions),
                     'buttons_enabled': s3['wait15_disabled'] is False}
            # try one more LEGAL wait15 and watch seq for 15 s
            await js("document.getElementById('wait15-btn').click(); 1")
            t0 = time.time(); advanced = False
            while time.time() - t0 < 15:
                if (await js("document.getElementById('seq').textContent")) != s3['seq']:
                    advanced = True; break
                await asyncio.sleep(1.0)
            alive['wait15_advances_seq'] = advanced
            RESULT['ok'] = bool(alive['buttons_enabled'] and advanced and alive['exceptions'] == 0)
            report.append(f'aliveness after engine rejection: {json.dumps(alive)}')
            if advanced:
                s4 = await state('after post-rejection LEGAL wait15')
                report.append(f"post-rejection LEGAL wait15 accepted: seq {s3['seq']} -> {s4['seq']}")
            await shot('v2-07-final.png')

            report.append(f'page exceptions: {len(exceptions)}; console error/warn: {len(console_errors)}')
            for e in exceptions[:5]:
                report.append(f'  EXC {e}')
            for c in console_errors[:5]:
                report.append(f'  CON {c}')
    finally:
        p.terminate()
    print('\n'.join(report))
    return RESULT

RESULT = {}
sys.exit(0 if asyncio.run(main()).get('ok') else 1)
