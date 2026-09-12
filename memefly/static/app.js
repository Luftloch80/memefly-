const REFRESH_MS = 5000;

let chart = null;
let lastPriceUnit = "usd";

function fmtSol(n) {
  if (n === null || n === undefined) return "--";
  return `${Number(n).toFixed(4)} SOL`;
}

function fmtUsd(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  return num < 0.01 ? `$${num.toFixed(8)}` : `$${num.toFixed(4)}`;
}

function fmtPrice(n, unit) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if ((unit || lastPriceUnit) === "sol") {
    return `${num < 0.01 ? num.toFixed(10) : num.toFixed(6)} SOL`;
  }
  return fmtUsd(num);
}

function shortSig(sig) {
  if (!sig) return "";
  return `${sig.slice(0, 6)}…${sig.slice(-6)}`;
}

function renderNeuronGrid(elId, spikes) {
  const el = document.getElementById(elId);
  el.innerHTML = "";
  if (!spikes || spikes.length === 0) {
    el.innerHTML = '<div style="color:#8b91a7;font-size:12px;">no data yet</div>';
    return;
  }
  const max = Math.max(...spikes, 1);
  for (const s of spikes) {
    const cell = document.createElement("div");
    cell.className = "neuron-cell";
    const intensity = Math.min(1, s / max);
    if (intensity > 0) {
      const alpha = 0.15 + intensity * 0.85;
      cell.style.background = `rgba(167, 139, 250, ${alpha})`;
      cell.style.boxShadow = intensity > 0.6 ? "0 0 6px rgba(167,139,250,0.8)" : "none";
    }
    el.appendChild(cell);
  }
}

async function fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} -> ${resp.status}`);
  return resp.json();
}

async function refreshBalance() {
  try {
    const data = await fetchJson("/api/balance");
    document.getElementById("balance-value").textContent =
      data.balance_sol !== null ? fmtSol(data.balance_sol) : "--";
    document.getElementById("balance-sub").textContent = data.pubkey
      ? `${data.pubkey.slice(0, 4)}…${data.pubkey.slice(-4)}`
      : data.error || "no wallet configured";
  } catch (e) {
    document.getElementById("balance-sub").textContent = "unavailable";
  }
}

async function refreshState() {
  let state;
  try {
    state = await fetchJson("/api/state");
  } catch (e) {
    return;
  }

  lastPriceUnit = state.price_unit || "usd";

  document.getElementById("thought-text").textContent = state.thought || "Waiting for the first cycle…";
  if (state.timestamp) {
    document.getElementById("thought-updated").textContent = `updated ${new Date(state.timestamp * 1000).toLocaleTimeString()}`;
  }

  const modeBadge = document.getElementById("mode-badge");
  modeBadge.textContent = state.is_live ? "LIVE" : "DRY RUN";
  modeBadge.className = `badge ${state.is_live ? "live" : "dry-run"}`;

  const discoveryBadge = document.getElementById("discovery-badge");
  discoveryBadge.textContent = state.mode === "discovery" ? "AUTONOMOUS DISCOVERY" : "FIXED COIN";
  discoveryBadge.className = `badge ${state.mode === "discovery" ? "dry-run" : ""}`;

  const haltBadge = document.getElementById("halt-badge");
  if (state.halted) {
    haltBadge.textContent = `HALTED: ${state.halt_reason || ""}`;
    haltBadge.className = "badge halted";
  } else {
    haltBadge.className = "badge badge-hidden";
  }

  document.getElementById("position-value").textContent = fmtSol(state.position_sol);
  const heldMint = state.held_mint || (state.mode !== "discovery" ? state.target_token_mint : null);
  document.getElementById("position-sub").textContent = state.entry_price_usd
    ? `entry @ ${fmtPrice(state.entry_price_usd, state.price_unit)}${heldMint ? ` — ${heldMint.slice(0, 4)}…${heldMint.slice(-4)}` : ""}`
    : "no open position";

  const pnl = state.daily_pnl_sol ?? 0;
  const pnlEl = document.getElementById("pnl-value");
  pnlEl.textContent = `${pnl >= 0 ? "+" : ""}${fmtSol(pnl)}`;
  pnlEl.classList.remove("pnl-positive", "pnl-negative");
  pnlEl.classList.add(pnl >= 0 ? "pnl-positive" : "pnl-negative");

  document.getElementById("price-value").textContent = fmtPrice(state.price_usd, state.price_unit);
  document.getElementById("price-sub").textContent = state.target_token_mint
    ? `${state.target_token_mint.slice(0, 4)}…${state.target_token_mint.slice(-4)}`
    : "";

  const candidatesPanel = document.getElementById("candidates-panel");
  const candidates = state.candidates || [];
  if (state.mode === "discovery") {
    candidatesPanel.hidden = false;
    const body = document.getElementById("candidates-body");
    if (!candidates.length) {
      body.innerHTML = '<tr><td colspan="7" class="empty">no candidates cleared the filters yet</td></tr>';
    } else {
      body.innerHTML = candidates
        .map((c) => {
          const actionClass = c.action === "buy" ? "action-buy" : c.action === "sell" ? "action-sell" : "";
          const isHeld = c.mint === state.held_mint;
          return `<tr${isHeld ? ' style="outline:1px solid #a78bfa;"' : ""}>
            <td>${c.mint.slice(0, 4)}…${c.mint.slice(-4)}${isHeld ? " 🪰" : ""}</td>
            <td>${c.symbol || "?"}</td>
            <td class="${actionClass}">${(c.action || "").toUpperCase()}</td>
            <td>${(c.score || 0).toFixed(2)}</td>
            <td>${((c.confidence || 0) * 100).toFixed(0)}%</td>
            <td>${c.trade_count ?? "-"}</td>
            <td>${c.age_seconds ? Math.round(c.age_seconds / 60) + "m" : "-"}</td>
          </tr>`;
        })
        .join("");
    }
  } else {
    candidatesPanel.hidden = true;
  }

  const sig = state.signal || {};
  const sigEl = document.getElementById("signal-value");
  sigEl.textContent = (sig.action || "--").toUpperCase();
  sigEl.className = `card-value ${sig.action || ""}`;
  document.getElementById("signal-sub").textContent = `confidence ${((sig.confidence || 0) * 100).toFixed(0)}%`;

  const circuit = state.circuit || {};
  document.getElementById("circuit-sub").textContent = circuit.dataset
    ? `${circuit.dataset} — ${circuit.num_neurons} neurons (${circuit.num_input_neurons} sensory in, ${circuit.num_output_neurons} decision out)`
    : "waiting for circuit info…";

  renderNeuronGrid("approach-grid", sig.approach_neuron_spikes);
  renderNeuronGrid("avoidance-grid", sig.avoidance_neuron_spikes);
  document.getElementById("approach-total").textContent = `${(sig.approach_spikes || 0).toFixed(0)} spikes`;
  document.getElementById("avoidance-total").textContent = `${(sig.avoidance_spikes || 0).toFixed(0)} spikes`;

  const score = sig.score || 0;
  const clamped = Math.max(-1, Math.min(1, score));
  const fill = document.getElementById("score-fill");
  const pct = Math.abs(clamped) * 50;
  if (clamped >= 0) {
    fill.style.bottom = "50%";
    fill.style.top = `${50 - pct}%`;
  } else {
    fill.style.top = "50%";
    fill.style.bottom = `${50 - pct}%`;
  }
  document.getElementById("score-label").textContent = `score: ${score.toFixed(2)}`;
  document.getElementById("confidence-label").textContent = `confidence: ${((sig.confidence || 0) * 100).toFixed(0)}%`;
}

async function refreshHistory() {
  let rows;
  try {
    rows = await fetchJson("/api/history?limit=300");
  } catch (e) {
    return;
  }
  if (!rows.length) return;

  const labels = rows.map((r) => new Date(Number(r.timestamp) * 1000).toLocaleTimeString());
  const prices = rows.map((r) => Number(r.price_usd));
  const pnls = rows.map((r) => Number(r.daily_pnl_sol));

  if (typeof Chart === "undefined") {
    document.getElementById("history-chart").replaceWith(
      Object.assign(document.createElement("p"), {
        textContent: "Chart library failed to load (offline or CDN blocked).",
        style: "color:#8b91a7;font-size:13px;",
      })
    );
    return;
  }

  if (!chart) {
    const ctx = document.getElementById("history-chart").getContext("2d");
    chart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: lastPriceUnit === "sol" ? "Price (SOL)" : "Price (USD)",
            data: prices,
            borderColor: "#38bdf8",
            backgroundColor: "rgba(56,189,248,0.08)",
            yAxisID: "y",
            tension: 0.25,
            pointRadius: 0,
          },
          {
            label: "Daily PnL (SOL)",
            data: pnls,
            borderColor: "#a78bfa",
            backgroundColor: "rgba(167,139,250,0.08)",
            yAxisID: "y1",
            tension: 0.25,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { position: "left", ticks: { color: "#8b91a7" }, grid: { color: "#232838" } },
          y1: { position: "right", ticks: { color: "#8b91a7" }, grid: { display: false } },
          x: { ticks: { color: "#8b91a7", maxTicksLimit: 8 }, grid: { display: false } },
        },
        plugins: { legend: { labels: { color: "#e7e9f0" } } },
      },
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = prices;
    chart.data.datasets[1].data = pnls;
    chart.update("none");
  }
}

async function refreshTrades() {
  let rows;
  try {
    rows = await fetchJson("/api/trades?limit=50");
  } catch (e) {
    return;
  }
  const body = document.getElementById("trades-body");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty">no trades yet</td></tr>';
    return;
  }
  body.innerHTML = rows
    .map((r) => {
      const time = new Date(Number(r.timestamp) * 1000).toLocaleString();
      const actionClass = r.action === "buy" ? "action-buy" : r.action === "sell" ? "action-sell" : "";
      const tx = r.signature
        ? `<a class="tx-link" href="https://solscan.io/tx/${r.signature}" target="_blank" rel="noopener">${shortSig(r.signature)}</a>`
        : "—";
      const mintLabel = r.mint ? `${r.mint.slice(0, 4)}…${r.mint.slice(-4)}` : "";
      return `<tr>
        <td>${time}</td>
        <td class="${actionClass}">${r.action.toUpperCase()}${mintLabel ? ` <span style="color:#8b91a7;">${mintLabel}</span>` : ""}</td>
        <td>${Number(r.size_sol).toFixed(4)}</td>
        <td>${fmtPrice(r.price_usd)}</td>
        <td>${r.reason}</td>
        <td>${tx}</td>
      </tr>`;
    })
    .join("");
}

async function refreshAll() {
  // refreshState sets lastPriceUnit, which refreshHistory/refreshTrades
  // read -- run it first so they don't render with a stale default.
  await refreshState();
  await Promise.all([refreshBalance(), refreshHistory(), refreshTrades()]);
}

refreshAll();
setInterval(refreshAll, REFRESH_MS);
