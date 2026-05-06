const state = { docId: null, pages: [], redacted: {}, current: 0, fmt: null };

const $ = (id) => document.getElementById(id);

function setStatus(msg, kind = "info") {
  const el = $("uploadStatus");
  el.textContent = msg;
  el.dataset.kind = kind;
}

function showWorkPane(show) {
  $("workPane").hidden = !show;
  $("uploadPane").hidden = show;
}

function renderPage() {
  if (!state.pages.length) return;
  const idx = state.current;
  const page = state.pages[idx];
  $("pageLabel").textContent = `page ${idx + 1} / ${state.pages.length}`;
  $("originalText").textContent = page.text;
  const r = state.redacted[idx];
  $("redactedText").textContent = r ? r.redacted : "— not redacted yet —";
  $("downloadBtn").disabled = Object.keys(state.redacted).length === 0;
}

async function uploadFile(file) {
  if (!/\.(docx|pdf)$/i.test(file.name)) {
    setStatus("Only .docx or .pdf supported.", "error");
    return;
  }
  setStatus(`Uploading ${file.name}…`);
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch("/api/upload", { method: "POST", body: fd });
  if (!resp.ok) {
    setStatus(`Upload failed: ${(await resp.json()).detail || resp.status}`, "error");
    return;
  }
  const meta = await resp.json();
  state.docId = meta.docId;
  state.fmt = meta.fmt;
  const listing = await (await fetch(`/api/documents/${meta.docId}`)).json();
  state.pages = listing.pages;
  state.redacted = {};
  state.current = 0;
  $("docInfo").textContent = `${meta.filename} · ${meta.pageCount} page(s)`;
  showWorkPane(true);
  renderPage();
}

async function redactCurrent() {
  if (state.docId == null) return;
  const method = $("methodSelect").value;
  const resp = await fetch("/api/redact/page", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ docId: state.docId, pageIndex: state.current, method }),
  });
  if (!resp.ok) {
    alert(`Redaction failed: ${(await resp.json()).detail || resp.status}`);
    return;
  }
  const { page } = await resp.json();
  state.redacted[page.index] = page;
  renderPage();
}

async function redactBatch() {
  if (state.docId == null) return;
  const method = $("methodSelect").value;
  const resp = await fetch("/api/redact/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ docId: state.docId, method }),
  });
  if (!resp.ok) {
    alert(`Batch redaction failed: ${(await resp.json()).detail || resp.status}`);
    return;
  }
  const { pages } = await resp.json();
  pages.forEach((p) => (state.redacted[p.index] = p));
  renderPage();
}

async function reset() {
  if (state.docId) {
    await fetch(`/api/documents/${state.docId}`, { method: "DELETE" });
  }
  state.docId = null;
  state.pages = [];
  state.redacted = {};
  state.current = 0;
  state.fmt = null;
  $("docInfo").textContent = "";
  $("fileInput").value = "";
  setStatus("");
  showWorkPane(false);
}

function bind() {
  $("fileInput").addEventListener("change", (e) => {
    const f = e.target.files?.[0];
    if (f) uploadFile(f);
  });
  const dz = document.querySelector(".drop-zone");
  dz.addEventListener("dragover", (e) => {
    e.preventDefault();
    dz.classList.add("hover");
  });
  dz.addEventListener("dragleave", () => dz.classList.remove("hover"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("hover");
    const f = e.dataTransfer.files?.[0];
    if (f) uploadFile(f);
  });
  $("prevPage").addEventListener("click", () => {
    if (state.current > 0) {
      state.current--;
      renderPage();
    }
  });
  $("nextPage").addEventListener("click", () => {
    if (state.current < state.pages.length - 1) {
      state.current++;
      renderPage();
    }
  });
  $("redactPageBtn").addEventListener("click", redactCurrent);
  $("redactBatchBtn").addEventListener("click", redactBatch);
  $("downloadBtn").addEventListener("click", () => {
    if (state.docId) window.location.href = `/api/download/${state.docId}`;
  });
  $("resetBtn").addEventListener("click", reset);
}

bind();
