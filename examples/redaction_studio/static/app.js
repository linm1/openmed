const NONE_PATTERN_SENTINEL = "__none__";

const state = {
  docId: null,
  pages: [],
  redacted: {},
  current: 0,
  fmt: null,
  canonical: {},
  customTerms: [],
  availablePatterns: [],
  confidence: 0.85,
  enabledPatternIds: [],
  patternSelectionExplicit: false,
};

const $ = (id) => document.getElementById(id);

function setStatus(msg, kind = "info") {
  const el = $("uploadStatus");
  el.textContent = msg;
  el.dataset.kind = msg ? kind : "";
}

function showWorkPane(show) {
  $("workPane").hidden = !show;
  $("uploadPane").hidden = show;
}

async function readErrorDetail(resp) {
  try {
    const body = await resp.json();
    return body.detail || resp.status;
  } catch {
    return resp.status;
  }
}

function describeRequestError(error) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "network error";
}

function defaultEnabledPatternIds() {
  return state.availablePatterns
    .filter((pattern) => pattern.enabled_by_default)
    .map((pattern) => pattern.id);
}

function resolveEnabledPatternIds(patternIds) {
  if (!Array.isArray(patternIds) || patternIds.length === 0) {
    return defaultEnabledPatternIds();
  }
  if (patternIds.includes(NONE_PATTERN_SENTINEL)) {
    return [];
  }
  return patternIds;
}

function serializeEnabledPatternIds(patternIds) {
  return patternIds.length > 0 ? patternIds : [NONE_PATTERN_SENTINEL];
}

function applyContext(context = {}) {
  state.customTerms = Array.isArray(context.customTerms) ? [...context.customTerms] : [];
  state.confidence = typeof context.confidenceThreshold === "number"
    ? context.confidenceThreshold
    : 0.85;

  const rawPatternIds = Array.isArray(context.enabledPatternIds)
    ? context.enabledPatternIds
    : [];
  state.patternSelectionExplicit = rawPatternIds.length > 0;
  state.enabledPatternIds = resolveEnabledPatternIds(rawPatternIds);
}

function setCanonicalSummary(canonical) {
  state.canonical = canonical && typeof canonical === "object" ? canonical : {};
}

function appendPlaceholderChip(container, text) {
  const chip = document.createElement("div");
  chip.className = "chip chip-placeholder";

  const label = document.createElement("span");
  label.className = "chip-label";
  label.textContent = text;

  chip.append(label);
  container.append(chip);
}

function renderPage() {
  if (!state.pages.length) {
    $("pageLabel").textContent = "page 0 / 0";
    $("originalText").textContent = "";
    $("redactedText").textContent = "";
    $("prevPage").disabled = true;
    $("nextPage").disabled = true;
    $("downloadBtn").disabled = true;
    return;
  }

  const idx = state.current;
  const page = state.pages[idx];
  $("pageLabel").textContent = `page ${idx + 1} / ${state.pages.length}`;
  $("originalText").textContent = page.text;

  const redactedPage = state.redacted[idx];
  $("redactedText").textContent = redactedPage ? redactedPage.redacted : "-- not redacted yet --";
  $("prevPage").disabled = idx === 0;
  $("nextPage").disabled = idx >= state.pages.length - 1;
  $("downloadBtn").disabled = Object.keys(state.redacted).length === 0;
}

function renderSidebar() {
  renderCanonical();
  renderCustomTerms();
  renderPatternList();
  renderConfidence();
}

function renderCanonical() {
  const container = $("canonical-chips");
  container.replaceChildren();

  const entries = Object.entries(state.canonical).sort((left, right) => {
    const leftCount = Number(left[1]?.occurrences || 0);
    const rightCount = Number(right[1]?.occurrences || 0);
    if (leftCount !== rightCount) {
      return rightCount - leftCount;
    }
    return left[0].localeCompare(right[0]);
  });

  if (entries.length === 0) {
    appendPlaceholderChip(container, "No canonical terms yet");
    return;
  }

  entries.forEach(([surface, detail]) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.title = detail.label || "canonical entity";

    const label = document.createElement("span");
    label.className = "chip-label";

    const token = typeof detail.token === "string" && detail.token ? `${detail.token} ` : "";
    const occurrences = Number(detail.occurrences || 0);
    const suffix = occurrences > 1 ? ` (${occurrences}x)` : "";
    label.textContent = `${token}${surface}${suffix}`;

    chip.append(label);
    container.append(chip);
  });
}

function renderCustomTerms() {
  const container = $("custom-term-chips");
  container.replaceChildren();

  if (state.customTerms.length === 0) {
    appendPlaceholderChip(container, "No custom terms added");
    return;
  }

  state.customTerms.forEach((term) => {
    const chip = document.createElement("div");
    chip.className = "chip removable";

    const label = document.createElement("span");
    label.className = "chip-label";
    label.textContent = term;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chip-remove";
    remove.dataset.term = term;
    remove.setAttribute("aria-label", `Remove ${term}`);
    remove.textContent = "x";

    chip.append(label, remove);
    container.append(chip);
  });
}

function renderPatternList() {
  const list = $("pattern-list");
  list.replaceChildren();

  if (state.availablePatterns.length === 0) {
    const item = document.createElement("li");
    item.className = "pattern-row";

    const label = document.createElement("label");
    const title = document.createElement("span");
    title.className = "pattern-label";
    title.textContent = "Pattern catalog unavailable";

    const preview = document.createElement("span");
    preview.className = "pattern-regex";
    preview.textContent = "The pattern list will appear here after the catalog loads.";

    label.append(title, preview);
    item.append(document.createElement("span"), label);
    list.append(item);
    return;
  }

  const selectedIds = new Set(state.enabledPatternIds);
  state.availablePatterns.forEach((pattern) => {
    const item = document.createElement("li");
    item.className = "pattern-row";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = `pattern-toggle-${pattern.id}`;
    checkbox.dataset.patternId = pattern.id;
    checkbox.checked = selectedIds.has(pattern.id);
    checkbox.setAttribute("aria-label", pattern.label);

    const label = document.createElement("label");
    label.htmlFor = checkbox.id;

    const title = document.createElement("span");
    title.className = "pattern-label";
    title.textContent = pattern.label;

    const preview = document.createElement("span");
    preview.className = "pattern-regex";
    preview.textContent = pattern.regex_preview;

    label.append(title, preview);
    item.append(checkbox, label);
    list.append(item);
  });
}

function renderConfidence() {
  const slider = $("confidence-slider");
  const value = Math.min(1, Math.max(0, Number(state.confidence) || 0.85));
  slider.value = value.toFixed(2);
  $("confidence-value").textContent = value.toFixed(2);
}

async function patchContext(partial = {}) {
  if (!state.docId) {
    return false;
  }

  const payload = {
    customTerms: partial.customTerms ?? state.customTerms,
    confidenceThreshold: partial.confidenceThreshold ?? state.confidence,
    enabledPatternIds: serializeEnabledPatternIds(
      partial.enabledPatternIds ?? state.enabledPatternIds,
    ),
  };

  try {
    const resp = await fetch(`/api/documents/${state.docId}/context`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      alert(`Context update failed: ${await readErrorDetail(resp)}`);
      return false;
    }

    const { context } = await resp.json();
    applyContext(context);
    state.redacted = {};
    setCanonicalSummary({});
    renderPage();
    renderSidebar();
    return true;
  } catch (error) {
    console.error(error);
    alert(`Context update failed: ${describeRequestError(error)}`);
    return false;
  }
}

async function addCustomTerm() {
  const input = $("custom-term-input");
  const term = input.value.trim();
  if (!term) {
    return;
  }

  const exists = state.customTerms.some(
    (current) => current.toLowerCase() === term.toLowerCase(),
  );
  if (exists) {
    input.value = "";
    return;
  }

  const nextTerms = [...state.customTerms, term];
  if (await patchContext({ customTerms: nextTerms })) {
    input.value = "";
  }
}

async function removeCustomTerm(term) {
  const nextTerms = state.customTerms.filter((current) => current !== term);
  await patchContext({ customTerms: nextTerms });
}

async function togglePattern(patternId) {
  const selectedIds = new Set(state.enabledPatternIds);
  if (selectedIds.has(patternId)) {
    selectedIds.delete(patternId);
  } else {
    selectedIds.add(patternId);
  }

  const nextPatternIds = state.availablePatterns
    .map((pattern) => pattern.id)
    .filter((id) => selectedIds.has(id));

  await patchContext({ enabledPatternIds: nextPatternIds });
}

async function changeConfidence() {
  const slider = $("confidence-slider");
  const nextValue = Number(slider.value);
  if (!Number.isFinite(nextValue)) {
    return;
  }

  const previous = state.confidence;
  state.confidence = nextValue;
  renderConfidence();

  if (!(await patchContext({ confidenceThreshold: nextValue }))) {
    state.confidence = previous;
    renderConfidence();
  }
}

async function loadPatterns() {
  try {
    const resp = await fetch("/api/patterns");
    if (!resp.ok) {
      throw new Error(`Pattern load failed: ${await readErrorDetail(resp)}`);
    }

    const patterns = await resp.json();
    state.availablePatterns = Array.isArray(patterns) ? patterns : [];

    if (!state.patternSelectionExplicit) {
      state.enabledPatternIds = defaultEnabledPatternIds();
    }

    renderSidebar();
  } catch (error) {
    console.error(error);
    state.availablePatterns = [];
    renderSidebar();
  }
}

async function redactCurrent() {
  if (state.docId == null) {
    return;
  }

  try {
    const resp = await fetch(`/api/documents/${state.docId}/redact-page`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page: state.current }),
    });

    if (!resp.ok) {
      alert(`Redaction failed: ${await readErrorDetail(resp)}`);
      return;
    }

    const data = await resp.json();
    state.redacted[data.pageNumber] = {
      index: data.pageNumber,
      original: state.pages[state.current]?.text || "",
      redacted: data.redactedText,
      entities: [],
    };
    setCanonicalSummary(data.canonical);
    renderPage();
    renderSidebar();
  } catch (error) {
    console.error(error);
    alert(`Redaction failed: ${describeRequestError(error)}`);
  }
}

async function redactBatch() {
  if (state.docId == null) {
    return;
  }

  try {
    const resp = await fetch("/api/redact/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ docId: state.docId }),
    });

    if (!resp.ok) {
      alert(`Batch redaction failed: ${await readErrorDetail(resp)}`);
      return;
    }

    const data = await resp.json();
    data.pages.forEach((page) => {
      state.redacted[page.index] = page;
    });

    setCanonicalSummary(data.canonical);
    renderPage();
    renderSidebar();
  } catch (error) {
    console.error(error);
    alert(`Batch redaction failed: ${describeRequestError(error)}`);
  }
}

async function uploadFile(file) {
  if (!/\.(docx|pdf)$/i.test(file.name)) {
    setStatus("Only .docx or .pdf supported.", "error");
    return;
  }

  setStatus(`Uploading ${file.name}...`);

  const fd = new FormData();
  fd.append("file", file);

  try {
    const uploadResp = await fetch("/api/upload", { method: "POST", body: fd });
    if (!uploadResp.ok) {
      setStatus(`Upload failed: ${await readErrorDetail(uploadResp)}`, "error");
      return;
    }

    const meta = await uploadResp.json();
    const listingResp = await fetch(`/api/documents/${meta.docId}`);
    if (!listingResp.ok) {
      setStatus(`Listing failed: ${await readErrorDetail(listingResp)}`, "error");
      return;
    }

    const listing = await listingResp.json();
    state.docId = meta.docId;
    state.fmt = meta.fmt;
    state.pages = Array.isArray(listing.pages) ? listing.pages : [];
    state.redacted = {};
    state.current = 0;
    setCanonicalSummary({});
    applyContext(listing.context);

    $("docInfo").textContent = `${meta.filename} - ${meta.pageCount} page(s)`;
    setStatus("", "info");
    showWorkPane(true);
    renderPage();
    renderSidebar();
  } catch (error) {
    console.error(error);
    setStatus(`Upload failed: ${describeRequestError(error)}`, "error");
  }
}

async function reset() {
  if (state.docId) {
    try {
      await fetch(`/api/documents/${state.docId}`, { method: "DELETE" });
    } catch (error) {
      console.error(error);
    }
  }

  state.docId = null;
  state.pages = [];
  state.redacted = {};
  state.current = 0;
  state.fmt = null;
  setCanonicalSummary({});
  state.customTerms = [];
  state.confidence = 0.85;
  state.patternSelectionExplicit = false;
  state.enabledPatternIds = defaultEnabledPatternIds();

  $("docInfo").textContent = "";
  $("fileInput").value = "";
  $("custom-term-input").value = "";
  setStatus("");
  renderPage();
  renderSidebar();
  showWorkPane(false);
}

function bind() {
  $("fileInput").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) {
      uploadFile(file);
    }
  });

  const dropZone = document.querySelector(".drop-zone");
  dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("hover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("hover"));
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("hover");
    const file = event.dataTransfer.files?.[0];
    if (file) {
      uploadFile(file);
    }
  });

  $("prevPage").addEventListener("click", () => {
    if (state.current > 0) {
      state.current -= 1;
      renderPage();
    }
  });
  $("nextPage").addEventListener("click", () => {
    if (state.current < state.pages.length - 1) {
      state.current += 1;
      renderPage();
    }
  });

  $("redactPageBtn").addEventListener("click", redactCurrent);
  $("redactBatchBtn").addEventListener("click", redactBatch);
  $("downloadBtn").addEventListener("click", () => {
    if (state.docId) {
      window.location.href = `/api/download/${state.docId}`;
    }
  });
  $("resetBtn").addEventListener("click", reset);

  $("add-term-btn").addEventListener("click", addCustomTerm);
  $("custom-term-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addCustomTerm();
    }
  });

  $("custom-term-chips").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-term]");
    if (button) {
      removeCustomTerm(button.dataset.term);
    }
  });

  $("pattern-list").addEventListener("change", (event) => {
    const checkbox = event.target.closest("input[data-pattern-id]");
    if (checkbox) {
      togglePattern(checkbox.dataset.patternId);
    }
  });

  $("confidence-slider").addEventListener("input", (event) => {
    state.confidence = Number(event.target.value);
    renderConfidence();
  });
  $("confidence-slider").addEventListener("change", changeConfidence);
}

bind();
renderSidebar();
loadPatterns();
