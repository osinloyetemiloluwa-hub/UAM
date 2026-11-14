/* NanoMuse Python worker — CPython compiled to WebAssembly (Pyodide), off the UI thread. */
const BASE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
importScripts(BASE + 'pyodide.js');
const PIP = { docx: 'python-docx', PIL: 'pillow', qrcode: 'qrcode', reportlab: 'reportlab' };
let py = null, booting = null;
const say = (s) => postMessage({ t: 'status', s });

function boot() {
  return booting || (booting = (async () => {
    say('Loading Python (WebAssembly)…');
    py = await loadPyodide({ indexURL: BASE });
    py.runPython("import os\nos.environ['MPLBACKEND']='Agg'\nos.makedirs('/home/pyodide/ws',exist_ok=True)");
    return py;
  })().catch((e) => { booting = null; throw e; }));
}

async function exec(code) {
  await py.loadPackagesFromImports(code);
  await py.runPythonAsync(code);
}

async function run(id, code, sid) {
  let out = '', err = '';
  try {
    await boot();
    const ws = '/home/pyodide/ws/' + String(sid || 'anon').replace(/[^\w-]/g, '').slice(0, 40);
    py.globals.set('_ws', ws);
    py.runPython("import os\nos.makedirs(_ws,exist_ok=True)\nos.chdir(_ws)");
    const snap = () => JSON.parse(py.runPython(
      "import json\njson.dumps({n:[os.stat(n).st_size,os.stat(n).st_mtime_ns] for n in [os.path.join(d,f)[2:] for d,_,fs in os.walk('.') for f in fs]})"));
    const before = snap();
    const sink = { batched: (s) => { out += s + '\n'; } };
    py.setStdout(sink); py.setStderr(sink);
    try { await exec(code); }
    catch (e) {
      err = String(e.message || e);
      const m = /No module named '(\w+)'/.exec(err);
      if (m) {
        try {
          say('Installing ' + m[1] + '…');
          await py.loadPackage('micropip');
          await py.pyimport('micropip').install(PIP[m[1]] || m[1]);
          err = ''; await exec(code);
        } catch (e2) { err = String(e2.message || e2); }
      }
    }
    const after = snap(), files = [], bad = [], xfer = [];
    for (const [n, [size, mt]] of Object.entries(after)) {
      if (before[n] && before[n][1] === mt) continue;
      if (n === 'main.py' || n.startsWith('.')) continue;
      if (!size) { bad.push(n + ': EMPTY (0 bytes)'); continue; }
      const bytes = py.FS.readFile(ws + '/' + n);
      files.push({ name: n, size, bytes }); xfer.push(bytes.buffer);
    }
    let text = (out.trim() ? 'stdout:\n' + out.slice(-3000) + '\n\n' : '');
    if (err) text += 'stderr:\n' + err.slice(-3000) + '\n\nThe script failed. Read the traceback and fix it.\n\n';
    text += 'exit code: ' + (err ? 1 : 0);
    if (files.length) text += '\n\nVALIDATED files: ' + files.map((f) => f.name).join(', ');
    if (bad.length) text += '\n\nPROBLEMS — fix these and run again:\n' + bad.join('\n');
    if (!files.length && !bad.length) text += '\n\nNo files were created. Did you forget savefig/to_excel/open().write()?';
    postMessage({ t: 'done', id, text, files }, xfer);
  } catch (e) {
    postMessage({ t: 'done', id, text: 'Python runtime failed to start: ' + (e.message || e), files: [] });
  }
}

onmessage = (e) => { if (e.data.t === 'run') run(e.data.id, e.data.code, e.data.sid); else if (e.data.t === 'warm') boot().catch(() => {}); };
