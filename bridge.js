/* Puente: imita fetch() hacia el servidor local, pero habla con el worker de Python. */
window.DFP = (() => {
  const worker = new Worker("pyworker.js");
  const pending = new Map();
  let nextId = 1;
  let overlay = null;
  let resolveReady, rejectReady;
  const ready = new Promise((res, rej) => { resolveReady = res; rejectReady = rej; });

  function showOverlay(text, isError = false) {
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:14px;padding:24px;text-align:center;background:rgba(255,255,255,.96);color:#2a2a3c;font:600 16px system-ui,sans-serif";
      overlay.innerHTML = '<div style="font-size:30px;font-weight:800;color:#ff3d8b">Destiny</div><div id="dfpBootText"></div>';
      (document.body || document.documentElement).append(overlay);
    }
    const label = overlay.querySelector("#dfpBootText");
    label.textContent = text;
    label.style.color = isError ? "#c0153c" : "#2a2a3c";
  }
  const hideOverlay = () => { if (overlay) { overlay.remove(); overlay = null; } };

  document.addEventListener("DOMContentLoaded", () => showOverlay("Preparando el motor…"));

  worker.onmessage = (event) => {
    const m = event.data;
    if (m.type === "progress") showOverlay(m.text);
    else if (m.type === "ready") { hideOverlay(); resolveReady(); }
    else if (m.type === "fatal") {
      showOverlay("No se pudo iniciar el motor Python: " + m.text + ". Revisa tu conexión (la primera vez necesita internet) y recarga.", true);
      rejectReady(new Error(m.text));
    } else if (m.type === "result") {
      const job = pending.get(m.id); pending.delete(m.id);
      if (job) job.resolve(m);
    }
  };

  async function fetchLike(path, options = {}) {
    await ready;
    const method = (options.method || "GET").toUpperCase();
    const headers = {};
    for (const [k, v] of Object.entries(options.headers || {})) headers[k.toLowerCase()] = String(v);
    const body = options.body == null ? new Uint8Array(0) : new Uint8Array(await new Response(options.body).arrayBuffer());
    const id = nextId++;
    const done = new Promise((resolve) => pending.set(id, { resolve }));
    worker.postMessage({ id, method, path, headers, body }, [body.buffer]);
    const m = await done;
    const out = new Headers();
    for (const [k, v] of Object.entries(m.headers || {})) out.set(k, v);
    return new Response(m.body, { status: m.status, headers: out });
  }

  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
  return { fetch: fetchLike };
})();
