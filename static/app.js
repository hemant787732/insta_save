const socket = io(location.origin, { transports: ["websocket","polling"] });
const form = document.getElementById("dlForm");
const urlInput = document.getElementById("urlInput");
const progressCard = document.getElementById("progressCard");
const statusText = document.getElementById("statusText");
const percentText = document.getElementById("percentText");
const barFill = document.getElementById("barFill");
const speedText = document.getElementById("speedText");
const etaText = document.getElementById("etaText");
const doneRow = document.getElementById("doneRow");
const errorRow = document.getElementById("errorRow");
const dlBtn = document.getElementById("dlBtn");
const downloadLink = document.getElementById("downloadLink");
let currentJob = null;
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;
  resetUI();
  progressCard.hidden = false;
  dlBtn.disabled = true;
  statusText.textContent = "Queued…";
  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({url})
    });
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || "Failed to start download");
    currentJob = json.job_id;
    statusText.textContent = "Starting…";
  } catch (err) {
    showError(err.message || "Request failed");
  }
});
socket.on("progress", (payload) => {
  if (!currentJob || payload.job_id !== currentJob) return;
  const { status, progress, speed, eta, file_path, error } = payload;
  const pct = (progress || "0%").replace(/[^\d.]/g,"");
  percentText.textContent = `${pct}%`;
  barFill.style.width = `${Math.max(Math.min(parseFloat(pct)||0,100),0)}%`;
  statusText.textContent = status === "processing" ? "Processing..." : (status || "...");
  speedText.textContent = speed ? `Speed: ${speed}` : "";
  etaText.textContent = eta ? `ETA: ${eta}` : "";
  if (status === "done" && file_path) {
    downloadLink.href = `/files/${encodeURIComponent(file_path)}`;
    doneRow.hidden = false;
    dlBtn.disabled = false;
  }
  if (status === "error") {
    showError(error || "Unknown error");
  }
});
function resetUI(){
  percentText.textContent = "0%";
  barFill.style.width = "0%";
  speedText.textContent = "";
  etaText.textContent = "";
  doneRow.hidden = true;
  errorRow.hidden = true;
  errorRow.textContent = "";
  dlBtn.disabled = false;
}
function showError(msg){
  errorRow.textContent = `❌ ${msg}`;
  errorRow.hidden = false;
  dlBtn.disabled = false;
}
