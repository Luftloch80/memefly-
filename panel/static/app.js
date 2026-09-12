const form = document.getElementById("env-form");
const saveStatus = document.getElementById("save-status");
const jobLog = document.getElementById("job-log");
const containerStatus = document.getElementById("container-status");

const btnBuild = document.getElementById("btn-build");
const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");

let activeJob = null; // "build" | "start" | "stop" | null
let pollTimer = null;

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  saveStatus.textContent = "saving…";
  try {
    const resp = await fetch("/api/env", { method: "POST", body: new FormData(form) });
    if (!resp.ok) throw new Error(await resp.text());
    saveStatus.textContent = "saved ✓";
    setTimeout(() => (saveStatus.textContent = ""), 3000);
  } catch (err) {
    saveStatus.textContent = "save failed";
  }
});

function setButtonsDisabled(disabled) {
  btnBuild.disabled = disabled;
  btnStart.disabled = disabled;
  btnStop.disabled = disabled;
}

async function startJob(name, url) {
  if (activeJob) return;
  const resp = await fetch(url, { method: "POST" });
  const data = await resp.json();
  if (!data.started) {
    jobLog.textContent = `${name}: already running or could not start`;
    return;
  }
  activeJob = name;
  setButtonsDisabled(true);
  jobLog.textContent = `${name}: starting…`;
  pollJob(name);
}

function pollJob(name) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/${name}/status`);
      const data = await resp.json();
      jobLog.textContent = data.logs.join("\n") || "(no output yet)";
      jobLog.scrollTop = jobLog.scrollHeight;
      if (data.status === "success" || data.status === "failed") {
        clearInterval(pollTimer);
        activeJob = null;
        setButtonsDisabled(false);
        refreshContainerStatus();
      }
    } catch (e) {
      // transient fetch error, keep polling
    }
  }, 1200);
}

btnBuild.addEventListener("click", () => startJob("build", "/api/build"));
btnStart.addEventListener("click", () => startJob("start", "/api/start"));
btnStop.addEventListener("click", () => startJob("stop", "/api/stop"));

async function refreshContainerStatus() {
  try {
    const resp = await fetch("/api/status");
    const data = await resp.json();
    if (data.error) {
      containerStatus.textContent = data.error;
      return;
    }
    if (!data.containers.length) {
      containerStatus.textContent = "no containers running";
      return;
    }
    containerStatus.textContent = data.containers
      .map((c) => `${c.Service || c.Name}: ${c.State || c.Status}`)
      .join("  •  ");
  } catch (e) {
    containerStatus.textContent = "";
  }
}

refreshContainerStatus();
setInterval(refreshContainerStatus, 8000);
