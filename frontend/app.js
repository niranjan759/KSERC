const API = "/api/documents";
const COMPARE_API = "/api/comparisons";

let currentDoc = null;
let currentDocId = null;

const docItemsEl = document.getElementById("doc-items");
const contentEl = document.getElementById("content");

let currentComparison = null;
let currentComparisonId = null;
let allDocsForForm = [];

const comparisonItemsEl = document.getElementById("comparison-items");
const compareContentEl = document.getElementById("compare-content");

const SBU_NAMES = { G: "Generation", T: "Transmission", D: "Distribution" };
let currentSbu = "G";
let docPollTimer = null;
let awaitingDocId = null;

async function loadDocList(selectId) {
  const docs = await fetch(API).then(r => r.json());
  docItemsEl.innerHTML = "";
  if (docs.length === 0) {
    docItemsEl.innerHTML = '<div class="doc-item meta">No documents uploaded yet.</div>';
  }
  docs.forEach(d => {
    const el = document.createElement("div");
    el.className = "doc-item" + (d.doc_id === selectId ? " active" : "") + (d.state !== "ready" ? " " + d.state : "");
    if (d.state === "processing") {
      el.innerHTML = `
        <div class="name">${escapeHtml(d.filename || d.doc_id)}</div>
        <div class="meta">Processing… extracting all SBU chapters (large documents take a few minutes)</div>`;
    } else if (d.state === "failed") {
      el.innerHTML = `
        <div class="name">${escapeHtml(d.filename || d.doc_id)}</div>
        <div class="meta invalid">Upload refused: ${escapeHtml(d.error || "")}</div>
        <button class="secondary small" onclick="event.stopPropagation(); deleteDocument('${d.doc_id}', true)">Dismiss</button>`;
    } else {
      el.innerHTML = `
        <div class="name">${escapeHtml(d.filename || d.doc_id)}</div>
        <div class="meta doc-type ${d.doc_type}">${escapeHtml(d.label)}</div>
        <div class="meta">SBU ${d.sbus_available.join(", ")} · ${d.order_table_count} tables · ${d.needs_review_count} flagged</div>
        ${d.updating ? '<div class="meta">Updating… re-extracting with the latest extraction fixes</div>' : ""}`;
      el.onclick = () => selectDocument(d.doc_id);
    }
    docItemsEl.appendChild(el);
  });

  // keep refreshing while anything is still being extracted in the background
  const processing = docs.some(d => d.state === "processing" || d.updating);
  clearTimeout(docPollTimer);
  if (processing) docPollTimer = setTimeout(() => loadDocList(currentDocId), 4000);
  if (awaitingDocId) {
    const d = docs.find(x => x.doc_id === awaitingDocId);
    if (d && d.state === "ready") { awaitingDocId = null; selectDocument(d.doc_id); }
    else if (d && d.state === "failed") { awaitingDocId = null; }
  }
}

async function selectDocument(docId) {
  currentDocId = docId;
  const data = await fetch(`${API}/${docId}`).then(r => r.json());
  currentDoc = data;
  const available = Object.keys(data.sbus || {}).filter(s => data.sbus[s] && !data.sbus[s].error);
  if (!available.includes(currentSbu)) currentSbu = available[0] || "G";
  renderDocument();
  await loadDocList(docId);
}

async function deleteDocument(docId, isFailed) {
  if (!isFailed && !confirm("Delete this document? Comparisons that use it will be marked as broken.")) return;
  await fetch(`${API}/${docId}`, { method: "DELETE" });
  if (docId === currentDocId) { currentDocId = null; currentDoc = null; renderDocument(); }
  await loadDocList(currentDocId);
}

function switchSbu(sbu) {
  currentSbu = sbu;
  renderDocument();
}

function currentSection() {
  const s = currentDoc && currentDoc.sbus ? currentDoc.sbus[currentSbu] : null;
  return s && !s.error ? s : null;
}

function renderDocument() {
  if (!currentDoc) {
    contentEl.innerHTML = '<div class="empty-state">Select a document.</div>';
    return;
  }
  const tabs = ["G", "T", "D"].map(s => {
    const sec = currentDoc.sbus && currentDoc.sbus[s];
    const has = sec && !sec.error;
    return `<button class="tab ${s === currentSbu ? "active" : ""}" ${has ? `onclick="switchSbu('${s}')"` : "disabled"}
      title="${has ? "" : escapeHtml(sec ? sec.error : "Not extracted yet - older uploads are being updated in the background")}">SBU-${s} ${SBU_NAMES[s]}</button>`;
  }).join("");
  const d = currentSection();
  let html = `
    <div class="doc-toolbar">
      <nav class="tabs sbu-tabs">${tabs}</nav>
      <button class="secondary" onclick="deleteDocument('${currentDocId}')">Delete document</button>
    </div>`;
  if (!d) {
    contentEl.innerHTML = html + '<div class="empty-state">This document has no chapter for this SBU.</div>';
    return;
  }
  html += `
    <div class="chapter-banner">
      <b>${escapeHtml(d.chapter_heading || "")}</b><br>
      Source pages ${d.pages ? d.pages[0] + "–" + d.pages[1] : "?"} &middot; ${d.order_tables.length} order tables
      &middot; ${d.reference_tables.length} reference tables excluded
      &middot; ${d.unclassified_fragments.length} unclassified fragments
    </div>
  `;

  html += `<div class="section-heading">Order tables (SBU-${currentSbu} ${SBU_NAMES[currentSbu]})</div>`;
  if (d.order_tables.length === 0) {
    html += `<div class="empty-state">No order tables found.</div>`;
  } else {
    d.order_tables.forEach((t, i) => { html += renderTableCard(t, "order_tables", i, false); });
  }

  if (d.unclassified_fragments.length > 0) {
    html += `<div class="section-heading">Unclassified fragments (pdfplumber found a table-like shape here, but no table number could be matched — needs a human look)</div>`;
    d.unclassified_fragments.forEach((t, i) => { html += renderTableCard(t, "unclassified_fragments", i, true); });
  }

  if (d.reference_tables.length > 0) {
    html += `<div class="section-heading reference-section">Reference material (quoted from Tariff Regulations — not part of the petition's financial claims)</div>`;
    html += `<div class="reference-section">`;
    d.reference_tables.forEach((t, i) => { html += renderTableCard(t, "reference_tables", i, false); });
    html += `</div>`;
  }

  contentEl.innerHTML = html;
  attachGridListeners();
}

function renderTableCard(t, bucket, index, isFragment) {
  const badge = t.table_no ? `Table ${escapeHtml(t.table_no)}` : "Unlabeled";
  const title = t.title || "(no title detected)";
  const pages = t.pages && t.pages.length ? `p.${t.pages.join(", ")}` : "";
  const flags = [];
  if (t.needs_review) flags.push(`<span class="flag review">Needs manual review</span>`);
  if (t.reviewed) flags.push(`<span class="flag reviewed">Reviewed</span>`);

  const headerRow = t.header || [];
  let gridHtml = `<table class="data-grid" data-bucket="${bucket}" data-index="${index}"><thead><tr>`;
  headerRow.forEach(c => { gridHtml += `<th>${escapeHtml(c || "")}</th>`; });
  gridHtml += `</tr>`;
  if (t.unit_row) {
    gridHtml += `<tr class="unit-row">`;
    t.unit_row.forEach(c => { gridHtml += `<td>${escapeHtml(c || "")}</td>`; });
    gridHtml += `</tr>`;
  }
  gridHtml += `</thead><tbody>`;
  (t.data_rows || []).forEach((row, ri) => {
    const mismatch = headerRow.length && row.length !== headerRow.length;
    gridHtml += `<tr data-row="${ri}" class="${mismatch ? "row-mismatch" : ""}">`;
    row.forEach(c => { gridHtml += `<td contenteditable="true">${escapeHtml(c || "")}</td>`; });
    gridHtml += `</tr>`;
  });
  gridHtml += `</tbody></table>`;

  return `
    <div class="table-card ${isFragment ? "fragment-card" : ""}">
      <div class="table-card-header">
        <span class="table-no-badge">${badge}</span>
        <span class="table-title">${escapeHtml(title)}</span>
        <span class="table-pages">${pages}</span>
        ${flags.join(" ")}
        <div class="table-card-actions">
          <button class="secondary" onclick="viewSourcePages('${bucket}', ${index})">View source page</button>
          <button class="secondary" onclick="toggleReviewed('${bucket}', ${index})">${t.reviewed ? "Unmark reviewed" : "Mark reviewed"}</button>
        </div>
      </div>
      <div class="grid-wrap">${gridHtml}</div>
    </div>
  `;
}

function attachGridListeners() {
  document.querySelectorAll("table.data-grid").forEach(grid => {
    grid.addEventListener("blur", (e) => {
      if (e.target.tagName === "TD" && e.target.isContentEditable) {
        saveGrid(grid);
      }
    }, true);
  });
}

async function saveGrid(gridEl) {
  const bucket = gridEl.dataset.bucket;
  const index = parseInt(gridEl.dataset.index, 10);
  const rows = [];
  gridEl.querySelectorAll("tbody tr").forEach(tr => {
    const row = [];
    tr.querySelectorAll("td").forEach(td => row.push(td.textContent));
    rows.push(row);
  });
  await fetch(`${API}/${currentDocId}/${bucket}/${index}?sbu=${currentSbu}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data_rows: rows })
  });
  // keep the in-memory model in sync so a later re-render (e.g. toggling
  // "reviewed" on another table) doesn't wipe this edit back to its
  // pre-edit value.
  currentSection()[bucket][index].data_rows = rows;
}

async function toggleReviewed(bucket, index) {
  const t = currentSection()[bucket][index];
  const reviewed = !t.reviewed;
  await fetch(`${API}/${currentDocId}/${bucket}/${index}?sbu=${currentSbu}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewed })
  });
  t.reviewed = reviewed;
  renderDocument();
}

function viewSourcePages(bucket, index) {
  const t = currentSection()[bucket][index];
  const panel = document.getElementById("source-panel");
  const title = document.getElementById("source-panel-title");
  const body = document.getElementById("source-panel-body");
  title.textContent = `Table ${t.table_no || ""} — page(s) ${(t.pages || []).join(", ")}`;
  body.innerHTML = "";
  (t.pages || []).forEach(p => {
    const img = document.createElement("img");
    img.src = `${API}/${currentDocId}/page/${p}.png`;
    img.alt = `Page ${p}`;
    body.appendChild(img);
  });
  panel.classList.add("open");
}

function closeSourcePanel() {
  document.getElementById("source-panel").classList.remove("open");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("file-input");
  if (!input.files.length) return;
  const btn = document.getElementById("upload-btn");
  btn.disabled = true;
  btn.textContent = "Uploading...";
  try {
    const formData = new FormData();
    formData.append("file", input.files[0]);
    const res = await fetch(`${API}/upload`, { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      alert("Upload failed: " + (err.detail || res.statusText));
      return;
    }
    const data = await res.json();
    input.value = "";
    // extraction continues in the background; the list polls until it's
    // ready and then opens it
    awaitingDocId = data.doc_id;
    switchView("documents");
    await loadDocList(currentDocId);
  } finally {
    btn.disabled = false;
    btn.textContent = "Upload & extract";
  }
});

// --- View switching ---

document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

function switchView(view) {
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  document.getElementById("view-documents").style.display = view === "documents" ? "" : "none";
  document.getElementById("view-compare").style.display = view === "compare" ? "" : "none";
  if (view === "compare" && !currentComparisonId) {
    loadComparisonList();
  }
}

// --- Comparisons ---

async function loadComparisonList(selectId) {
  const comparisons = await fetch(COMPARE_API).then(r => r.json());
  comparisonItemsEl.innerHTML = "";
  if (comparisons.length === 0) {
    comparisonItemsEl.innerHTML = '<div class="comparison-item meta">No comparisons yet.</div>';
    return;
  }
  comparisons.forEach(c => {
    const el = document.createElement("div");
    el.className = "comparison-item" + (c.comparison_id === selectId ? " active" : "");
    el.innerHTML = `
      <div class="name">SBU-${escapeHtml(c.sbu)} · ${escapeHtml(c.target_year)} — ${escapeHtml(c.petition_filename || c.comparison_id)}</div>
      ${c.has_errors
        ? '<div class="meta invalid">Mismatched documents — results not meaningful</div>'
        : `<div class="meta">${c.field_count} fields · ${c.flagged_count} flagged</div>`}
    `;
    el.onclick = () => selectComparison(c.comparison_id);
    comparisonItemsEl.appendChild(el);
  });
}

async function selectComparison(id) {
  currentComparisonId = id;
  currentComparison = await fetch(`${COMPARE_API}/${id}`).then(r => r.json());
  renderComparisonDetail();
  await loadComparisonList(id);
}

document.getElementById("new-comparison-btn").addEventListener("click", async () => {
  currentComparisonId = null;
  currentComparison = null;
  await renderNewComparisonForm();
  await loadComparisonList();
});

const FORM_SLOTS = [
  { id: "cf-tuo", type: "truing_up_order", label: "Previous year's Truing Up Order (schema source)", missing: "No Truing Up Order uploaded yet." },
  { id: "cf-arr", type: "arr", label: "ARR order (approved budget)", missing: "No ARR order uploaded yet." },
  { id: "cf-petition", type: "petition", label: "This year's truing-up petition (claimed values)", missing: "No truing-up petition uploaded yet." },
];

function slotOptions(slot) {
  // Only offer documents detected as the right type; unrecognised ones are
  // still listed (detection can miss an unusual layout) but marked as such.
  const matching = allDocsForForm.filter(d => d.doc_type === slot.type);
  const unknown = allDocsForForm.filter(d => d.doc_type === "unknown");
  return [...matching, ...unknown]
    .map(d => `<option value="${d.doc_id}">${escapeHtml(d.filename || d.doc_id)} — ${escapeHtml(d.label)}</option>`)
    .join("");
}

async function renderNewComparisonForm() {
  allDocsForForm = (await fetch(API).then(r => r.json())).filter(d => d.state === "ready");
  const sbus = await fetch("/api/sbus").then(r => r.json());
  let html = `<div class="new-comparison-form"><div class="section-heading" style="margin-top:0">New comparison</div>
    <label for="cf-sbu">Business unit</label>
    <select id="cf-sbu">${sbus.map(s => `<option value="${s.sbu}" ${s.comparable ? "" : "disabled"}>SBU-${s.sbu} ${s.name}${s.comparable ? "" : " (field mapping not built yet)"}</option>`).join("")}</select>`;
  let anyMissing = false;
  FORM_SLOTS.forEach(slot => {
    const opts = slotOptions(slot);
    html += `<label for="${slot.id}">${slot.label}</label>`;
    if (opts) {
      html += `<select id="${slot.id}">${opts}</select>`;
    } else {
      anyMissing = true;
      html += `<div class="slot-missing">${slot.missing} Upload one in the Documents tab.</div>`;
    }
  });
  html += `
      <label for="cf-year">Target year</label>
      <input type="text" id="cf-year" placeholder="e.g. 2024-25">
      <button id="cf-submit" ${anyMissing ? "disabled" : ""}>Run comparison</button>
      <div id="cf-error" class="form-error"></div>
    </div>`;
  compareContentEl.innerHTML = html;
  if (anyMissing) return;

  const petitionSel = document.getElementById("cf-petition");
  const yearInput = document.getElementById("cf-year");
  const syncYear = () => {
    const p = allDocsForForm.find(d => d.doc_id === petitionSel.value);
    if (p && p.fiscal_year) yearInput.value = p.fiscal_year;
  };
  petitionSel.addEventListener("change", syncYear);
  syncYear();
  document.getElementById("cf-submit").addEventListener("click", submitNewComparison);
}

async function submitNewComparison() {
  const tuo_doc_id = document.getElementById("cf-tuo").value;
  const arr_doc_id = document.getElementById("cf-arr").value;
  const petition_doc_id = document.getElementById("cf-petition").value;
  const target_year = document.getElementById("cf-year").value.trim();
  const sbu = document.getElementById("cf-sbu").value;
  const errEl = document.getElementById("cf-error");
  const btn = document.getElementById("cf-submit");
  if (!target_year) {
    errEl.textContent = "Enter a target year, e.g. 2024-25.";
    return;
  }
  btn.disabled = true;
  btn.textContent = "Running…";
  errEl.textContent = "";
  try {
    const res = await fetch(COMPARE_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tuo_doc_id, arr_doc_id, petition_doc_id, target_year, sbu })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      errEl.textContent = err.detail || res.statusText;
      return;
    }
    const data = await res.json();
    await selectComparison(data.comparison_id);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run comparison";
  }
}

function renderComparisonDetail() {
  const c = currentComparison;
  if (!c) {
    compareContentEl.innerHTML = '<div class="empty-state">Pick a comparison from the left, or create a new one.</div>';
    return;
  }

  const errors = c.input_errors || [];
  const warnings = c.input_warnings || [];
  let html = `
    <div class="compare-banner">
      <button class="secondary delete-comparison" onclick="deleteComparison()">Delete comparison</button>
      <b>SBU-${escapeHtml(c.sbu || "G")} ${SBU_NAMES[c.sbu || "G"]} · FY ${escapeHtml(c.target_year)}</b> &middot;
      Schema: ${escapeHtml(c.tuo_filename || c.tuo_doc_id)} &middot;
      ARR: ${escapeHtml(c.arr_filename || c.arr_doc_id)} &middot;
      Petition: ${escapeHtml(c.petition_filename || c.petition_doc_id)}<br>
      ${c.fields.length} of ${c.schema_field_count} schema fields mapped and compared.
    </div>
    ${errors.length ? `<div class="notice error"><b>These results aren't meaningful</b> — this comparison was created with the wrong documents:<ul>${errors.map(e => `<li>${escapeHtml(e)}</li>`).join("")}</ul>Delete it and create a new one.</div>` : ""}
    ${warnings.length ? `<div class="notice warn"><ul>${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul></div>` : ""}
    <div class="settings-panel">
      <div class="field">
        <label for="set-pct">Flag when deviation ≥</label>
        <input type="number" id="set-pct" value="${c.settings.pct_threshold}" step="0.5"> %
      </div>
      <div class="field">
        <label for="set-abs">AND absolute diff ≥</label>
        <input type="number" id="set-abs" value="${c.settings.abs_threshold}" step="0.1"> ${escapeHtml(c.fields[0] ? (c.fields[0].unit || "") : "")}
      </div>
      <div class="stat">${c.fields.filter(f => f.needs_review || isSignificant(f)).length} field(s) flagged</div>
    </div>
    <table class="compare-grid">
      <thead>
        <tr>
          <th>Field</th>
          <th>ARR Approved</th>
          <th>Petition Claimed</th>
          <th>Deviation</th>
          <th>%</th>
          <th>Flags</th>
          <th>Source</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
  `;

  c.fields.forEach((f, i) => {
    const significant = isSignificant(f);
    const rowClasses = [
      f.note ? "no-budget-line" : "",
      significant ? "significant" : "",
      f.reviewed ? "reviewed-row" : "",
    ].filter(Boolean).join(" ");
    html += `
      <tr class="${rowClasses}" data-index="${i}">
        <td>${escapeHtml(f.field_label)}${f.unit ? ` <span style="color:var(--muted); font-weight:400;">(${escapeHtml(f.unit)})</span>` : ""}</td>
        <td ${f.note ? `title="${escapeHtml(f.note)}"` : 'contenteditable="true" data-field="arr_approved"'}>${f.note ? "—" : escapeHtml(f.arr_approved ?? "")}</td>
        <td ${f.claim_note ? `title="${escapeHtml(f.claim_note)}"` : 'contenteditable="true" data-field="petition_claimed"'}>${f.claim_note ? "—" : escapeHtml(f.petition_claimed ?? "")}</td>
        <td>${f.deviation_abs ?? "—"}</td>
        <td class="dev-pct">${f.deviation_pct != null ? f.deviation_pct + "%" : "—"}</td>
        <td>
          ${f.needs_review ? `<span class="flag review" title="${escapeHtml(f.lookup_problem || "The source table was flagged during extraction, or the value was recovered from a page break - check the source page")}">Needs review</span>` : ""}
          ${f.recovered ? '<span class="flag review" title="Value reconstructed from a page-break recovery, not a normal extraction">Recovered</span>' : ""}
          ${f.new_in_petition ? '<span class="flag review" title="Claimed in this petition but not a line in last year\'s Truing Up Order - check it by hand">New line</span>' : ""}
          ${f.claim_note ? `<span class="flag info" title="${escapeHtml(f.claim_note)}">No separate claim</span>` : ""}
          ${f.note ? `<span class="flag info" title="${escapeHtml(f.note)}">No ARR line</span>` : ""}
        </td>
        <td class="compare-actions">
          ${f.arr_pages && f.arr_pages.length ? `<button class="secondary" onclick="viewComparisonSource(${i}, 'arr')">ARR p.${f.arr_pages.join(",")}</button>` : ""}
          ${f.petition_pages && f.petition_pages.length ? `<button class="secondary" onclick="viewComparisonSource(${i}, 'petition')">Petition p.${f.petition_pages.join(",")}</button>` : ""}
        </td>
        <td class="compare-actions">
          <button class="secondary" onclick="toggleFieldReviewed(${i})">${f.reviewed ? "Unmark" : "Reviewed"}</button>
        </td>
      </tr>
    `;
  });

  html += `</tbody></table>`;
  compareContentEl.innerHTML = html;
  attachCompareListeners();
}

function isSignificant(f) {
  if (f.deviation_pct == null || f.deviation_abs == null) return false;
  const s = currentComparison.settings;
  return Math.abs(f.deviation_pct) >= s.pct_threshold && Math.abs(f.deviation_abs) >= s.abs_threshold;
}

function attachCompareListeners() {
  document.getElementById("set-pct").addEventListener("change", (e) => updateSettings({ pct_threshold: parseFloat(e.target.value) }));
  document.getElementById("set-abs").addEventListener("change", (e) => updateSettings({ abs_threshold: parseFloat(e.target.value) }));

  document.querySelectorAll("table.compare-grid td[contenteditable]").forEach(td => {
    td.addEventListener("blur", () => saveFieldValue(td));
  });
}

async function updateSettings(update) {
  const res = await fetch(`${COMPARE_API}/${currentComparisonId}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update)
  });
  currentComparison.settings = await res.json();
  renderComparisonDetail();
}

async function saveFieldValue(td) {
  const tr = td.closest("tr");
  const index = parseInt(tr.dataset.index, 10);
  const field = td.dataset.field;
  const value = td.textContent.trim();
  const res = await fetch(`${COMPARE_API}/${currentComparisonId}/fields/${index}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [field]: value })
  });
  currentComparison.fields[index] = await res.json();
  renderComparisonDetail();
}

async function deleteComparison() {
  if (!confirm("Delete this comparison? Reviewed flags and edited values in it will be lost.")) return;
  await fetch(`${COMPARE_API}/${currentComparisonId}`, { method: "DELETE" });
  currentComparisonId = null;
  currentComparison = null;
  renderComparisonDetail();
  await loadComparisonList();
}

async function toggleFieldReviewed(index) {
  const reviewed = !currentComparison.fields[index].reviewed;
  const res = await fetch(`${COMPARE_API}/${currentComparisonId}/fields/${index}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewed })
  });
  currentComparison.fields[index] = await res.json();
  renderComparisonDetail();
}

function viewComparisonSource(index, side) {
  const f = currentComparison.fields[index];
  const docId = side === "arr" ? currentComparison.arr_doc_id : currentComparison.petition_doc_id;
  const pages = side === "arr" ? f.arr_pages : f.petition_pages;
  const panel = document.getElementById("source-panel");
  const title = document.getElementById("source-panel-title");
  const body = document.getElementById("source-panel-body");
  title.textContent = `${side === "arr" ? "ARR" : "Petition"} — ${f.field_label} — page(s) ${pages.join(", ")}`;
  body.innerHTML = "";
  pages.forEach(p => {
    const img = document.createElement("img");
    img.src = `${API}/${docId}/page/${p}.png`;
    img.alt = `Page ${p}`;
    body.appendChild(img);
  });
  panel.classList.add("open");
}

loadDocList();
