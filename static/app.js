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
  if (r.status === "done") {
    clearInterval(pollTimer);
    $("#progress-title").textContent = "All done.";
    show("done");
  }
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
