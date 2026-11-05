// ApplyPilot browser helper - background worker: API calls, auto-apply loop.
const TICK_MINUTES = 5;

async function cfg() {
  return chrome.storage.local.get(["base", "token", "autoApply", "log"]);
}

async function log(line) {
  const { log: old = [] } = await chrome.storage.local.get("log");
  const next = [`${new Date().toLocaleTimeString()} - ${line}`, ...old].slice(0, 15);
  await chrome.storage.local.set({ log: next });
}

async function api(path, opts = {}) {
  const { base, token } = await cfg();
  if (!base || !token) throw new Error("Not connected - paste your connection code first");
  const res = await fetch(`${base}/api${path}`, {
    ...opts,
    headers: { "X-ApplyPilot-Token": token, "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* not json */ }
    throw new Error(detail);
  }
  return opts.raw ? res : res.json();
}

async function resumeBase64(versionId) {
  const res = await api(`/ext/resume/${versionId}`, { raw: true });
  const buf = new Uint8Array(await res.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function inject(tabId, fnName, arg) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    func: (name, a) => window.__applypilot[name](a),
    args: [fnName, arg],
  });
  return res ? res.result : null;
}

function waitForLoad(tabId, timeout = 30000) {
  return new Promise((resolve) => {
    const done = () => { chrome.tabs.onUpdated.removeListener(listener); clearTimeout(t); setTimeout(resolve, 3500); };
    const listener = (id, info) => { if (id === tabId && info.status === "complete") done(); };
    const t = setTimeout(done, timeout);
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function buildContext(url) {
  const ctx = await api(`/ext/context?url=${encodeURIComponent(url)}`);
  const resume = ctx.resume ? { name: ctx.resume.filename, b64: await resumeBase64(ctx.resume.version_id) } : null;
  return { profile: ctx.apply_profile || {}, app: ctx.application, resume };
}

async function runFlow(tabId, mode, ctx) {
  let result = { outcome: "needs_attention", detail: "Could not complete the form" };
  for (let pass = 0; pass < 4; pass++) {
    try {
      result = (await inject(tabId, "run", { mode, ...ctx })) || { outcome: "continue" };
    } catch (e) {
      result = { outcome: "continue" };
    }
    if (result.outcome !== "continue") return result;
    await waitForLoad(tabId, 15000);
  }
  return result.outcome === "continue" ? { outcome: "needs_attention", detail: "The application has more steps than expected" } : result;
}

async function processTask(task) {
  const tab = await chrome.tabs.create({ url: task.job_url, active: false });
  await waitForLoad(tab.id);
  const ctx = await buildContext(task.job_url);
  ctx.app = ctx.app || task;
  const result = await runFlow(tab.id, "auto", ctx);
  const outcome = result.outcome === "submitted" ? "submitted" : "needs_attention";
  await api(`/ext/applications/${task.id}/result`, { method: "POST", body: JSON.stringify({ outcome, detail: result.detail || "" }) });
  await log(`${task.job_title} at ${task.company || task.board}: ${outcome === "submitted" ? "submitted" : result.detail}`);
  if (outcome === "submitted") chrome.tabs.remove(tab.id);
}

async function tick(force = false) {
  const { autoApply } = await cfg();
  if (!autoApply && !force) return { ok: true, skipped: true };
  const { tasks, reason } = await api("/ext/tasks");
  if (!tasks.length) {
    await log(`Nothing to submit (${reason})`);
    return { ok: true, reason };
  }
  for (const task of tasks) await processTask(task);
  return { ok: true, processed: tasks.length };
}

async function pollJob(oppId) {
  for (let i = 0; i < 20; i++) {
    await new Promise((r) => setTimeout(r, 4000));
    const s = await api(`/ext/jobs/${oppId}`);
    if (s.application || s.error || s.match) return s;
  }
  return null;
}

chrome.alarms.create("applypilot-tick", { periodInMinutes: TICK_MINUTES });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "applypilot-tick") tick().catch((e) => log(`Auto-apply error: ${e.message}`));
});

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    if (msg.type === "me") return api("/ext/me");
    if (msg.type === "save") {
      const job = await inject(msg.tabId, "extract");
      const saved = await api("/ext/jobs", { method: "POST", body: JSON.stringify(job) });
      await log(`Saved: ${job.title}${saved.created ? "" : " (already saved)"}`);
      if (saved.created) pollJob(saved.opportunity_id).then((s) => s && log(
        s.error ? `Match failed: ${s.error}` : `${s.job_title}: ${s.match ? s.match.score + "% match" : ""}${s.application ? ", application " + s.application.status.replace("_", " ") : ""}`));
      return { ...saved, title: job.title };
    }
    if (msg.type === "autofill") {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      return runFlow(msg.tabId, "fill", await buildContext(tab.url));
    }
    if (msg.type === "tick") return tick(true);
    return null;
  })().then((r) => reply({ ok: true, data: r })).catch((e) => reply({ ok: false, error: e.message }));
  return true;
});
