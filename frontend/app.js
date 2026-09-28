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

async function loadDocList(selectId) {
  const docs = await fetch(API).then(r => r.json());
  docItemsEl.innerHTML = "";
  if (docs.length === 0) {
    docItemsEl.innerHTML = '<div class="doc-item meta">No documents uploaded yet.</div>';
    return;
  }
  docs.forEach(d => {
    const el = document.createElement("div");
    el.className = "doc-item" + (d.doc_id === selectId ? " active" : "");
    el.innerHTML = `
      <div class="name">${escapeHtml(d.filename || d.doc_id)}</div>
      <div class="meta">${d.order_table_count} tables · ${d.needs_review_count} flagged</div>
    `;
    el.onclick = () => selectDocument(d.doc_id);
    docItemsEl.appendChild(el);
  });
}

async function selectDocument(docId) {
  currentDocId = docId;
  const data = await fetch(`${API}/${docId}`).then(r => r.json());
  currentDoc = data;
  renderDocument();
  await loadDocList(docId);
}

function renderDocument() {
  if (!currentDoc) {
    contentEl.innerHTML = '<div class="empty-state">Select a document.</div>';
    return;
  }
  const d = currentDoc;
  let html = `
    <div class="chapter-banner">
      <b>${escapeHtml(d.chapter_heading || "")}</b><br>
      Source pages ${d.pages ? d.pages[0] + "–" + d.pages[1] : "?"} &middot; ${d.order_tables.length} order tables
      &middot; ${d.reference_tables.length} reference tables excluded
      &middot; ${d.unclassified_fragments.length} unclassified fragments
    </div>
  `;

  html += `<div class="section-heading">Order tables (SBU-G financial claims)</div>`;
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
  await fetch(`${API}/${currentDocId}/${bucket}/${index}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data_rows: rows })
  });
  // keep the in-memory model in sync so a later re-render (e.g. toggling
  // "reviewed" on another table) doesn't wipe this edit back to its
  // pre-edit value.
  currentDoc[bucket][index].data_rows = rows;
}

async function toggleReviewed(bucket, index) {
  const t = currentDoc[bucket][index];
  const reviewed = !t.reviewed;
  await fetch(`${API}/${currentDocId}/${bucket}/${index}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewed })
  });
  t.reviewed = reviewed;
  renderDocument();
}

function viewSourcePages(bucket, index) {
  const t = currentDoc[bucket][index];
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
  btn.textContent = "Extracting...";
  try {
    const formData = new FormData();
    formData.append("file", input.files[0]);
    const res = await fetch(`${API}/upload`, { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      alert("Extraction failed: " + (err.detail || res.statusText));
      return;
    }
    const data = await res.json();
    input.value = "";
    await selectDocument(data.doc_id);
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
      <div class="name">${escapeHtml(c.target_year)} — ${escapeHtml(c.petition_filename || c.comparison_id)}</div>
      <div class="meta">${c.field_count} fields · ${c.flagged_count} flagged</div>
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

async function renderNewComparisonForm() {
  allDocsForForm = await fetch(API).then(r => r.json());
  const opts = allDocsForForm.map(d => `<option value="${d.doc_id}">${escapeHtml(d.filename || d.doc_id)}</option>`).join("");
  compareContentEl.innerHTML = `
    <div class="new-comparison-form">
      <div class="section-heading" style="margin-top:0">New comparison</div>
      <label>Truing Up Order (schema source)</label>
      <select id="cf-tuo">${opts}</select>
      <label>ARR (approved budget source)</label>
      <select id="cf-arr">${opts}</select>
      <label>Petition (claimed values source)</label>
      <select id="cf-petition">${opts}</select>
      <label>Target year</label>
      <input type="text" id="cf-year" placeholder="e.g. 2024-25">
      <button id="cf-submit">Run comparison</button>
      <div id="cf-error" style="color:#b42318; font-size:12.5px; margin-top:10px;"></div>
    </div>
  `;
  if (allDocsForForm.length === 0) {
    compareContentEl.innerHTML = '<div class="empty-state">Upload at least one document (a Truing Up Order, an ARR, and a Petition) in the Documents tab first.</div>';
    return;
  }
  document.getElementById("cf-submit").addEventListener("click", submitNewComparison);
}

async function submitNewComparison() {
  const tuo_doc_id = document.getElementById("cf-tuo").value;
  const arr_doc_id = document.getElementById("cf-arr").value;
  const petition_doc_id = document.getElementById("cf-petition").value;
  const target_year = document.getElementById("cf-year").value.trim();
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
      body: JSON.stringify({ tuo_doc_id, arr_doc_id, petition_doc_id, target_year })
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

  let html = `
    <div class="compare-banner">
      <b>FY ${escapeHtml(c.target_year)}</b> &middot;
      Schema: ${escapeHtml(c.tuo_filename || c.tuo_doc_id)} &middot;
      ARR: ${escapeHtml(c.arr_filename || c.arr_doc_id)} &middot;
      Petition: ${escapeHtml(c.petition_filename || c.petition_doc_id)}<br>
      ${c.fields.length} of ${c.schema_field_count} schema fields mapped and compared.
    </div>
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
        <td contenteditable="true" data-field="petition_claimed">${escapeHtml(f.petition_claimed ?? "")}</td>
        <td>${f.deviation_abs ?? "—"}</td>
        <td class="dev-pct">${f.deviation_pct != null ? f.deviation_pct + "%" : "—"}</td>
        <td>
          ${f.needs_review ? '<span class="flag review">Needs review</span>' : ""}
          ${f.recovered ? '<span class="flag review" title="Value reconstructed from a page-break recovery, not a normal extraction">Recovered</span>' : ""}
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
