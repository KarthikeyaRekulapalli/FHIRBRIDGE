"use strict";
/* FHIR EHR Bridge UI.
 * Flow: configure -> search -> select records -> (review candidate match) -> retrieve or summarize.
 * Any change upstream (new search, selection change) clears everything downstream, so a
 * previous patient's records or summary can never be shown under a new selection.
 * No user, patient, tenant or search value is pre-filled; everything comes from the
 * server's /api/config or from what the user types. */

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const LABEL = { cerner: "Cerner", athena: "athenahealth" };

const state = {
  config: null,
  sources: [],          // sources the user ticked (subset of ready providers)
  clusters: [],         // last search result
  selected: new Map(),  // "source:id" -> member card
};

/* ---------- transport ---------- */
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (r.status === 401) {
    location.assign("/auth/login"); // session missing or expired: sign in with Microsoft
    throw new Error("sign in required");
  }
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { const j = await r.json(); if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep */ }
    throw new Error(detail);
  }
  return r.json();
}

/* ---------- status / errors ---------- */
function setStatus(kind, text) {
  const bar = $("statusbar");
  if (!kind) { bar.hidden = true; return; }
  bar.hidden = false;
  bar.className = `statusbar ${kind}`;
  bar.textContent = text;
}
function banner(kind, text) {
  const b = el("div", `banner ${kind}`, text);
  const x = el("button", "x", "×");
  x.onclick = () => b.remove();
  b.appendChild(x);
  $("errbar").appendChild(b);
}
const clearBanners = () => { $("errbar").innerHTML = ""; };

/* ---------- stale-state control ---------- */
function clearOutput() { $("output").innerHTML = ""; $("review").hidden = true; $("review").innerHTML = ""; setStatus(null); }
function clearResults() { clearOutput(); state.selected.clear(); state.clusters = []; $("results").innerHTML = ""; }

/* ---------- config ---------- */
async function loadConfig() {
  clearResults();
  try {
    state.config = await api("/api/config");
  } catch (err) {
    if (err.message !== "sign in required") { $("status").textContent = "backend unreachable"; banner("error", `Could not load configuration: ${err.message}`); }
    return;
  }
  $("searchPanel").hidden = false;
  renderSources();
  const ai = state.config.ai;
  $("status").textContent = (state.config.user ? `${state.config.user} · ` : "") + (ai.name
    ? `AI: ${ai.name} → ${ai.data_destination}`
    : "AI provider not configured");
  $("signout").hidden = !state.config.user;
  for (const p of state.config.problems || []) banner("error", `Configuration: ${p}`);
  if (ai.problems && ai.problems.length) banner("warn", `AI provider: ${ai.problems.join("; ")}`);
  for (const [src, p] of Object.entries(state.config.providers)) {
    if (p.state === "not_configured") banner("warn", `${p.label} is not configured: ${p.problems.join("; ")}`);
  }
  if (!state.sources.length) banner("error", "No EHR is ready. Fix the configuration and restart the service.");
}

function renderSources() {
  const box = $("sources");
  box.innerHTML = "";
  state.sources = [];
  box.appendChild(el("span", "lbl", "Search in:"));
  for (const [src, p] of Object.entries(state.config.providers)) {
    const ready = p.state === "ready";
    const lab = el("label");
    const cb = el("input");
    cb.type = "checkbox"; cb.checked = ready; cb.disabled = !ready;
    cb.onchange = () => {
      state.sources = [...box.querySelectorAll("input:checked")].map((c) => c.value);
    };
    cb.value = src;
    if (ready) state.sources.push(src);
    lab.append(cb, el("span", `badge ${src}`, p.label), ready ? "" : el("span", "muted", ` (${p.state.replace("_", " ")})`));
    box.appendChild(lab);
  }
}

/* ---------- search ---------- */
async function doSearch() {
  clearBanners();
  clearResults();
  const given = $("given").value.trim(), family = $("family").value.trim();
  const dob = $("dob").value, gender = $("gender").value;
  if (!given && !family && !dob) { banner("warn", "Enter a first name, last name or date of birth."); return; }
  if (!state.sources.length) { banner("warn", "Select at least one EHR to search."); return; }
  const q = new URLSearchParams();
  if (given) q.set("given", given);
  if (family) q.set("family", family);
  if (dob) q.set("birth_date", dob);
  if (gender) q.set("gender", gender);
  q.set("sources", state.sources.join(","));
  setStatus("working", `Searching ${state.sources.map((s) => LABEL[s]).join(" and ")}…`);
  $("searchBtn").disabled = true;
  try {
    const data = await api(`/api/search?${q}`);
    state.clusters = data.clusters;
    renderResults(data);
    for (const e of data.errors) banner("error", `Search failed in one EHR: ${e}`);
    for (const s of data.truncated) banner("warn", `${LABEL[s]} returned more records than shown; narrow the search.`);
    if (!data.results.length) setStatus(data.errors.length ? "error" : "done", data.errors.length ? "Search did not complete in every EHR." : "No records matched.");
    else setStatus(data.errors.length ? "error" : "done", `${data.results.length} record(s) found${data.errors.length ? ", but one EHR failed" : ""}.`);
  } catch (err) {
    setStatus("error", "Search failed.");
    if (err.message !== "sign in required") banner("error", err.message);
  } finally {
    $("searchBtn").disabled = false;
  }
}

function renderResults(data) {
  const root = $("results");
  root.innerHTML = "";
  if (!data.results.length) return;
  root.appendChild(el("h2", null, "Matches"));
  for (const c of data.clusters) root.appendChild(renderCluster(c));
  const bar = el("div", "actions");
  bar.id = "actions";
  bar.appendChild(el("span", "selinfo", ""));
  const rec = el("button", "btn ghost", "Retrieve records"); rec.id = "retrieveBtn"; rec.onclick = () => startAction("records");
  const sum = el("button", "btn", "Summarize"); sum.id = "summarizeBtn"; sum.onclick = () => startAction("summary");
  bar.append(rec, sum);
  root.appendChild(bar);
  updateActions();
}

function renderCluster(c) {
  const box = el("div", "cluster");
  const multi = c.members.length > 1;
  const head = el("div", "cluster-head");
  head.appendChild(el("span", "name", c.display_name));
  head.appendChild(el("span", "meta", `DOB ${c.birth_date || "unknown"} · ${c.gender || "gender unknown"}`));
  head.appendChild(el("span", multi ? "flag candidate" : "flag", multi
    ? `Candidate match across ${c.members.length} EHRs (${Math.round(c.confidence * 100)}% agreement)`
    : "Single EHR record"));
  box.appendChild(head);
  if (multi) {
    const ev = el("div", "evidence");
    ev.appendChild(el("span", null, `Agrees on: ${c.evidence.join(", ") || "nothing"}.`));
    if (c.conflicts.length) ev.appendChild(el("span", "conflict", ` Conflicts: ${c.conflicts.join("; ")}.`));
    box.appendChild(ev);
  }
  for (const m of c.members) box.appendChild(renderMember(m));
  return box;
}

function renderMember(m) {
  const row = el("label", "member");
  const key = `${m.source}:${m.source_id}`;
  const cb = el("input"); cb.type = "checkbox"; cb.checked = state.selected.has(key);
  cb.onchange = () => {
    clearOutput(); // selection changed: anything retrieved or summarized is stale
    if (cb.checked) state.selected.set(key, m); else state.selected.delete(key);
    updateActions();
  };
  row.appendChild(cb);
  row.appendChild(el("span", `badge ${m.source}`, LABEL[m.source]));
  const who = el("div", "who");
  who.appendChild(el("span", "full", m.full_name));
  who.appendChild(el("span", "demo", `DOB ${m.birth_date || "unknown"} · ${m.gender || "gender unknown"}${m.mrn ? ` · MRN ${m.mrn}` : ""}`));
  who.appendChild(el("span", "id", `${LABEL[m.source]} id ${m.source_id}`));
  row.appendChild(who);
  row.appendChild(el("span", "score", `${Math.round(m.match_score * 100)}% match to search`));
  return row;
}

function updateActions() {
  const bar = $("actions");
  if (!bar) return;
  const n = state.selected.size, max = state.config.max_selections;
  bar.querySelector(".selinfo").textContent = n ? `${n} record(s) selected` : "Select one or more records";
  const ok = n > 0 && n <= max;
  bar.querySelector("#retrieveBtn").disabled = !ok;
  bar.querySelector("#summarizeBtn").disabled = !ok;
  if (n > max) banner("warn", `At most ${max} records can be combined.`);
}

/* ---------- review step before combining records ---------- */
function startAction(kind) {
  clearOutput();
  clearBanners();
  const sels = [...state.selected.values()];
  if (sels.length < 2 || kind === "records") { run(kind, false); return; }
  const box = $("review");
  box.hidden = false;
  box.appendChild(el("h2", null, "Confirm these records belong to the same person"));
  const ul = el("ul");
  for (const m of sels) ul.appendChild(el("li", null, `${LABEL[m.source]}: ${m.full_name}, DOB ${m.birth_date || "unknown"}, ${m.gender || "gender unknown"}, id ${m.source_id}`));
  box.appendChild(ul);
  const notes = [];
  for (const c of state.clusters) {
    const inCluster = c.members.filter((m) => state.selected.has(`${m.source}:${m.source_id}`)).length;
    if (inCluster >= 2) notes.push(`Candidate match: agrees on ${c.evidence.join(", ")}${c.conflicts.length ? `; conflicts: ${c.conflicts.join("; ")}` : ""}.`);
  }
  const sameSource = new Set(sels.map((m) => m.source)).size < sels.length;
  if (sameSource) notes.push("Two selected records come from the same EHR; they cannot be the same record.");
  if (!notes.length) notes.push("These records were NOT identified as a candidate match (birth dates or names differ). Combine only if you have verified identity another way.");
  for (const n of notes) box.appendChild(el("p", n.startsWith("Candidate") ? "ok" : "conflict", n));
  const row = el("div", "row");
  const yes = el("button", "btn", "Confirm and summarize"); yes.onclick = () => run("summary", true);
  const no = el("button", "btn ghost", "Cancel"); no.onclick = clearOutput;
  row.append(yes, no);
  box.appendChild(row);
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function run(kind, confirmed) {
  const selections = [...state.selected.values()].map((m) => ({ source: m.source, patient_id: m.source_id }));
  const snapshot = selections.map((s) => `${s.source}:${s.patient_id}`).join("|");
  clearOutput();
  setStatus("working", kind === "summary" ? "Retrieving records and generating summary…" : "Retrieving records…");
  try {
    const body = kind === "summary" ? { selections, confirmed_same_person: confirmed } : { selections };
    const data = await api(`/api/${kind}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    // ignore the response if the selection changed while the request was in flight
    if ([...state.selected.keys()].join("|") !== snapshot) return;
    if (kind === "summary") renderSummary(data); else renderRecords(data.records);
    setStatus("done", kind === "summary" ? `Summary generated by ${data.provider}.` : "Records retrieved. No summary generated.");
    $("output").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setStatus("error", kind === "summary" ? "Summary failed." : "Retrieval failed.");
    if (err.message !== "sign in required") banner("error", err.message);
  }
}

/* ---------- output ---------- */
function renderRecords(perSource) {
  const out = $("output");
  out.appendChild(el("h2", null, "Retrieved records"));
  out.appendChild(sourceCards(perSource));
}

function renderSummary(s) {
  const out = $("output");
  const nar = el("div", "narrative");
  nar.appendChild(el("h2", null, "AI summary"));
  nar.appendChild(el("div", "meta", `Sources: ${s.sources.map((x) => LABEL[x]).join(" + ")} · provider ${s.provider} · data sent to ${s.data_destination}`));
  nar.appendChild(el("p", "text", s.narrative));
  for (const o of s.omitted) nar.appendChild(el("div", "conflict", `Not included in the summary input: ${o}`));
  nar.appendChild(el("div", "disclaimer", s.disclaimer));
  out.appendChild(nar);
  out.appendChild(el("h2", null, "Source records"));
  out.appendChild(sourceCards(s.per_source));
}

function sourceCards(perSource) {
  const cols = el("div", "cols");
  for (const ps of perSource) {
    const c = el("div", "srccard");
    const h = el("header");
    h.append(el("span", `badge ${ps.patient.source}`, LABEL[ps.patient.source]), el("span", "full", ps.patient.full_name),
      el("span", "id", `id ${ps.patient.source_id}`));
    c.appendChild(h);
    c.appendChild(section("Conditions", ps.conditions, (x) => `${x.text}${x.clinical_status ? ` (${x.clinical_status})` : ""}`));
    c.appendChild(section("Medications", ps.medications, (x) => `${x.text}${x.dosage ? ` — ${x.dosage}` : ""}${x.status ? ` (${x.status})` : ""}`));
    c.appendChild(section("Allergies", ps.allergies, (x) => `${x.text}${x.reaction ? ` → ${x.reaction}` : ""}${x.criticality === "high" ? " (high criticality)" : ""}`));
    c.appendChild(section("Vital signs", ps.observations, (x) => `${x.text}${x.value ? `: ${x.value}` : ""}${x.effective ? ` (${x.effective.slice(0, 10)})` : ""}`));
    c.appendChild(section("Encounters", ps.encounters, (x) => `${x.text}${x.period_start ? ` (${x.period_start.slice(0, 10)})` : ""}`));
    if (ps.fetch_errors.length) c.appendChild(el("div", "conflict", `Could not retrieve: ${ps.fetch_errors.join(", ")}.`));
    if (ps.truncated.length) c.appendChild(el("div", "muted", `Partial (more exist in the EHR): ${ps.truncated.join(", ")}.`));
    cols.appendChild(c);
  }
  return cols;
}

function section(title, items, fmt) {
  const sec = el("div", "section");
  sec.appendChild(el("h3", null, title));
  if (!items.length) { sec.appendChild(el("div", "muted", "None recorded")); return sec; }
  const ul = el("ul");
  for (const it of items) ul.appendChild(el("li", null, fmt(it)));
  sec.appendChild(ul);
  return sec;
}

/* ---------- wiring ---------- */
$("searchBtn").onclick = doSearch;
for (const id of ["given", "family", "dob"]) $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
loadConfig();
