
const API = "";
let currentUser = null;
let cachedAnomalies = [];
let cachedHealth = [];
let cachedTelemetry = [];
let liveTelemetry = [];
let liveAnomalies = [];
let activeAnomalyFeedList = [];
let activeAllAnomaliesList = [];
let liveRefreshInterval = null;
let activeTab = "overview";

// Password Visibility Toggle
function togglePasswordVisibility() {
  const pwd = document.getElementById("password");
  const eye = document.getElementById("eyeIcon");
  if (pwd.type === "password") {
    pwd.type = "text";
    eye.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858-5.908a10.04 10.04 0 013.682-.763c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m-1.99-3.953a3 3 0 11-4.243-4.243" />`;
  } else {
    pwd.type = "password";
    eye.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>`;
  }
}

// Quick fill credentials for demo accounts
function quickFill(user, pwd) {
  document.getElementById("username").value = user;
  document.getElementById("password").value = pwd;
  doLogin();
}

function showError(msg) {
  const errDiv = document.getElementById("loginError");
  const errText = document.getElementById("loginErrorText");
  errText.textContent = msg;
  errDiv.classList.remove("hidden");
}

function startLivePolling() {
  if (!liveRefreshInterval) {
    // 15-second frontend UI refresh timer (polls backend /api/live/status without triggering Open-Meteo)
    liveRefreshInterval = setInterval(loadSystemStatus, 15000);
  }
}

async function doLogin() {
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  const loginBtn = document.getElementById("loginBtn");

  if (!username || !password) {
    showError("Please enter both username and password.");
    return;
  }

  loginBtn.disabled = true;
  loginBtn.innerHTML = `
    <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
    </svg>
    <span>AUTHENTICATING...</span>
  `;

  try {
    const res = await fetch(API + "/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });

    if (!res.ok) {
      showError("Invalid username or password.");
      loginBtn.disabled = false;
      loginBtn.innerHTML = `<span>SIGN IN TO COMMAND CENTER</span>`;
      return;
    }

    currentUser = await res.json();
    document.getElementById("loginScreen").classList.add("hidden");
    document.getElementById("mainScreen").classList.remove("hidden");

    // Update user badges
    document.getElementById("userBadge").textContent = `${currentUser.name} (${currentUser.role})`;
    document.getElementById("sidebarUserName").textContent = currentUser.name;
    document.getElementById("sidebarUserRole").textContent = currentUser.role.toUpperCase();
    document.getElementById("userAvatar").textContent = currentUser.name.substring(0, 2).toUpperCase();

    switchTab("overview");
    loadSystemStatus();
    startLivePolling();
  } catch (e) {
    showError("Could not reach server. Is api.py running?");
    loginBtn.disabled = false;
    loginBtn.innerHTML = `<span>SIGN IN TO COMMAND CENTER</span>`;
  }
}

function logout() {
  currentUser = null;
  document.getElementById("mainScreen").classList.add("hidden");
  document.getElementById("loginScreen").classList.remove("hidden");
  document.getElementById("username").value = "";
  document.getElementById("password").value = "";
  document.getElementById("loginError").classList.add("hidden");
  if (liveRefreshInterval) {
    clearInterval(liveRefreshInterval);
    liveRefreshInterval = null;
  }
}

function toggleSidebar() {
  const sb = document.getElementById("sidebar");
  sb.classList.toggle("-translate-x-full");
}

function trustBadge(state) {
  const map = {
    ACCEPT: "badge-accept",
    CAUTION: "badge-caution",
    QUARANTINE: "badge-quarantine",
    REJECT: "badge-reject"
  };
  const cls = map[state] || "badge-caution";
  return `<span class="text-[11px] font-mono font-semibold px-2.5 py-0.5 rounded-full ${cls}">${state || "-"}</span>`;
}

function confidenceBar(pct) {
  const val = parseInt(pct) || 0;
  let barColor = "bg-blue-600";
  if (val >= 80) barColor = "bg-emerald-600";
  else if (val >= 50) barColor = "bg-amber-500";
  else if (val < 30) barColor = "bg-red-500";

  return `
    <div class="flex items-center space-x-2 font-mono text-xs">
      <div class="w-16 bg-slate-100 border border-slate-200 h-2 rounded-full overflow-hidden">
        <div class="${barColor} h-full rounded-full" style="width: ${val}%"></div>
      </div>
      <span class="font-semibold text-slate-700">${val}%</span>
    </div>
  `;
}

function buildTable(rows, columns, onRowClick = null, tableSource = 'cached') {
  if (!rows || rows.length === 0) {
    return `
      <div class="text-center py-10 bg-white rounded-xl border border-slate-100">
        <svg class="w-10 h-10 text-slate-300 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
        <p class="text-xs font-mono text-slate-400">No records found for current scope.</p>
      </div>
    `;
  }

  let thead = columns.map(c => `<th class="text-left px-4 py-3 text-[11px] font-mono text-slate-500 uppercase tracking-wider border-b border-slate-200 bg-slate-50/80 font-semibold">${c.label}</th>`).join("");

  let tbody = rows.map((r, idx) => {
    let cells = columns.map(c => `<td class="px-4 py-3.5 text-xs border-b border-slate-100">${c.render ? c.render(r) : (r[c.key] ?? "-")}</td>`).join("");
    const cursorCls = onRowClick ? "cursor-pointer hover:bg-blue-50/50" : "hover:bg-slate-50/50";
    return `<tr class="transition-colors bg-white ${cursorCls}" onclick='${onRowClick ? `handleRowClick(${idx}, "${tableSource}")` : ""}'>${cells}</tr>`;
  }).join("");

  return `<table class="w-full text-left border-collapse bg-white rounded-xl overflow-hidden shadow-xs"><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;
}

function handleRowClick(index, tableSource = 'cached') {
  let record = null;
  if (tableSource === 'overviewFeed' && activeAnomalyFeedList && activeAnomalyFeedList[index]) {
    record = activeAnomalyFeedList[index];
  } else if (tableSource === 'allAnomalies' && activeAllAnomaliesList && activeAllAnomaliesList[index]) {
    record = activeAllAnomaliesList[index];
  } else if (cachedAnomalies && cachedAnomalies[index]) {
    record = cachedAnomalies[index];
  }
  if (record) {
    openDrawer(record);
  }
}

function getLatestLiveRecord(selectedStationId = null) {
  if (!Array.isArray(liveTelemetry) || liveTelemetry.length === 0) {
    return null;
  }
  if (selectedStationId) {
    const match = liveTelemetry.find(r => r && r.station_id === selectedStationId && r.temperature != null);
    if (match) return match;
  }
  return [...liveTelemetry]
    .filter(record => record && record.timestamp && record.temperature != null)
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0] || null;
}

let selectedStation = "ST01";
let globalAnomalyHistory = [];

function getLatestLiveRecord(selectedStationId = null) {
  if (!Array.isArray(liveTelemetry) || liveTelemetry.length === 0) {
    return null;
  }
  if (selectedStationId) {
    const match = liveTelemetry.find(r => r && r.station_id === selectedStationId && r.temperature != null);
    if (match) return match;
  }
  return [...liveTelemetry]
    .filter(record => record && record.timestamp && record.temperature != null)
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0] || null;
}

function getLatestLiveAnomaly() {
  if (!Array.isArray(liveAnomalies) || liveAnomalies.length === 0) return null;
  return [...liveAnomalies]
    .filter(a => a && a.timestamp)
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0] || null;
}

function renderLiveAnomalyFeed() {
  const badgeEl = document.getElementById("anomalyFeedBadge");
  const feedEl = document.getElementById("overviewTable");

  if (!feedEl) return;

  const hasLiveAnomalies = liveAnomalies && Array.isArray(liveAnomalies) && liveAnomalies.length > 0;

  if (hasLiveAnomalies) {
    // Priority sort: timestamp DESC primary, confidence_% DESC secondary
    let displayList = [...liveAnomalies].sort((a, b) => {
      const tA = new Date(a.timestamp).getTime() || 0;
      const tB = new Date(b.timestamp).getTime() || 0;
      if (tB !== tA) return tB - tA;
      return (parseFloat(b["confidence_%"] || b.confidence) || 0) - (parseFloat(a["confidence_%"] || a.confidence) || 0);
    });

    activeAnomalyFeedList = displayList.slice(0, 20);

    if (badgeEl) {
      badgeEl.className = "text-xs font-mono font-semibold text-blue-700 bg-blue-50 px-3 py-1 rounded-full border border-blue-200";
      const newest = activeAnomalyFeedList[0];
      badgeEl.textContent = `Source: Open-Meteo Live ● ${newest && newest.timestamp ? newest.timestamp : 'Active Feed'}`;
    }

    feedEl.innerHTML = buildTable(activeAnomalyFeedList, anomalyColumns, true, 'overviewFeed');
    console.log(`[AnomalyFeed] received ${liveAnomalies.length} live anomalies | rendering ${activeAnomalyFeedList.length} events`);
  } else {
    activeAnomalyFeedList = [];
    if (badgeEl) {
      badgeEl.className = "text-xs font-mono font-semibold text-emerald-700 bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200";
      badgeEl.textContent = "Source: Open-Meteo Live ● All Stations Normal";
    }

    feedEl.innerHTML = `
      <div class="p-8 text-center bg-white rounded-xl border border-slate-100 space-y-2">
        <div class="inline-flex items-center justify-center w-10 h-10 rounded-full bg-emerald-50 text-emerald-600 font-bold text-sm font-mono">✓</div>
        <h4 class="text-sm font-bold text-slate-800 font-mono uppercase tracking-wide">NO ACTIVE LIVE ANOMALIES</h4>
        <p class="text-xs text-slate-500 font-mono max-w-md mx-auto">Current live observations contain no active anomaly events across monitored stations.</p>
      </div>
    `;
    console.log("[AnomalyFeed] 0 live anomalies | rendered zero-event state");
  }
}

function renderIntelligenceAttribution() {
  const container = document.getElementById("attributionBreakdown");
  if (!container) return;

  const hasLiveAnomalies = liveAnomalies && Array.isArray(liveAnomalies) && liveAnomalies.length > 0;
  const activeList = hasLiveAnomalies ? liveAnomalies : (cachedAnomalies || []);

  if (!activeList || activeList.length === 0) {
    container.innerHTML = `
      <div class="p-6 text-center bg-slate-50/80 rounded-xl border border-slate-200/80 space-y-1 font-mono">
        <div class="inline-flex items-center justify-center w-7 h-7 rounded-full bg-emerald-100 text-emerald-700 font-bold text-xs mb-1">✓</div>
        <div class="text-xs font-bold text-slate-700 uppercase">NO ACTIVE LIVE ANOMALIES</div>
        <p class="text-[11px] text-slate-400">Current live observations contain no active anomaly events for attribution.</p>
      </div>
    `;
    console.log("[Attribution] 0 active live anomaly events | rendered zero-event state");
    return;
  }

  const attrCounts = {};
  const evidenceLayersSet = new Set();
  let totalEvents = activeList.length;

  activeList.forEach(a => {
    const rawAttr = a.attribution || a.root_cause || "Sensor / Data Fault";
    attrCounts[rawAttr] = (attrCounts[rawAttr] || 0) + 1;

    if (a.flagged_by_rule) evidenceLayersSet.add("RULE");
    if (a.flagged_by_physics) evidenceLayersSet.add("PHYSICS");
    if (a.flagged_by_neighbor) evidenceLayersSet.add("NEIGHBOR");
    if (a.flagged_by_ml) evidenceLayersSet.add("ML");
  });

  const attrEntries = Object.entries(attrCounts).sort((a, b) => b[1] - a[1]);

  let itemsHtml = attrEntries.map(([category, count]) => {
    const pct = Math.round((count / totalEvents) * 100);
    return `
      <div>
        <div class="flex justify-between items-center text-xs mb-1 font-mono">
          <span class="text-slate-700 font-medium">${category}</span>
          <span class="text-blue-600 font-bold">${count} event${count === 1 ? '' : 's'} (${pct}%)</span>
        </div>
        <div class="w-full bg-slate-100 h-2 rounded-full overflow-hidden border border-slate-200/60">
          <div class="bg-gradient-to-r from-blue-600 to-indigo-600 h-full rounded-full" style="width: ${pct}%"></div>
        </div>
      </div>
    `;
  }).join("");

  const topCategory = attrEntries[0] ? attrEntries[0][0].toLowerCase() : "";
  let summaryExplanation = "Recent live observations are largely consistent with expected meteorological variation.";
  if (topCategory.includes("sensor") || topCategory.includes("hardware") || topCategory.includes("flatline") || topCategory.includes("stuck") || topCategory.includes("spike")) {
    summaryExplanation = "Recent anomalies are primarily associated with sensor/hardware or data quality fault evidence.";
  } else if (topCategory.includes("weather") || topCategory.includes("meteorological") || topCategory.includes("dew point") || topCategory.includes("thermal")) {
    summaryExplanation = "Recent anomalies are primarily consistent with intense local meteorological variations.";
  } else if (topCategory.includes("spatial") || topCategory.includes("neighbor") || topCategory.includes("tampering") || topCategory.includes("inconsistency")) {
    summaryExplanation = "Current live anomaly evidence suggests spatial inconsistency or sensor calibration drift.";
  } else if (totalEvents > 0) {
    summaryExplanation = "Current live anomaly evidence is distributed across meteorological and sensor fault indicators.";
  }

  const layersList = Array.from(evidenceLayersSet);
  const layersStr = layersList.length > 0 ? layersList.join(" • ") : "RULE • PHYSICS • ML";

  container.innerHTML = `
    <div class="space-y-3">
      ${itemsHtml}
      <div class="pt-3 border-t border-slate-100 font-mono text-[11px] space-y-2">
        <div class="p-2.5 rounded-lg bg-blue-50/60 border border-blue-100 text-blue-900 leading-snug">
          💡 <strong>Live Insights:</strong> ${summaryExplanation}
        </div>
        <div class="flex justify-between items-center text-slate-500 pt-1">
          <span>Evidence Layers Active:</span>
          <span class="font-bold text-slate-800">${layersStr}</span>
        </div>
        <div class="flex justify-between items-center text-slate-500">
          <span>Total Monitored Events:</span>
          <span class="font-bold text-blue-700">${totalEvents} Active Event${totalEvents === 1 ? '' : 's'}</span>
        </div>
      </div>
    </div>
  `;

  console.log(`[Attribution] received ${totalEvents} live anomaly events | grouped events:`, attrCounts);
}

function onStationChange(val) {
  selectedStation = val;
  console.log(`[LiveCharts] selectedStation = ${selectedStation}`);
  fetchLiveVisualizationData();
}

async function fetchLiveVisualizationData() {
  let samples = [];
  try {
    const liveRes = await fetch(API + "/api/live/status");
    if (liveRes.ok) {
      const liveData = await liveRes.json();
      globalAnomalyHistory = liveData.live_anomaly_history || liveData.latest_anomalies || [];
      
      const badge = document.getElementById("liveStatusBadge");
      const dot = document.getElementById("liveStatusDot");
      if (badge && dot) {
        if (liveData.collector_status === "RUNNING") {
          badge.className = "text-xs font-mono font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200";
          badge.textContent = "● LIVE";
          if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-500 pulse-glow";
        } else {
          badge.className = "text-xs font-mono font-semibold px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200";
          badge.textContent = "● STALE";
          if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-amber-500";
        }
      }
    }
  } catch (e) {
    const badge = document.getElementById("liveStatusBadge");
    const dot = document.getElementById("liveStatusDot");
    if (badge && dot) {
      badge.className = "text-xs font-mono font-semibold px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200";
      badge.textContent = "● STALE (OFFLINE)";
      if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-amber-500";
    }
  }

  console.log(`[LiveCharts] requesting ${API}/api/live/history?station_id=${selectedStation}&limit=50`);
  try {
    const historyRes = await fetch(`${API}/api/live/history?station_id=${selectedStation}&limit=50`);
    if (historyRes.ok) {
      const histData = await historyRes.json();
      samples = histData.samples || [];
      window.currentStationSamples = samples;
      console.log(`[LiveCharts] received ${samples.length} samples | stations in response = ${selectedStation}`);
    }
  } catch (e) {
    console.warn("[LiveCharts] Error fetching station history:", e);
  }

  if (samples && samples.length > 0) {
    const latest = samples[samples.length - 1];
    
    const tempEl = document.getElementById("summaryTemp");
    const pressEl = document.getElementById("summaryPressure");
    const humEl = document.getElementById("summaryHumidity");
    const tsEl = document.getElementById("summaryLastUpdated");
    const subtextEl = document.getElementById("summaryUpdateSubtext");

    const latestTempEl = document.getElementById("chartLatestTemp");
    const latestPressEl = document.getElementById("chartLatestPressure");
    const latestHumEl = document.getElementById("chartLatestHumidity");

    if (tempEl && latest.temperature != null) tempEl.textContent = `${parseFloat(latest.temperature).toFixed(1)} °C`;
    if (pressEl && latest.pressure != null) pressEl.textContent = `${parseFloat(latest.pressure).toFixed(1)} hPa`;
    if (humEl && latest.humidity != null) humEl.textContent = `${parseFloat(latest.humidity).toFixed(1)} %`;
    if (tsEl) tsEl.textContent = latest.timestamp ? `${latest.timestamp.substring(11, 19)} UTC` : 'Just now';
    if (subtextEl) subtextEl.textContent = `Station: ${selectedStation} ● Open-Meteo AWS`;

    if (latestTempEl && latest.temperature != null) latestTempEl.textContent = `${parseFloat(latest.temperature).toFixed(1)} °C`;
    if (latestPressEl && latest.pressure != null) latestPressEl.textContent = `${parseFloat(latest.pressure).toFixed(1)} hPa`;
    if (latestHumEl && latest.humidity != null) latestHumEl.textContent = `${parseFloat(latest.humidity).toFixed(1)} %`;

    console.log(`[LiveCharts] rendering ${selectedStation} charts`);
    renderTimelineChart("tempChartContainer", samples, "temperature", "°C", "#2563EB", globalAnomalyHistory);
    renderTimelineChart("pressureChartContainer", samples, "pressure", "hPa", "#4F46E5", globalAnomalyHistory);
    renderTimelineChart("humidityChartContainer", samples, "humidity", "%", "#06B6D4", globalAnomalyHistory);
  } else {
    document.getElementById("tempChartContainer").innerHTML = `<div class="p-8 text-center text-xs font-mono text-slate-400 bg-slate-50 rounded-xl border border-slate-200">Waiting for ${selectedStation} live observation timeline...</div>`;
    document.getElementById("pressureChartContainer").innerHTML = `<div class="p-8 text-center text-xs font-mono text-slate-400 bg-slate-50 rounded-xl border border-slate-200">Waiting for ${selectedStation} live observation timeline...</div>`;
    document.getElementById("humidityChartContainer").innerHTML = `<div class="p-8 text-center text-xs font-mono text-slate-400 bg-slate-50 rounded-xl border border-slate-200">Waiting for ${selectedStation} live observation timeline...</div>`;
  }
}

function renderTimelineChart(containerId, samples, paramKey, paramUnit, lineColor, anomalyList) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!samples || samples.length === 0) {
    container.innerHTML = `<div class="p-8 text-center text-xs font-mono text-slate-400 bg-slate-50 rounded-xl border border-slate-200">Waiting for live observation timeline data...</div>`;
    return;
  }

  const width = 800;
  const height = 160;
  const padL = 50;
  const padR = 25;
  const padT = 20;
  const padB = 30;
  const chartW = width - padL - padR;
  const chartH = height - padT - padB;

  const validSamples = samples.filter(s => s[paramKey] !== null && s[paramKey] !== undefined);
  if (validSamples.length === 0) {
    container.innerHTML = `<div class="p-8 text-center text-xs font-mono text-slate-400 bg-slate-50 rounded-xl border border-slate-200">No valid observations available for ${paramKey}.</div>`;
    return;
  }

  const vals = validSamples.map(s => parseFloat(s[paramKey]));
  let rawMin = Math.min(...vals);
  let rawMax = Math.max(...vals);

  let range = rawMax - rawMin;
  if (range === 0) range = 1.0;
  const minVal = rawMin - range * 0.15;
  const maxVal = rawMax + range * 0.15;

  const points = validSamples.map((s, idx) => {
    const x = padL + (idx / Math.max(1, validSamples.length - 1)) * chartW;
    const val = parseFloat(s[paramKey]);
    const y = padT + (1 - (val - minVal) / (maxVal - minVal)) * chartH;
    return { x, y, sample: s, val };
  });

  const polylinePoints = points.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

  const stationId = selectedStation;
  const stationAnomalies = (anomalyList || []).filter(a => a.station_id === stationId);

  let nodeSvgElements = "";
  points.forEach((p, idx) => {
    const matchedAnomaly = stationAnomalies.find(a => {
      if (!a.timestamp || !p.sample.timestamp) return false;
      return String(a.timestamp).substring(0, 16) === String(p.sample.timestamp).substring(0, 16);
    });

    const tsFormatted = p.sample.timestamp ? p.sample.timestamp.substring(11, 16) : `T${idx+1}`;

    if (matchedAnomaly) {
      nodeSvgElements += `
        <g class="cursor-pointer group" onclick="showAnomalyDetail('${matchedAnomaly.station_id}', '${matchedAnomaly.timestamp}')">
          <line x1="${p.x.toFixed(1)}" y1="${padT}" x2="${p.x.toFixed(1)}" y2="${padT + chartH}" stroke="#EF4444" stroke-width="1.5" stroke-dasharray="3,3" />
          <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="8" fill="#EF4444" fill-opacity="0.3" class="pulse-glow" />
          <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="5" fill="#EF4444" stroke="#FFFFFF" stroke-width="2" />
          <text x="${p.x.toFixed(1)}" y="${p.y - 9}" text-anchor="middle" font-size="9" fill="#DC2626" font-weight="bold" font-family="monospace">⚠ ANOMALY</text>
        </g>
      `;
    } else {
      nodeSvgElements += `
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3.5" fill="${lineColor}" stroke="#FFFFFF" stroke-width="1.5">
          <title>${tsFormatted} UTC: ${p.val.toFixed(1)} ${paramUnit}</title>
        </circle>
      `;
    }
  });

  const midVal = (minVal + maxVal) / 2;
  const gridLines = `
    <line x1="${padL}" y1="${padT}" x2="${width - padR}" y2="${padT}" stroke="#F1F5F9" stroke-dasharray="2,2" />
    <line x1="${padL}" y1="${padT + chartH * 0.5}" x2="${width - padR}" y2="${padT + chartH * 0.5}" stroke="#F1F5F9" stroke-dasharray="2,2" />
    <line x1="${padL}" y1="${padT + chartH}" x2="${width - padR}" y2="${padT + chartH}" stroke="#E2E8F0" />
    
    <text x="${padL - 8}" y="${padT + 4}" text-anchor="end" font-size="9" fill="#94A3B8" font-family="monospace">${maxVal.toFixed(1)}</text>
    <text x="${padL - 8}" y="${padT + chartH * 0.5 + 3}" text-anchor="end" font-size="9" fill="#94A3B8" font-family="monospace">${midVal.toFixed(1)}</text>
    <text x="${padL - 8}" y="${padT + chartH}" text-anchor="end" font-size="9" fill="#94A3B8" font-family="monospace">${minVal.toFixed(1)}</text>
  `;

  const firstTs = validSamples[0]?.timestamp ? validSamples[0].timestamp.substring(11, 16) : 'T1';
  const lastTs = validSamples[validSamples.length - 1]?.timestamp ? validSamples[validSamples.length - 1].timestamp.substring(11, 16) : 'T-Now';
  const midIndex = Math.floor(validSamples.length / 2);
  const midTs = validSamples[midIndex]?.timestamp ? validSamples[midIndex].timestamp.substring(11, 16) : '';

  const xAxisTicks = `
    <text x="${padL}" y="${height - 8}" text-anchor="start" font-size="9" fill="#94A3B8" font-family="monospace">${firstTs} UTC</text>
    ${midTs ? `<text x="${padL + chartW * 0.5}" y="${height - 8}" text-anchor="middle" font-size="9" fill="#94A3B8" font-family="monospace">${midTs} UTC</text>` : ''}
    <text x="${width - padR}" y="${height - 8}" text-anchor="end" font-size="9" fill="#94A3B8" font-family="monospace">${lastTs} UTC</text>
  `;

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" class="w-full h-full overflow-visible">
      ${gridLines}
      <polyline fill="none" stroke="${lineColor}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="${polylinePoints}" />
      ${nodeSvgElements}
      ${xAxisTicks}
    </svg>
  `;
}

function showAnomalyDetail(stationId, timestamp) {
  const popover = document.getElementById("anomalyDetailPopover");
  if (!popover) return;

  const anomaly = (globalAnomalyHistory || []).find(a => a.station_id === stationId && String(a.timestamp).substring(0, 16) === String(timestamp).substring(0, 16));
  
  if (!anomaly) {
    popover.innerHTML = `
      <div class="flex items-center justify-between text-slate-700">
        <span>Anomaly Event for <strong>${stationId}</strong> at <strong>${timestamp}</strong></span>
        <button onclick="document.getElementById('anomalyDetailPopover').classList.add('hidden')" class="text-slate-400 hover:text-slate-600 font-bold">✕</button>
      </div>
    `;
    popover.classList.remove("hidden");
    return;
  }

  const layers = [];
  if (anomaly.flagged_by_rule) layers.push("RULE (Range/Flatline)");
  if (anomaly.flagged_by_physics) layers.push("PHYSICS (Dew Point/Thermal)");
  if (anomaly.flagged_by_neighbor) layers.push("NEIGHBOR (Spatial Cross-Check)");
  if (anomaly.flagged_by_ml) layers.push("ML (Isolation Forest)");
  const layerStr = layers.length > 0 ? layers.join(" + ") : "Anomaly Detection Pipeline";

  popover.innerHTML = `
    <div class="flex items-center justify-between border-b border-red-200 pb-2">
      <div class="flex items-center space-x-2">
        <span class="w-2.5 h-2.5 rounded-full bg-red-600 pulse-glow"></span>
        <span class="font-bold text-red-700 font-mono text-xs uppercase">ANOMALY EVENT DETECTED</span>
      </div>
      <button onclick="document.getElementById('anomalyDetailPopover').classList.add('hidden')" class="text-slate-400 hover:text-slate-600 font-bold px-1.5">✕</button>
    </div>
    
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-[11px]">
      <div><span class="text-slate-500">Station:</span> <strong class="text-blue-700 font-mono">${anomaly.station_id}</strong></div>
      <div><span class="text-slate-500">Timestamp:</span> <strong class="text-slate-800 font-mono">${anomaly.timestamp}</strong></div>
      <div><span class="text-slate-500">Attribution:</span> <strong class="text-red-700 font-mono">${anomaly.attribution || 'Sensor Anomaly'}</strong></div>
      <div><span class="text-slate-500">Severity:</span> <strong class="text-red-700 font-mono">${anomaly.trust_state || anomaly.alert_priority || 'CAUTION'}</strong></div>
    </div>

    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] pt-1 border-t border-red-100">
      <div><span class="text-slate-500">Confidence Score:</span> <strong class="text-blue-700 font-mono">${(anomaly['confidence_%'] || 50).toFixed(1)}%</strong></div>
      <div><span class="text-slate-500">Evidence Layers:</span> <strong class="text-slate-800 font-mono">${layerStr}</strong></div>
    </div>
    ${anomaly.corrected_value ? `<div class="text-[11px] text-slate-700 pt-1 border-t border-red-100">💡 <strong>Corrected Value Estimate:</strong> ${anomaly.corrected_value}</div>` : ''}
  `;
  popover.classList.remove("hidden");
}

async function loadSystemStatus() {
  try {
    const res = await fetch(API + "/api/system-status");
    const data = await res.json();
    const dot = document.getElementById("statusDot");
    const text = document.getElementById("statusText");
    if (data.status === "ok") {
      if (dot) dot.className = "w-2 h-2 rounded-full bg-emerald-500 pulse-glow";
      if (text) text.textContent = "Pipeline Operational";
    } else {
      if (dot) dot.className = "w-2 h-2 rounded-full bg-amber-500";
      if (text) text.textContent = "Pipeline Output Missing";
    }
  } catch (e) {
    const text = document.getElementById("statusText");
    if (text) text.textContent = "API Disconnected";
  }

  try {
    const liveRes = await fetch(API + "/api/live/status");
    if (liveRes.ok) {
      const liveData = await liveRes.json();
      const liveBadge = document.getElementById("liveMeteoBadge");
      const liveText = document.getElementById("liveStatusText");

      if (liveData.latest_telemetry && Array.isArray(liveData.latest_telemetry) && liveData.latest_telemetry.length > 0) {
        const validReadings = liveData.latest_telemetry.filter(r => r && r.temperature != null);
        if (validReadings.length > 0) {
          liveTelemetry = validReadings;
        }
      }

      if (liveData.live_anomaly_history && Array.isArray(liveData.live_anomaly_history) && liveData.live_anomaly_history.length > 0) {
        liveAnomalies = liveData.live_anomaly_history;
      } else if (liveData.latest_anomalies && Array.isArray(liveData.latest_anomalies) && liveData.latest_anomalies.length > 0) {
        liveAnomalies = liveData.latest_anomalies;
      }

      if (liveBadge && liveText) {
        if (liveData.collector_status === "RUNNING") {
          liveBadge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-blue-50 border border-blue-200 text-blue-700";
          const newestRec = getLatestLiveRecord(selectedStation);
          const timeLabel = newestRec && newestRec.timestamp ? newestRec.timestamp.substring(11, 19) : (liveData.last_successful_fetch ? liveData.last_successful_fetch.substring(11, 19) : "ACTIVE");
          liveText.textContent = `LIVE METEO ● ${timeLabel} UTC`;
        } else if (liveData.collector_status === "TEMPORARILY UNAVAILABLE") {
          liveBadge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-amber-50 border border-amber-200 text-amber-700";
          liveText.textContent = liveTelemetry.length > 0 ? "LIVE METEO ● LAST DATA AVAILABLE" : "LIVE METEO: TEMPORARILY UNAVAILABLE";
        } else {
          liveBadge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-slate-50 border border-slate-200 text-slate-600";
          liveText.textContent = "LIVE METEO: IDLE";
        }
      }

      renderLiveAnomalyFeed();
      renderIntelligenceAttribution();
      fetchLiveVisualizationData();
    }
  } catch (e) {
    console.warn("[LIVE UI] Network error fetching /api/live/status, keeping last valid liveTelemetry & liveAnomalies:", e);
    const liveBadge = document.getElementById("liveMeteoBadge");
    const liveText = document.getElementById("liveStatusText");
    if (liveBadge && liveText && liveTelemetry.length > 0) {
      liveBadge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-amber-50 border border-amber-200 text-amber-700";
      liveText.textContent = "LIVE METEO ● LAST DATA AVAILABLE (OFFLINE)";
    }
  }
}

async function fetchAnomalies() {
  const params = new URLSearchParams({ role: currentUser.role });
  if (currentUser.region) params.set("region", currentUser.region);
  const res = await fetch(API + "/api/anomalies?" + params.toString());
  cachedAnomalies = await res.json();
  return cachedAnomalies;
}

async function fetchTelemetry() {
  try {
    const res = await fetch(API + "/api/telemetry");
    if (res.ok) {
      cachedTelemetry = await res.json();
      return cachedTelemetry;
    }
  } catch (e) {}
  return [];
}

const anomalyColumns = [
  { key: "station_id", label: "Station", render: r => `<span class="font-mono font-bold text-blue-600">${r.station_id}</span>` },
  { key: "timestamp", label: "Timestamp", render: r => `<span class="font-mono text-slate-500">${r.timestamp || "-"}</span>` },
  { key: "attribution", label: "Issue / Attribution", render: r => `<span class="font-semibold text-slate-900">${r.attribution || "-"}</span>` },
  { key: "confidence_%", label: "Confidence", render: r => confidenceBar(r["confidence_%"] || r.confidence) },
  { key: "trust_state", label: "Trust State", render: r => trustBadge(r.trust_state || r.severity) },
  { key: "corrected_value", label: "Corrected Estimate", render: r => r.corrected_value ? `<span class="font-mono text-emerald-600 font-semibold">${r.corrected_value}</span>` : "-" },
  { key: "action", label: "Action", render: r => `<button class="px-2.5 py-1 rounded bg-blue-50 hover:bg-blue-100 border border-blue-200 text-blue-700 text-[11px] font-mono transition-colors font-semibold">Inspect →</button>` }
];

async function loadOverview() {
  const anomalies = await fetchAnomalies();
  const health = await (await fetch(API + "/api/health-scores")).json();
  cachedHealth = health;
  const telemetry = await fetchTelemetry();

  // Load system status to update live state
  await loadSystemStatus();

  // Use liveAnomalies source for KPI overview if active, fallback to cached
  const activeAnomaliesSource = (liveAnomalies && liveAnomalies.length > 0) ? liveAnomalies : anomalies;
  const total = activeAnomaliesSource.length;
  const critical = activeAnomaliesSource.filter(a => a.trust_state === "QUARANTINE" || a.trust_state === "REJECT" || a.severity === "QUARANTINE" || a.severity === "REJECT").length;
  const avgHealth = health.length ? (health.reduce((s, h) => s + parseFloat(h.health_score), 0) / health.length).toFixed(1) : "-";
  const worstStation = health.length ? health.reduce((a, b) => parseFloat(a.health_score) < parseFloat(b.health_score) ? a : b) : null;

  // KPI Cards Render
  const kpiEl = document.getElementById("kpiCards");
  if (kpiEl) {
    kpiEl.innerHTML = `
      <div class="glass-panel p-5 rounded-2xl bg-white/90">
        <div class="text-[11px] font-mono text-slate-400 uppercase tracking-wider font-semibold">Total Anomalies (${liveAnomalies.length > 0 ? 'Live Feed' : 'Role View'})</div>
        <div class="text-3xl font-extrabold text-slate-900 mt-1 font-mono">${total}</div>
        <div class="text-xs text-slate-500 mt-2 flex items-center space-x-1">
          <span class="text-blue-600">●</span> <span>${liveAnomalies.length > 0 ? 'Real-time live anomaly count' : 'Role-filtered live feed'}</span>
        </div>
      </div>

      <div class="glass-panel p-5 rounded-2xl border-l-4 border-red-500 bg-white/90">
        <div class="text-[11px] font-mono text-slate-400 uppercase tracking-wider font-semibold">Needs Attention</div>
        <div class="text-3xl font-extrabold text-red-600 mt-1 font-mono">${critical}</div>
        <div class="text-xs text-slate-500 mt-2">Quarantine / Reject state events</div>
      </div>

      <div class="glass-panel p-5 rounded-2xl border-l-4 border-blue-600 bg-white/90">
        <div class="text-[11px] font-mono text-slate-400 uppercase tracking-wider font-semibold">Avg. Station Health</div>
        <div class="text-3xl font-extrabold text-blue-600 mt-1 font-mono">${avgHealth}</div>
        <div class="text-xs text-slate-500 mt-2">Network health score index</div>
      </div>

      <div class="glass-panel p-5 rounded-2xl border-l-4 border-amber-500 bg-white/90">
        <div class="text-[11px] font-mono text-slate-400 uppercase tracking-wider font-semibold">Lowest Health Station</div>
        <div class="text-3xl font-extrabold text-amber-600 mt-1 font-mono">${worstStation ? worstStation.station_id : "-"}</div>
        <div class="text-xs text-slate-500 mt-2 truncate">${worstStation ? worstStation.health_score + " / 100 Score" : "No health data"}</div>
      </div>
    `;
  }

  // Render components using current live state
  fetchLiveVisualizationData();
  renderIntelligenceAttribution();
  renderLiveAnomalyFeed();
}

async function loadAnomalies() {
  const anomalies = await fetchAnomalies();
  const hasLiveAnomalies = liveAnomalies && Array.isArray(liveAnomalies) && liveAnomalies.length > 0;
  const list = hasLiveAnomalies ? [...liveAnomalies, ...anomalies] : anomalies;
  activeAllAnomaliesList = list;
  document.getElementById("anomalyCount").textContent = `${list.length} Record(s) ${hasLiveAnomalies ? '(Live Feed Active)' : ''}`;
  document.getElementById("anomalyTable").innerHTML = buildTable(list, anomalyColumns, true, 'allAnomalies');
}

async function loadTelemetry() {
  const historical = await fetchTelemetry();
  const isLiveActive = liveTelemetry && liveTelemetry.length > 0;
  const telemetry = isLiveActive ? liveTelemetry : historical;
  
  const countEl = document.getElementById("telemetryCount");
  if (countEl) {
    countEl.textContent = `${telemetry.length} ${isLiveActive ? 'Live Station Reading(s)' : 'Historical Baseline Sample(s)'}`;
  }

  const cols = [
    { key: "station_id", label: "Station", render: r => `<span class="font-mono font-bold text-blue-600">${r.station_id}</span>` },
    { key: "timestamp", label: "Timestamp", render: r => `<span class="font-mono text-slate-500">${r.timestamp || "-"}</span>` },
    { key: "temperature", label: "Temp (°C)", render: r => `<span class="font-mono text-slate-900 font-semibold">${r.temperature != null ? r.temperature + '°C' : '-'}</span>` },
    { key: "humidity", label: "Humidity (%)", render: r => `<span class="font-mono text-slate-700">${r.humidity != null ? r.humidity + '%' : '-'}</span>` },
    { key: "pressure", label: "Pressure (hPa)", render: r => `<span class="font-mono text-slate-700">${r.pressure != null ? r.pressure + ' hPa' : '-'}</span>` },
    { key: "rainfall", label: "Rainfall (mm)", render: r => `<span class="font-mono text-blue-600 font-semibold">${r.rainfall != null ? r.rainfall + 'mm' : '-'}</span>` },
    { key: "status", label: "Status", render: r => r.status ? `<span class="font-mono text-xs font-semibold ${r.status === 'ANOMALY' ? 'text-red-600' : 'text-emerald-600'}">${r.status}</span>` : '-' }
  ];

  document.getElementById("telemetryTable").innerHTML = buildTable(telemetry, cols);
}

async function loadHealth() {
  let healthScores = [];
  try {
    const liveRes = await fetch(API + "/api/live/status");
    if (liveRes.ok) {
      const liveData = await liveRes.json();
      if (liveData.latest_health_scores && liveData.latest_health_scores.length > 0) {
        healthScores = liveData.latest_health_scores;
      }
    }
  } catch (e) {}

  if (!healthScores || healthScores.length === 0) {
    try {
      const res = await fetch(API + "/api/health-scores");
      healthScores = await res.json();
    } catch (e) {}
  }
  cachedHealth = healthScores;

  const cols = [
    { 
      key: "station_id", 
      label: "STATION", 
      render: r => `<span class="font-mono font-bold text-blue-600">${r.station_id}</span>` 
    },
    { 
      key: "health_score", 
      label: "HEALTH SCORE", 
      render: r => {
        const score = parseFloat(r.health_score || 0);
        const color = score >= 90 ? 'text-emerald-600' : score >= 75 ? 'text-blue-600' : score >= 60 ? 'text-amber-600' : score >= 40 ? 'text-orange-600' : 'text-red-600';
        const bg = score >= 90 ? 'bg-emerald-500' : score >= 75 ? 'bg-blue-500' : score >= 60 ? 'bg-amber-500' : score >= 40 ? 'bg-orange-500' : 'bg-red-500';
        return `
          <div class="flex items-center space-x-2 font-mono font-bold">
            <span class="${color}">${score.toFixed(1)}</span>
            <div class="w-16 bg-slate-100 border border-slate-200 h-2 rounded-full overflow-hidden">
              <div class="${bg} h-full" style="width: ${Math.min(100, Math.max(0, score))}%"></div>
            </div>
          </div>
        `;
      } 
    },
    { 
      key: "status", 
      label: "STATUS", 
      render: r => {
        const st = r.status || (r.health_score >= 90 ? 'HEALTHY' : r.health_score >= 75 ? 'GOOD' : r.health_score >= 60 ? 'WARNING' : r.health_score >= 40 ? 'DEGRADED' : 'CRITICAL');
        const map = {
          HEALTHY: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          GOOD: 'bg-blue-50 text-blue-700 border-blue-200',
          WARNING: 'bg-amber-50 text-amber-700 border-amber-200',
          DEGRADED: 'bg-orange-50 text-orange-700 border-orange-200',
          CRITICAL: 'bg-red-50 text-red-700 border-red-200',
        };
        const cls = map[st] || map.GOOD;
        return `<span class="text-[11px] font-mono font-semibold px-2.5 py-0.5 rounded-full border ${cls}">${st}</span>`;
      } 
    },
    { 
      key: "maintenance_risk", 
      label: "MAINTENANCE RISK", 
      render: r => {
        const risk = r.maintenance_risk || (r.health_score < 40 ? 'CRITICAL' : r.health_score < 60 ? 'HIGH' : r.health_score < 75 ? 'MEDIUM' : 'LOW');
        const map = {
          LOW: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          MEDIUM: 'bg-amber-50 text-amber-700 border-amber-200',
          HIGH: 'bg-orange-50 text-orange-700 border-orange-200',
          CRITICAL: 'bg-red-50 text-red-700 border-red-200',
        };
        return `<span class="text-[11px] font-mono font-semibold px-2.5 py-0.5 rounded-full border ${map[risk] || map.LOW}">${risk}</span>`;
      } 
    },
    { 
      key: "maintenance_horizon", 
      label: "MAINTENANCE HORIZON", 
      render: r => {
        let horizonText = "Insufficient history";
        if (r.rul_days != null && r.rul_days > 0) {
          const days = Math.round(r.rul_days);
          horizonText = `${days} day${days === 1 ? '' : 's'}`;
        } else if (r.rul_days === 0 || (r.rul_label && r.rul_label.toLowerCase().includes("threshold crossed"))) {
          horizonText = "0 days (Inspect now)";
        } else if (r.rul_label) {
          const l = r.rul_label.toLowerCase();
          if (l.includes("not currently indicated") || l.includes("not indicated") || l.includes("insufficient degradation")) {
            horizonText = "Not indicated";
          } else if (l.includes("insufficient history")) {
            horizonText = "Insufficient history";
          } else {
            const match = r.rul_label.match(/\d+/);
            if (match) {
              horizonText = `${match[0]} days`;
            } else {
              horizonText = r.rul_label;
            }
          }
        }
        const colorCls = (horizonText.includes("day") && !horizonText.includes("Not")) ? 'text-red-600 font-semibold' : 'text-slate-600';
        return `<span class="font-mono text-xs ${colorCls}">${horizonText}</span>`;
      } 
    },
    { 
      key: "trend", 
      label: "DEGRADATION TREND", 
      render: r => {
        const tr = r.trend || "INSUFFICIENT_HISTORY";
        const map = {
          IMPROVING: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          STABLE: 'bg-blue-50 text-blue-700 border-blue-200',
          DEGRADING: 'bg-red-50 text-red-700 border-red-200',
          INSUFFICIENT_HISTORY: 'bg-slate-50 text-slate-600 border-slate-200',
        };
        const cls = map[tr] || map.INSUFFICIENT_HISTORY;
        let icon = tr === "IMPROVING" ? "↑ IMPROVING" : tr === "DEGRADING" ? "↓ DEGRADING" : tr === "STABLE" ? "→ STABLE" : "INSUFFICIENT_HISTORY";
        return `<span class="text-[11px] font-mono font-semibold px-2.5 py-0.5 rounded-full border ${cls}">${icon}</span>`;
      } 
    }
  ];

  document.getElementById("healthTable").innerHTML = buildTable(healthScores, cols);
}

async function loadComparison() {
  try {
    const data = await (await fetch(API + "/api/comparison")).json();
    const rows = data.existing_systems || [];
    const cols = [
      { key: "name", label: "System / Model", render: r => `<span class="font-bold text-slate-900">${r.name}</span>` },
      { key: "approach", label: "Technical Approach", render: r => `<span class="text-slate-700">${r.approach}</span>` },
      { key: "gap", label: "Operational Gap in India", render: r => `<span class="text-red-600 font-mono text-[11px] font-semibold">${r.gap}</span>` }
    ];
    document.getElementById("comparisonTable").innerHTML = buildTable(rows, cols);

    const diffs = data.our_differentiators || [];
    document.getElementById("differentiatorGrid").innerHTML = diffs.map(d => `
      <div class="glass-panel p-4 rounded-xl bg-white">
        <div class="font-bold text-blue-600 text-sm mb-1">✓ ${d.title}</div>
        <div class="text-xs text-slate-600 leading-relaxed">${d.detail}</div>
      </div>
    `).join("");

  } catch (e) {
    document.getElementById("comparisonTable").innerHTML = `<p class="text-xs font-mono text-slate-400">Comparison data unavailable.</p>`;
  }
}

function openDrawer(anomaly) {
  if (!anomaly) return;

  const checklistContainer = document.getElementById("chkRule") ? document.getElementById("chkRule").parentElement : null;
  if (!checklistContainer || !document.getElementById("chkRule")) {
    const parent = document.querySelector("#investigationDrawer .space-y-2.text-xs");
    if (parent) {
      parent.innerHTML = `
        <div id="chkRule" class="glass-panel p-3 rounded-lg flex items-center justify-between bg-white">
          <span class="text-slate-700">Temporal Range / Flatline Check</span>
          <span class="font-mono text-slate-400">Unflagged</span>
        </div>
        <div id="chkPhysics" class="glass-panel p-3 rounded-lg flex items-center justify-between bg-white">
          <span class="text-slate-700">Physics & Dew-Point Consistency</span>
          <span class="font-mono text-slate-400">Unflagged</span>
        </div>
        <div id="chkNeighbor" class="glass-panel p-3 rounded-lg flex items-center justify-between bg-white">
          <span class="text-slate-700">Spatial Cross-Check & Tampering</span>
          <span class="font-mono text-slate-400">Unflagged</span>
        </div>
        <div id="chkML" class="glass-panel p-3 rounded-lg flex items-center justify-between bg-white">
          <span class="text-slate-700">ML Isolation Forest Model</span>
          <span class="font-mono text-slate-400">Unflagged</span>
        </div>
      `;
    }
  }

  const flowParent = document.getElementById("drawerLayersTriggered") ? document.getElementById("drawerLayersTriggered").parentElement.parentElement : null;
  if (!flowParent || !document.getElementById("drawerLayersTriggered")) {
    const container = document.querySelector("#investigationDrawer .glass-panel.p-4.rounded-xl.font-mono");
    if (container) {
      container.parentElement.innerHTML = `
        <h4 class="text-xs font-mono text-slate-400 uppercase tracking-wider mb-3 font-semibold">VISUAL EVIDENCE FLOW</h4>
        <div class="glass-panel p-4 rounded-xl font-mono text-[11px] space-y-2 bg-slate-50 border border-slate-200">
          <div class="flex items-center space-x-2 text-slate-600">
            <span class="w-2 h-2 rounded-full bg-blue-600"></span>
            <span>OBSERVATION TELEMETRY</span>
          </div>
          <div class="pl-4 border-l border-slate-300 text-slate-400">↓ Layered Parallel Verification</div>
          <div class="flex items-center space-x-2 text-slate-700 font-semibold">
            <span class="w-2 h-2 rounded-full bg-indigo-600"></span>
            <span id="drawerLayersTriggered">PHYSICS + NEIGHBOR CHECK</span>
          </div>
          <div class="pl-4 border-l border-slate-300 text-slate-400">↓ Multi-Layer Fusion Engine</div>
          <div class="flex items-center space-x-2 text-emerald-700 font-bold">
            <span class="w-2 h-2 rounded-full bg-emerald-600"></span>
            <span id="drawerFinalAttributionNode">CONFIDENCE FUSED (88%)</span>
          </div>
        </div>
      `;
    }
  }

  document.getElementById("drawerStationTitle").textContent = `${anomaly.station_id} — ${anomaly.timestamp || ''}`;
  document.getElementById("drawerAttribution").textContent = anomaly.attribution || "Anomaly Flagged";
  document.getElementById("drawerTrustState").innerHTML = trustBadge(anomaly.trust_state);
  document.getElementById("drawerConfidenceTag").textContent = `Attribution Confidence: ${anomaly["confidence_%"]}%`;

  // Checklist Items
  const setCheck = (id, label, flag) => {
    const el = document.getElementById(id);
    if (!el) return;
    const isTrue = flag === true || flag === "True" || flag === "true";
    el.innerHTML = `
      <span class="text-slate-700 font-medium">${label}</span>
      <span class="font-mono text-xs ${isTrue ? 'text-blue-600 font-bold' : 'text-slate-400'}">${isTrue ? 'TRIGGERED ✓' : 'Passed'}</span>
    `;
  };

  setCheck("chkRule", "Temporal Range / Flatline Check", anomaly.flagged_by_rule);
  setCheck("chkPhysics", "Physics & Dew-Point Invariants", anomaly.flagged_by_physics);
  setCheck("chkNeighbor", "Spatial Cross-Check & Tampering", anomaly.flagged_by_neighbor);
  setCheck("chkML", "ML Isolation Forest Model", anomaly.flagged_by_ml);

  // Triggered layers list
  const layers = [];
  if (anomaly.flagged_by_rule) layers.push("RULE");
  if (anomaly.flagged_by_physics) layers.push("PHYSICS");
  if (anomaly.flagged_by_neighbor) layers.push("SPATIAL");
  if (anomaly.flagged_by_ml) layers.push("ML");
  const trigNode = document.getElementById("drawerLayersTriggered");
  if (trigNode) trigNode.textContent = layers.length ? layers.join(" + ") : "SINGLE LAYER VERIFICATION";

  const attrNode = document.getElementById("drawerFinalAttributionNode");
  if (attrNode) attrNode.textContent = `${(anomaly.attribution || 'FAULT').toUpperCase()} (${anomaly["confidence_%"]}%)`;
  
  const corrNode = document.getElementById("drawerCorrectedValue");
  if (corrNode) corrNode.textContent = anomaly.corrected_value ? `Corrected Estimate: ${anomaly.corrected_value}` : "No correction required.";

  // Open Drawer UI
  document.getElementById("drawerOverlay").classList.remove("hidden");
  setTimeout(() => {
    document.getElementById("drawerOverlay").classList.remove("opacity-0");
    document.getElementById("investigationDrawer").classList.remove("translate-x-full");
  }, 10);
}

function closeDrawer() {
  document.getElementById("investigationDrawer").classList.add("translate-x-full");
  document.getElementById("drawerOverlay").classList.add("opacity-0");
  setTimeout(() => {
    document.getElementById("drawerOverlay").classList.add("hidden");
  }, 200);
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab-content").forEach(el => el.classList.add("hidden"));
  document.getElementById("tab-" + tab).classList.remove("hidden");

  document.querySelectorAll(".nav-btn").forEach(b => {
    b.classList.remove("bg-blue-50", "text-blue-600", "border-l-4", "border-blue-600", "font-semibold");
    b.classList.add("text-slate-600");
  });

  const activeBtn = document.querySelector(`.nav-btn[data-tab="${tab}"]`);
  if (activeBtn) {
    activeBtn.classList.remove("text-slate-600");
    activeBtn.classList.add("bg-blue-50", "text-blue-600", "border-l-4", "border-blue-600", "font-semibold");
  }

  if (tab === "overview") loadOverview();
  if (tab === "telemetry") loadTelemetry();
  if (tab === "anomalies") loadAnomalies();
  if (tab === "health") loadHealth();
  if (tab === "about") loadComparison();
}
