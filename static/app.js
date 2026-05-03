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
    // auto-trigger the download so Yashvardhan doesn't have to click
    window.location.href = "/download/" + jobId;
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
  show("upload");
});
