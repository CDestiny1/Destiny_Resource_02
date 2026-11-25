/* Worker que corre Python (Pyodide) fuera del hilo principal para que la pantalla no se congele. */
const PYODIDE_VERSION = "0.26.4";
const INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PY_FILES = ["archive.py", "database.py", "team_assets.py", "bridge.py"];

importScripts(INDEX_URL + "pyodide.js");

let bridge = null;

async function init() {
  postMessage({ type: "progress", text: "Descargando el motor Python (solo la primera vez)…" });
  const pyodide = await loadPyodide({ indexURL: INDEX_URL });
  postMessage({ type: "progress", text: "Cargando el administrador de database…" });
  pyodide.FS.mkdir("/app");
  for (const name of PY_FILES) {
    const response = await fetch("py/" + name);
    if (!response.ok) throw new Error("No se pudo cargar py/" + name);
    pyodide.FS.writeFile("/app/" + name, await response.text());
  }
  pyodide.runPython('import sys\nsys.path.insert(0, "/app")');
  bridge = pyodide.pyimport("bridge");
}

const ready = init().then(
  () => postMessage({ type: "ready" }),
  (error) => postMessage({ type: "fatal", text: String((error && error.message) || error) })
);

onmessage = async (event) => {
  const { id, method, path, headers, body } = event.data;
  try {
    await ready;
    if (!bridge) throw new Error("El motor Python no pudo iniciarse");
    const result = bridge.handle(method, path, JSON.stringify(headers || {}), body);
    const meta = JSON.parse(result.get(0));
    const bodyProxy = result.get(1);
    const view = bodyProxy.getBuffer("u8");
    const out = view.data.slice();           // copia fuera de la memoria de wasm
    view.release(); bodyProxy.destroy(); result.destroy();
    postMessage({ type: "result", id, status: meta.status, headers: meta.headers, body: out.buffer }, [out.buffer]);
  } catch (error) {
    postMessage({ type: "result", id, status: 500, headers: { "content-type": "application/json; charset=utf-8" },
      body: new TextEncoder().encode(JSON.stringify({ ok: false, error: "Error interno: " + ((error && error.message) || error) })).buffer });
  }
};
