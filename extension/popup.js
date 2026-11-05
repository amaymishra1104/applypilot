const $ = (id) => document.getElementById(id);
const say = (text, bad) => { $("msg").textContent = text; $("msg").style.color = bad ? "#b91c1c" : "#0f766e"; };
const send = (msg) => new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
const activeTab = async () => (await chrome.tabs.query({ active: true, currentWindow: true }))[0];

async function renderLog() {
  const { log = [] } = await chrome.storage.local.get("log");
  $("log").innerHTML = "";
  log.forEach((l) => { const li = document.createElement("li"); li.textContent = l; $("log").appendChild(li); });
}

async function init() {
  const { token, autoApply } = await chrome.storage.local.get(["token", "autoApply"]);
  $("connect").hidden = !!token;
  $("main").hidden = !token;
  if (!token) return;
  $("auto").checked = !!autoApply;
  const me = await send({ type: "me" });
  if (!me.ok) return say(me.error, true);
  const a = me.data.autopilot || {};
  $("who").textContent = `Signed in as ${me.data.email || me.data.name}. ${a.paused ? "Emergency stop is ON." : a.mode === "auto" && a.enabled ? `Auto mode: ${a.min_match_score}%+ jobs go out automatically.` : "Approval mode: only approved jobs are submitted."}`;
  renderLog();
}

$("connectBtn").onclick = async () => {
  try {
    const { u, t } = JSON.parse(atob($("code").value.trim()));
    if (!u || !t) throw new Error();
    await chrome.storage.local.set({ base: u.replace(/\/$/, ""), token: t });
    init();
  } catch (e) {
    say("That connection code is not valid", true);
  }
};
$("disconnectBtn").onclick = async () => { await chrome.storage.local.clear(); init(); };
$("auto").onchange = async (e) => { await chrome.storage.local.set({ autoApply: e.target.checked }); say(e.target.checked ? "Auto-apply on" : "Auto-apply off"); };
$("saveBtn").onclick = async () => {
  say("Saving...");
  const r = await send({ type: "save", tabId: (await activeTab()).id });
  if (!r.ok) return say(r.error, true);
  say(r.data.created ? `Saved "${r.data.title}". AI matching runs now - see Job Boards in ApplyPilot.` : "Already saved in ApplyPilot");
  renderLog();
};
$("fillBtn").onclick = async () => {
  say("Filling...");
  const r = await send({ type: "autofill", tabId: (await activeTab()).id });
  if (!r.ok) return say(r.error, true);
  say(r.data.detail || "Filled what I could - review and click submit yourself", r.data.outcome === "needs_attention");
};
$("tickBtn").onclick = async () => {
  say("Checking for approved jobs...");
  const r = await send({ type: "tick" });
  if (!r.ok) return say(r.error, true);
  say(r.data.processed ? "Done - see the log below" : r.data.reason || "Nothing to submit");
  renderLog();
};
init();
