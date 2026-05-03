const $ = (s) => document.querySelector(s);
const drop = $("#drop");
const fileIn = $("#file");
const fileInfo = $("#file-info");

let pickedFile = null;
let jobId = null;
let pollTimer = null;

function show(id) { $("#step-" + id).classList.remove("hidden"); }
function hide(id) { $("#step-" + id).classList.add("hidden"); }

drop.addEventListener("click", () => fileIn.click());
["dragenter","dragover"].forEach(ev =>
  drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("hover"); }));
["dragleave","drop"].forEach(ev =>
  drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("hover"); }));
drop.addEventListener("drop", e => {
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileIn.addEventListener("change", e => {
  if (e.target.files.length) handleFile(e.target.files[0]);
});

async function handleFile(file) {
  pickedFile = file;
  fileInfo.hidden = false;
  fileInfo.textContent = `Loaded ${file.name} (${(file.size/1024).toFixed(1)} KB)`;

  const fd = new FormData();
  fd.append("file", file);
  let r;
  try {
    const res = await fetch("/columns", { method: "POST", body: fd });
    r = await res.json();
  } catch (e) {
    fileInfo.textContent = "Couldn't read that file. Make sure it's a valid CSV.";
    return;
  }
  if (r.error) { fileInfo.textContent = "Error: " + r.error; return; }

  fileInfo.textContent = `${file.name}, ${r.rows} rows`;
  const sel = $("#link-col");
  sel.innerHTML = "";
  r.columns.forEach(c => {
    const o = document.createElement("option");
    o.value = c; o.textContent = c;
    if (c === r.guess) o.selected = true;
    sel.appendChild(o);
  });
  $("#column-guess").textContent = r.guess
    ? `Auto-detected: "${r.guess}". Change it if that's wrong.`
    : "Couldn't auto-detect a link column. Pick the right one.";
  show("column");
}

$("#start-btn").addEventListener("click", async () => {
  if (!pickedFile) return;
  const fd = new FormData();
  fd.append("file", pickedFile);
  fd.append("link_col", $("#link-col").value);
  $("#start-btn").disabled = true;

  const res = await fetch("/upload", { method: "POST", body: fd });
  const r = await res.json();
  $("#start-btn").disabled = false;
  if (r.error) { alert("Error: " + r.error); return; }

  jobId = r.job_id;
  hide("upload"); hide("column");
  show("progress");
  $("#progress-title").textContent = `Working on ${r.total} videos...`;
  pollTimer = setInterval(poll, 700);
});

async function poll() {
  if (!jobId) return;
  const r = await fetch("/status/" + jobId).then(r => r.json());
  const pct = r.total ? (r.done / r.total) * 100 : 0;
  $("#bar-fill").style.width = pct.toFixed(1) + "%";
  $("#bar-meta").textContent = `${r.done} / ${r.total} processed`;
  $("#log").textContent = r.log.join("\n");

  // live stats: smooth counter animations
  animateCounter("#words-counter", r.words_total || 0);
  animateCounter("#hours-counter", ((r.words_total || 0) / 150 / 60), 1);
  animateCounter("#videos-counter", r.done || 0);

  // snippet rotation
  if (r.snippets && r.snippets.length) {
    latestSnippets = r.snippets;
    if (!quoteRotateTimer) {
      showQuote(latestSnippets[latestSnippets.length - 1]);
      quoteIdx = latestSnippets.length - 1;
      quoteRotateTimer = setInterval(rotateQuote, 9000);
    }
  }

  if (r.status === "done") {
    clearInterval(pollTimer);
    if (quoteRotateTimer) { clearInterval(quoteRotateTimer); quoteRotateTimer = null; }
    $("#progress-title").textContent = "All done.";
    show("done");
  }
}

// ---------- live counter + quote card ----------

let latestSnippets = [];
let quoteIdx = -1;
let quoteRotateTimer = null;
const counterState = {};  // selector -> {current, target, raf}

function animateCounter(selector, target, decimals = 0) {
  const el = document.querySelector(selector);
  if (!el) return;
  const state = counterState[selector] || { current: 0, raf: null };
  if (state.target === target) return;
  state.target = target;
  if (state.raf) cancelAnimationFrame(state.raf);
  const start = performance.now();
  const duration = 700;
  const from = state.current;
  function step(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const value = from + (target - from) * eased;
    state.current = value;
    el.textContent = decimals
      ? value.toFixed(decimals)
      : Math.round(value).toLocaleString();
    if (t < 1) state.raf = requestAnimationFrame(step);
    else state.raf = null;
  }
  state.raf = requestAnimationFrame(step);
  counterState[selector] = state;
}

function rotateQuote() {
  if (!latestSnippets.length) return;
  quoteIdx = (quoteIdx + 1) % latestSnippets.length;
  showQuote(latestSnippets[quoteIdx]);
}

function showQuote(s) {
  const card = $("#quote-card");
  card.classList.add("fading");
  setTimeout(() => {
    $("#quote-text").textContent = s.quote;
    const channel = escapeHtml(s.channel || "Unknown");
    const title = escapeHtml(s.title || "");
    $("#quote-attr").innerHTML = title
      ? `<strong>${channel}</strong> &middot; <em>${title}</em>`
      : `<strong>${channel}</strong>`;
    card.classList.remove("fading");
  }, 450);
}

$("#download-btn").addEventListener("click", () => {
  window.location.href = "/download/" + jobId;
});

$("#restart-btn").addEventListener("click", () => {
  pickedFile = null; jobId = null;
  fileIn.value = "";
  fileInfo.hidden = true;
  $("#bar-fill").style.width = "0%";
  $("#log").textContent = "";
  // reset wait-page state so the next run starts fresh
  latestSnippets = []; quoteIdx = -1;
  if (quoteRotateTimer) { clearInterval(quoteRotateTimer); quoteRotateTimer = null; }
  for (const k of Object.keys(counterState)) { delete counterState[k]; }
  ["#words-counter", "#videos-counter"].forEach(s => { const el = document.querySelector(s); if (el) el.textContent = "0"; });
  const h = document.querySelector("#hours-counter"); if (h) h.textContent = "0.0";
  $("#quote-text").textContent = "Warming up...";
  $("#quote-attr").textContent = "First quote will appear when the first transcript finishes.";
  hide("progress"); hide("done"); hide("column");
  // restore whichever tab is active
  document.querySelectorAll(".tabpane").forEach(p => p.classList.add("hidden"));
  const active = document.querySelector(".tab.active").dataset.tab;
  document.querySelector(`.tabpane[data-tab="${active}"]`).classList.remove("hidden");
});

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const which = btn.dataset.tab;
    document.querySelectorAll(".tabpane").forEach(p => {
      p.classList.toggle("hidden", p.dataset.tab !== which);
    });
  });
});

// ---------- channel browser ----------
let loadedVideos = [];
const selectedIds = new Set();

$("#load-channel-btn").addEventListener("click", async () => {
  const url = $("#channel-url").value.trim();
  const limit = parseInt($("#channel-limit").value, 10) || 50;
  if (!url) return;
  const statusEl = $("#channel-status");
  $("#load-channel-btn").disabled = true;
  statusEl.textContent = "Loading channel... this can take 5-30 seconds for big channels.";
  $("#channel-results").classList.add("hidden");

  try {
    const res = await fetch("/channel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, limit }),
    });
    const r = await res.json();
    $("#load-channel-btn").disabled = false;
    if (r.error) { statusEl.textContent = "Error: " + r.error; return; }
    loadedVideos = r.videos;
    selectedIds.clear();
    statusEl.textContent = `Loaded ${r.count} videos from ${r.channel_title || "channel"}.`;
    renderGrid(loadedVideos);
    $("#channel-results").classList.remove("hidden");
    updateSelectionCount();
  } catch (e) {
    $("#load-channel-btn").disabled = false;
    statusEl.textContent = "Network error: " + e.message;
  }
});

function renderGrid(videos) {
  const grid = $("#video-grid");
  grid.innerHTML = "";
  videos.forEach(v => {
    const card = document.createElement("div");
    card.className = "vcard" + (selectedIds.has(v.video_id) ? " selected" : "");
    card.dataset.vid = v.video_id;
    card.innerHTML = `
      <div class="thumb" style="background-image:url('${v.thumbnail}')">
        ${v.duration ? `<div class="duration">${v.duration}</div>` : ""}
        <div class="check">✓</div>
      </div>
      <div class="meta">
        <div class="vtitle">${escapeHtml(v.title)}</div>
        <div class="vviews">${v.views || ""}</div>
      </div>`;
    card.addEventListener("click", () => toggle(v.video_id, card));
    grid.appendChild(card);
  });
}

function toggle(vid, card) {
  if (selectedIds.has(vid)) { selectedIds.delete(vid); card.classList.remove("selected"); }
  else { selectedIds.add(vid); card.classList.add("selected"); }
  updateSelectionCount();
}

function updateSelectionCount() {
  $("#selection-count").textContent = `${selectedIds.size} selected`;
  $("#run-selection-btn").disabled = selectedIds.size === 0;
}

$("#filter-input").addEventListener("input", e => {
  const q = e.target.value.toLowerCase();
  const filtered = q ? loadedVideos.filter(v => v.title.toLowerCase().includes(q)) : loadedVideos;
  renderGrid(filtered);
});

$("#select-all-btn").addEventListener("click", () => {
  document.querySelectorAll(".vcard").forEach(c => {
    selectedIds.add(c.dataset.vid);
    c.classList.add("selected");
  });
  updateSelectionCount();
});
$("#clear-all-btn").addEventListener("click", () => {
  selectedIds.clear();
  document.querySelectorAll(".vcard.selected").forEach(c => c.classList.remove("selected"));
  updateSelectionCount();
});

$("#run-selection-btn").addEventListener("click", async () => {
  const ids = [...selectedIds];
  if (!ids.length) return;
  $("#run-selection-btn").disabled = true;
  const res = await fetch("/start_from_ids", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_ids: ids }),
  });
  const r = await res.json();
  $("#run-selection-btn").disabled = false;
  if (r.error) { alert("Error: " + r.error); return; }
  jobId = r.job_id;
  document.querySelectorAll(".tabpane").forEach(p => p.classList.add("hidden"));
  show("progress");
  $("#progress-title").textContent = `Working on ${r.total} videos...`;
  pollTimer = setInterval(poll, 700);
});

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
