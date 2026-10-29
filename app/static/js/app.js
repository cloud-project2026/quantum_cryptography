/**
 * PQC Migration Platform — Frontend Application
 * ===============================================
 * Handles all page navigation, API calls, chart rendering, and UI updates.
 * No framework required — plain JS with fetch() API.
 */

'use strict';

// ═══════════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════════
const state = {
  currentPage: 'overview',
  capabilities: null,    // cached from /api/system/capabilities
  selectedMode: 'classical',
  charts: {},            // Chart.js instances keyed by canvas id
  lastExperimentId: null,
};

// Chart.js default configuration for light theme
const CHART_DEFAULTS = {
  plugins: {
    legend: { labels: { color: '#334155', font: { family: 'Inter', size: 12, weight: 500 } } },
    tooltip: {
      backgroundColor: '#ffffff',
      borderColor: '#cbd5e1',
      borderWidth: 1,
      titleColor: '#0f172a',
      bodyColor: '#334155',
      padding: 10,
      cornerRadius: 6,
    },
  },
  scales: {
    x: { ticks: { color: '#64748b', font: { family: 'Inter', size: 11 } }, grid: { color: '#f1f5f9' } },
    y: { ticks: { color: '#64748b', font: { family: 'Inter', size: 11 } }, grid: { color: '#f1f5f9' } },
  },
};

// Mode descriptions for the UI
const MODE_DESCRIPTIONS = {
  classical: '<strong>Mode A — Classical TLS (X25519):</strong> Standard TLS 1.3 using X25519 elliptic-curve key exchange. This is the current internet standard. Fast and universally supported. Vulnerable to sufficiently powerful quantum computers in the future.',
  pqc:       '<strong>Mode B — Post-Quantum TLS (ML-KEM-768):</strong> TLS 1.3 key exchange using ML-KEM-768 only (NIST FIPS 203). Provides quantum-resistant key establishment. Note: certificate authentication is still classical unless also upgraded. Requires oqs-provider.',
  hybrid:    '<strong>Mode C — Hybrid TLS (X25519 + ML-KEM-768):</strong> Combines both X25519 and ML-KEM-768 in one handshake. Recommended migration path — both algorithms must be broken simultaneously to compromise the session. Requires oqs-provider.',
};

// ═══════════════════════════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════════════════════════
function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const page = document.getElementById(`page-${pageId}`);
  const nav  = document.getElementById(`nav-${pageId}`);
  if (page) page.classList.add('active');
  if (nav)  nav.classList.add('active');

  state.currentPage = pageId;

  // Trigger page-specific data loading
  switch (pageId) {
    case 'overview': loadOverview(); break;
    case 'compare':  loadComparison(); break;
    case 'history':  loadHistory(); break;
    case 'system':   loadSystemInfo(); break;
  }
}

// Wire up nav buttons
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => showPage(btn.dataset.page));
});

// ═══════════════════════════════════════════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════════════════════════════════════════
async function apiFetch(url, options = {}) {
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      throw new ApiError(body.error || body.message || `HTTP ${res.status}`, body);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Network error: ${err.message}`);
  }
}

class ApiError extends Error {
  constructor(message, data = null) {
    super(message);
    this.data = data;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// OVERVIEW PAGE
// ═══════════════════════════════════════════════════════════════════════════
async function loadOverview() {
  // Load server status
  try {
    const status = await apiFetch('/api/system/status');
    updateSidebarStatus(true, status.openssl_version);

    document.getElementById('ov-total').textContent = status.total_experiments;
    document.getElementById('banner-status-text').textContent =
      `Server running — Python ${status.python_version} · ${status.platform}`;
    document.getElementById('banner-openssl').textContent = status.openssl_version;
    document.getElementById('banner-dot').classList.add('pulse');
    document.getElementById('status-dot').className = 'status-dot online';
    document.getElementById('status-text').textContent = 'Online';

    if (status.latest_experiment) {
      renderLatestExperiment(status.latest_experiment);
    }
  } catch (err) {
    updateSidebarStatus(false);
    document.getElementById('banner-status-text').textContent = 'Server unavailable';
    document.getElementById('banner-dot').classList.remove('pulse');
  }

  // Load capabilities for badge colours
  await loadCapabilities();
  updateModeBadges();
}

function renderLatestExperiment(exp) {
  const card = document.getElementById('latest-experiment-body');
  const modeColor = { classical: 'tag-classical', pqc: 'tag-pqc', hybrid: 'tag-hybrid' };
  const statusColor = exp.status === 'completed' ? 'tag-ok' : exp.status === 'running' ? 'tag-running' : 'tag-fail';

  card.innerHTML = `
    <div class="latest-exp-grid">
      <div class="latest-exp-item">
        <div class="lei-label">Mode</div>
        <div class="lei-val"><span class="tag ${modeColor[exp.mode] || ''}">${exp.mode}</span></div>
      </div>
      <div class="latest-exp-item">
        <div class="lei-label">Status</div>
        <div class="lei-val"><span class="tag ${statusColor}">${exp.status}</span></div>
      </div>
      <div class="latest-exp-item">
        <div class="lei-label">Mean Latency</div>
        <div class="lei-val">${exp.mean_latency_ms != null ? exp.mean_latency_ms.toFixed(2) + ' ms' : '—'}</div>
      </div>
      <div class="latest-exp-item">
        <div class="lei-label">Timestamp</div>
        <div class="lei-val" style="font-size:11px">${formatDate(exp.created_at)}</div>
      </div>
    </div>`;
}

function updateModeBadges() {
  if (!state.capabilities) return;
  const { modes } = state.capabilities;

  function setBadge(id, available) {
    const badge = document.getElementById(id);
    if (!badge) return;
    badge.className = `metric-badge ${available ? 'badge-available' : 'badge-unavailable'}`;
    badge.textContent = available ? 'Available' : 'Not Available';
  }

  setBadge('ov-classical-badge', modes.classical.available);
  setBadge('ov-pqc-badge',       modes.pqc.available);
  setBadge('ov-hybrid-badge',    modes.hybrid.available);
}

function updateSidebarStatus(online, version = '') {
  document.getElementById('status-dot').className = `status-dot ${online ? 'online' : 'offline'}`;
  document.getElementById('status-text').textContent = online ? 'Online' : 'Offline';
}

// ═══════════════════════════════════════════════════════════════════════════
// CAPABILITIES
// ═══════════════════════════════════════════════════════════════════════════
async function loadCapabilities() {
  if (state.capabilities) return state.capabilities;
  try {
    state.capabilities = await apiFetch('/api/system/capabilities');
    updateModeButtons();
  } catch (err) {
    console.warn('Could not load capabilities:', err.message);
  }
  return state.capabilities;
}

function updateModeButtons() {
  if (!state.capabilities) return;
  const { modes } = state.capabilities;

  // Respect API availability for Classical, PQC, and Hybrid
  ['classical', 'pqc', 'hybrid'].forEach(mode => {
    const btn = document.getElementById(`mode-btn-${mode}`);
    const tag = document.getElementById(`mode-tag-${mode}`);
    if (!btn || !tag) return;

    const available = modes[mode]?.available;
    tag.textContent = available ? 'Available' : 'Unavailable';
    tag.className = `mode-status-tag ${available ? 'ok' : 'unavail'}`;

    if (!available) {
      btn.classList.add('disabled-mode');
      btn.disabled = true;
    } else {
      btn.classList.remove('disabled-mode');
      btn.disabled = false;
    }
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// RUN EXPERIMENT PAGE
// ═══════════════════════════════════════════════════════════════════════════

// Mode button wiring
document.querySelectorAll('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => selectMode(btn.dataset.mode));
});

function selectMode(mode) {
  if (!state.capabilities) { selectModeUI(mode); return; }
  const modeInfo = state.capabilities.modes[mode];

  selectModeUI(mode);

  document.getElementById('mode-description').innerHTML = MODE_DESCRIPTIONS[mode] || '';

  const warningEl = document.getElementById('pqc-unavailable-warning');
  const detailEl  = document.getElementById('pqc-unavailable-detail');

  if (modeInfo && !modeInfo.available) {
    warningEl.style.display = 'block';
    detailEl.textContent = modeInfo.limitations || 'This mode requires additional setup.';
    document.getElementById('start-btn').disabled = true;
  } else {
    warningEl.style.display = 'none';
    document.getElementById('start-btn').disabled = false;
  }

  // Auto-set sensible port defaults
  const portInput = document.getElementById('cfg-port');
  if (mode === 'classical') {
    // For classical we can test against example.com on 443
    portInput.value = 443;
  } else {
    portInput.value = 54443; // loopback server
  }
}

function selectModeUI(mode) {
  state.selectedMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
}

async function startExperiment() {
  const btn = document.getElementById('start-btn');
  const btnText = document.getElementById('start-btn-text');
  const livePanel = document.getElementById('run-live-results');
  const statusPanel = document.getElementById('run-status-panel');
  const errorBox = document.getElementById('run-error-box');
  const successBox = document.getElementById('run-success-box');

  // Collect config
  const config = {
    mode:        state.selectedMode,
    target_host: document.getElementById('cfg-host').value,
    target_port: parseInt(document.getElementById('cfg-port').value),
    repetitions: parseInt(document.getElementById('cfg-reps').value),
    concurrency: parseInt(document.getElementById('cfg-conc').value),
    warmup_runs: parseInt(document.getElementById('cfg-warmup').value),
    timeout_s:   parseFloat(document.getElementById('cfg-timeout').value),
  };

  // Show loading state
  btn.disabled = true;
  btnText.innerHTML = '<span class="spinner"></span> Running…';
  statusPanel.innerHTML = '';
  livePanel.style.display = 'block';
  errorBox.style.display = 'none';
  successBox.style.display = 'none';

  setProgressBar(10, 'Sending request…');
  document.getElementById('res-status').textContent = 'Running';

  try {
    setProgressBar(30, 'Connecting to server…');
    const data = await apiFetch('/api/experiments/run', {
      method: 'POST',
      body: JSON.stringify(config),
    });

    setProgressBar(100, 'Complete');
    const exp = data.experiment;
    state.lastExperimentId = exp.id;

    // Populate result grid
    document.getElementById('res-status').textContent  = exp.status;
    document.getElementById('res-mean').textContent    = fmtMs(exp.mean_latency_ms);
    document.getElementById('res-median').textContent  = fmtMs(exp.median_latency_ms);
    document.getElementById('res-minmax').textContent  = `${fmtMs(exp.min_latency_ms)} / ${fmtMs(exp.max_latency_ms)}`;
    document.getElementById('res-success').textContent = exp.success_rate_pct != null
      ? `${exp.success_count}/${exp.success_count + exp.failure_count} (${exp.success_rate_pct.toFixed(1)}%)`
      : '—';
    document.getElementById('res-tls-ver').textContent = exp.negotiated_tls_ver || 'See note ¹';
    document.getElementById('res-group').textContent   = exp.negotiated_group   || 'See note ²';
    document.getElementById('res-openssl').textContent = exp.openssl_version    || '—';

    if (exp.status === 'failed' || exp.success_count === 0) {
      errorBox.style.display = 'block';
      document.getElementById('run-error-detail').textContent =
        exp.error_summary || 'All handshakes failed. Check target host and port.';
    } else {
      successBox.style.display = 'block';
    }

    // ── Auto-refresh history so new run appears immediately ──────────────
    // Reset filter to 'All modes' so every experiment type is visible
    const histFilter = document.getElementById('history-filter-mode');
    if (histFilter) histFilter.value = '';
    // If history page is active, reload it; otherwise just prime the data
    if (state.currentPage === 'history') {
      loadHistory();
    }

  } catch (err) {
    setProgressBar(0, 'Error');
    errorBox.style.display = 'block';

    let msg = err.message;
    if (err.data) {
      if (err.data.error === 'mode_unsupported') {
        msg = `Mode not supported: ${err.data.details || err.data.message}`;
      } else {
        msg = err.data.error || err.data.message || msg;
      }
    }
    document.getElementById('run-error-detail').textContent = msg;
    document.getElementById('res-status').textContent = 'Failed';
    setProgressBar(0, 'Failed');
  } finally {
    btn.disabled = false;
    btnText.textContent = '▶ Start Benchmark';
  }
}

function setProgressBar(pct, label) {
  document.getElementById('progress-bar').style.width = pct + '%';
  document.getElementById('progress-text').textContent = label;
  document.getElementById('progress-pct').textContent  = pct + '%';
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPARE PAGE
// ═══════════════════════════════════════════════════════════════════════════
async function loadComparison() {
  const tableWrap = document.getElementById('compare-table-wrap');
  tableWrap.innerHTML = '<div class="loading-row"><span class="spinner"></span> Loading…</div>';

  try {
    const data = await apiFetch('/api/results/compare');
    renderComparisonTable(data);
    renderCharts(data);
  } catch (err) {
    tableWrap.innerHTML = `<div class="alert alert-error">Failed to load: ${err.message}</div>`;
  }

  // Load history-based time-series charts (classical vs PQC over time)
  await loadHistoryCharts();
}

function renderComparisonTable(data) {
  const wrap = document.getElementById('compare-table-wrap');
  const modes = ['classical', 'pqc', 'hybrid'];
  const hasAny = modes.some(m => data[m]?.mean_latency_ms != null || data[m]?.success_rate_pct != null);

  if (!hasAny) {
    wrap.innerHTML = '<div class="empty-state">No data yet — run experiments for each mode first.</div>';
    return;
  }

  const tagClass = { classical: 'tag-classical', pqc: 'tag-pqc', hybrid: 'tag-hybrid' };

  let html = `<table>
    <thead>
      <tr>
        <th>Mode</th>
        <th>Experiments</th>
        <th>Mean Latency</th>
        <th>Median</th>
        <th>Std Dev</th>
        <th>Min / Max</th>
        <th>Bytes (mean)</th>
        <th>Success Rate</th>
        <th>TLS Ver</th>
        <th>Group</th>
        <th>Latency Overhead</th>
      </tr>
    </thead><tbody>`;

  modes.forEach(m => {
    const d = data[m];
    if (!d) return;
    const noLatency = d.mean_latency_ms == null;
    const isFailed  = d.success_rate_pct === 0 || d.success_rate_pct === 0.0;
    const overhead = d.latency_overhead_pct;
    let overheadHTML = '—';
    if (overhead != null) {
      const cls = overhead > 0 ? 'overhead-positive' : overhead < 0 ? 'overhead-negative' : 'overhead-zero';
      const sign = overhead > 0 ? '+' : '';
      overheadHTML = `<span class="${cls}">${sign}${overhead.toFixed(1)}%</span>`;
    } else if (m === 'classical') {
      overheadHTML = '<span class="td-neutral">baseline</span>';
    }

    const expCount = d.experiment_count != null ? `${d.experiment_count} run${d.experiment_count !== 1 ? 's' : ''}` : '1 run';

    // For hybrid: show system limitation note if failed
    const latencyCell = noLatency
      ? (isFailed && m === 'hybrid'
          ? '<span class="td-neutral" title="Hybrid requires oqs-provider (OpenSSL 3.x)">N/A ⚠</span>'
          : '<span class="td-neutral">No data</span>')
      : fmtMs(d.mean_latency_ms);

    html += `<tr>
      <td class="td-mode"><span class="tag ${tagClass[m]}">${m}</span></td>
      <td style="font-size:11px;color:#64748b">${expCount}</td>
      <td>${latencyCell}</td>
      <td>${fmtMs(d.median_latency_ms)}</td>
      <td>${fmtMs(d.std_latency_ms)}</td>
      <td>${d.min_latency_ms != null ? fmtMs(d.min_latency_ms) + ' / ' + fmtMs(d.max_latency_ms) : '—'}</td>
      <td>${d.mean_bytes != null ? Math.round(d.mean_bytes) + ' B' : '—'}</td>
      <td>${d.success_rate_pct != null ? d.success_rate_pct.toFixed(1) + '%' : '—'}</td>
      <td>${d.negotiated_tls_ver || '—'}</td>
      <td>${d.negotiated_group || '—'}</td>
      <td>${overheadHTML}</td>
    </tr>`;
  });

  html += '</tbody></table>';

  if (!data.classical?.mean_latency_ms) {
    html += '<div class="alert alert-info" style="margin-top:12px">Run a <strong>Classical</strong> experiment first to see overhead comparisons against the baseline.</div>';
  }
  if (data.hybrid && data.hybrid.experiment_count > 0 && data.hybrid.success_rate_pct === 0) {
    html += `<div class="alert alert-warning" style="margin-top:12px">
      <strong>⚠ Hybrid mode (Mode C)</strong> handshakes failed. Check that the target host and loopback TLS server are active and reachable.
    </div>`;
  }

  wrap.innerHTML = html;
}

function renderCharts(data) {
  const modes   = ['classical', 'pqc', 'hybrid'];
  const labels  = ['Mode A — Classical (X25519)', 'Mode B — PQC (ML-KEM-768)', 'Mode C — Hybrid (X25519 + ML-KEM-768)'];
  const colors  = ['#2563eb', '#059669', '#7c3aed'];
  const colorsA = ['rgba(37,99,235,0.15)', 'rgba(5,150,105,0.15)', 'rgba(124,58,237,0.15)'];

  function latencyVal(m) {
    const d = data[m];
    if (!d) return null;
    return d.mean_latency_ms ?? null;
  }

  function successVal(m) {
    const d = data[m];
    if (!d) return null;
    return d.success_rate_pct ?? null;
  }

  const latencyVals = modes.map(latencyVal);
  const stdVals     = modes.map(m => data[m]?.std_latency_ms ?? 0);

  renderBarChart('chart-latency', labels, [{
    label: 'Mean Latency (ms)',
    data: latencyVals,
    backgroundColor: colorsA,
    borderColor: colors,
    borderWidth: 2,
  }], 'ms');

  // Bytes chart
  const byteVals = modes.map(m => data[m]?.mean_bytes ?? null);
  renderBarChart('chart-bytes', labels, [{
    label: 'Mean Bytes Transferred',
    data: byteVals,
    backgroundColor: colorsA,
    borderColor: colors,
    borderWidth: 2,
  }], 'bytes');

  // Success rate chart
  const successVals = modes.map(successVal);
  renderBarChart('chart-success', labels, [{
    label: 'Success Rate (%)',
    data: successVals,
    backgroundColor: colorsA,
    borderColor: colors,
    borderWidth: 2,
  }], '%', 100);

  // Overhead chart — PQC and Hybrid vs classical baseline
  const overheadLabels = ['Mode B — PQC (ML-KEM-768)', 'Mode C — Hybrid (X25519 + ML-KEM-768)'];
  const overheadData = [
    data.pqc?.latency_overhead_pct ?? null,
    data.hybrid?.latency_overhead_pct ?? null,
  ];
  renderBarChart('chart-overhead', overheadLabels, [{
    label: 'Latency Overhead vs. Classical (%)',
    data: overheadData,
    backgroundColor: overheadData.map(v => v == null ? 'rgba(100,116,139,0.15)' : v > 0 ? 'rgba(220,38,38,0.18)' : 'rgba(22,163,74,0.18)'),
    borderColor:     overheadData.map(v => v == null ? '#94a3b8' : v > 0 ? '#dc2626' : '#16a34a'),
    borderWidth: 2,
  }], '%');
}

// ─── History-based time-series charts ────────────────────────────────────────
async function loadHistoryCharts() {
  const section = document.getElementById('history-charts-section');
  if (!section) return;

  section.innerHTML = '<div class="loading-row"><span class="spinner"></span> Loading history charts…</div>';

  try {
    const data = await apiFetch('/api/experiments/?limit=200');
    const experiments = data.experiments || [];

    const classical = experiments
      .filter(e => e.mode === 'classical' && e.status === 'completed' && e.mean_latency_ms != null)
      .reverse();  // oldest first
    const pqc = experiments
      .filter(e => e.mode === 'pqc' && e.status === 'completed' && e.mean_latency_ms != null)
      .reverse();
    const hybrid = experiments
      .filter(e => e.mode === 'hybrid' && e.status === 'completed' && e.mean_latency_ms != null)
      .reverse();

    if (!classical.length && !pqc.length && !hybrid.length) {
      section.innerHTML = '<div class="empty-state">No completed experiments yet — run benchmarks to see time-series charts.</div>';
      return;
    }

    section.innerHTML = `
      <div class="card chart-card-wide">
        <div class="card-title">Latency Per Run — Classical vs PQC vs Hybrid Over Time <span class="card-hint">chronological order</span></div>
        <canvas id="chart-history-latency" height="90"></canvas>
      </div>
      <div class="chart-grid" style="margin-top:0">
        <div class="card chart-card">
          <div class="card-title">Latency Distribution <span class="card-hint">Box-style — min/mean/max per mode</span></div>
          <canvas id="chart-history-dist"></canvas>
        </div>
        <div class="card chart-card">
          <div class="card-title">Success Rate Per Run <span class="card-hint">Classical vs PQC vs Hybrid</span></div>
          <canvas id="chart-history-success"></canvas>
        </div>
      </div>`;

    // 1) Line chart: latency per run over time
    const maxLen = Math.max(classical.length, pqc.length, hybrid.length);
    const timeLabels = Array.from({ length: maxLen }, (_, i) => `Run ${i + 1}`);

    const classicalPadded = Array.from({ length: maxLen }, (_, i) =>
      classical[i] ? classical[i].mean_latency_ms : null);
    const pqcPadded = Array.from({ length: maxLen }, (_, i) =>
      pqc[i] ? pqc[i].mean_latency_ms : null);
    const hybridPadded = Array.from({ length: maxLen }, (_, i) =>
      hybrid[i] ? hybrid[i].mean_latency_ms : null);

    if (state.charts['chart-history-latency']) state.charts['chart-history-latency'].destroy();
    state.charts['chart-history-latency'] = new Chart(
      document.getElementById('chart-history-latency'),
      {
        type: 'line',
        data: {
          labels: timeLabels,
          datasets: [
            {
              label: 'Classical (X25519)',
              data: classicalPadded,
              borderColor: '#2563eb',
              backgroundColor: 'rgba(37,99,235,0.08)',
              pointBackgroundColor: '#2563eb',
              pointRadius: 4,
              pointHoverRadius: 6,
              tension: 0.3,
              fill: true,
              spanGaps: true,
            },
            {
              label: 'PQC (ML-KEM-768)',
              data: pqcPadded,
              borderColor: '#059669',
              backgroundColor: 'rgba(5,150,105,0.08)',
              pointBackgroundColor: '#059669',
              pointRadius: 4,
              pointHoverRadius: 6,
              tension: 0.3,
              fill: true,
              spanGaps: true,
            },
            {
              label: 'Hybrid (X25519 + ML-KEM-768)',
              data: hybridPadded,
              borderColor: '#7c3aed',
              backgroundColor: 'rgba(124,58,237,0.08)',
              pointBackgroundColor: '#7c3aed',
              pointRadius: 4,
              pointHoverRadius: 6,
              tension: 0.3,
              fill: true,
              spanGaps: true,
            },
          ],
        },
        options: {
          ...CHART_DEFAULTS,
          responsive: true,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            ...CHART_DEFAULTS.plugins,
            tooltip: {
              ...CHART_DEFAULTS.plugins.tooltip,
              callbacks: {
                label: ctx => ctx.raw != null ? `${ctx.dataset.label}: ${ctx.raw.toFixed(2)} ms` : 'No data',
              },
            },
          },
          scales: {
            x: { ...CHART_DEFAULTS.scales.x, title: { display: true, text: 'Experiment Run (oldest → newest)', color: '#64748b', font: { size: 10 } } },
            y: { ...CHART_DEFAULTS.scales.y, beginAtZero: true, title: { display: true, text: 'Mean Latency (ms)', color: '#64748b', font: { size: 10 } } },
          },
        },
      }
    );

    // 2) Min/Mean/Max distribution bar chart
    const distLabels = ['Classical (X25519)', 'PQC (ML-KEM-768)', 'Hybrid (X25519+ML-KEM)'];
    const meanVals = [
      classical.length ? classical.reduce((s, e) => s + e.mean_latency_ms, 0) / classical.length : null,
      pqc.length       ? pqc.reduce((s, e) => s + e.mean_latency_ms, 0) / pqc.length             : null,
      hybrid.length    ? hybrid.reduce((s, e) => s + e.mean_latency_ms, 0) / hybrid.length       : null,
    ];
    const minVals = [
      classical.length ? Math.min(...classical.map(e => e.min_latency_ms ?? e.mean_latency_ms)) : null,
      pqc.length       ? Math.min(...pqc.map(e => e.min_latency_ms ?? e.mean_latency_ms))       : null,
      hybrid.length    ? Math.min(...hybrid.map(e => e.min_latency_ms ?? e.mean_latency_ms))    : null,
    ];
    const maxVals = [
      classical.length ? Math.max(...classical.map(e => e.max_latency_ms ?? e.mean_latency_ms)) : null,
      pqc.length       ? Math.max(...pqc.map(e => e.max_latency_ms ?? e.mean_latency_ms))       : null,
      hybrid.length    ? Math.max(...hybrid.map(e => e.max_latency_ms ?? e.mean_latency_ms))    : null,
    ];

    if (state.charts['chart-history-dist']) state.charts['chart-history-dist'].destroy();
    state.charts['chart-history-dist'] = new Chart(
      document.getElementById('chart-history-dist'),
      {
        type: 'bar',
        data: {
          labels: distLabels,
          datasets: [
            { label: 'Min Latency (ms)', data: minVals, backgroundColor: ['rgba(37,99,235,0.2)', 'rgba(5,150,105,0.2)', 'rgba(124,58,237,0.2)'], borderColor: ['#2563eb','#059669','#7c3aed'], borderWidth: 2 },
            { label: 'Mean Latency (ms)', data: meanVals, backgroundColor: ['rgba(37,99,235,0.55)', 'rgba(5,150,105,0.55)', 'rgba(124,58,237,0.55)'], borderColor: ['#2563eb','#059669','#7c3aed'], borderWidth: 2 },
            { label: 'Max Latency (ms)', data: maxVals, backgroundColor: ['rgba(37,99,235,0.1)', 'rgba(5,150,105,0.1)', 'rgba(124,58,237,0.1)'], borderColor: ['#93c5fd','#6ee7b7','#c4b5fd'], borderWidth: 2, borderDash: [4,3] },
          ],
        },
        options: {
          ...CHART_DEFAULTS,
          responsive: true,
          plugins: { ...CHART_DEFAULTS.plugins, tooltip: { ...CHART_DEFAULTS.plugins.tooltip, callbacks: { label: ctx => ctx.raw != null ? `${ctx.dataset.label}: ${ctx.raw.toFixed(2)} ms` : 'No data' } } },
          scales: {
            x: { ...CHART_DEFAULTS.scales.x },
            y: { ...CHART_DEFAULTS.scales.y, beginAtZero: true, title: { display: true, text: 'ms', color: '#64748b', font: { size: 10 } } },
          },
        },
      }
    );

    // 3) Success rate per run
    const srClassical = classical.map(e => e.success_rate_pct ?? null);
    const srPqc       = pqc.map(e => e.success_rate_pct ?? null);
    const srHybrid    = hybrid.map(e => e.success_rate_pct ?? null);
    const srMax       = Math.max(classical.length, pqc.length, hybrid.length);
    const srLabels    = Array.from({ length: srMax }, (_, i) => `Run ${i + 1}`);
    const srCPad      = Array.from({ length: srMax }, (_, i) => srClassical[i] ?? null);
    const srPPad      = Array.from({ length: srMax }, (_, i) => srPqc[i] ?? null);
    const srHPad      = Array.from({ length: srMax }, (_, i) => srHybrid[i] ?? null);

    if (state.charts['chart-history-success']) state.charts['chart-history-success'].destroy();
    state.charts['chart-history-success'] = new Chart(
      document.getElementById('chart-history-success'),
      {
        type: 'line',
        data: {
          labels: srLabels,
          datasets: [
            { label: 'Classical Success Rate (%)', data: srCPad, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.08)', pointRadius: 4, tension: 0.2, fill: false, spanGaps: true },
            { label: 'PQC Success Rate (%)',       data: srPPad, borderColor: '#059669', backgroundColor: 'rgba(5,150,105,0.08)', pointRadius: 4, tension: 0.2, fill: false, spanGaps: true },
            { label: 'Hybrid Success Rate (%)',    data: srHPad, borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.08)', pointRadius: 4, tension: 0.2, fill: false, spanGaps: true },
          ],
        },
        options: {
          ...CHART_DEFAULTS,
          responsive: true,
          plugins: { ...CHART_DEFAULTS.plugins, tooltip: { ...CHART_DEFAULTS.plugins.tooltip, callbacks: { label: ctx => ctx.raw != null ? `${ctx.dataset.label}: ${ctx.raw.toFixed(1)}%` : 'No data' } } },
          scales: {
            x: { ...CHART_DEFAULTS.scales.x, title: { display: true, text: 'Experiment Run', color: '#64748b', font: { size: 10 } } },
            y: { ...CHART_DEFAULTS.scales.y, min: 0, max: 100, title: { display: true, text: '%', color: '#64748b', font: { size: 10 } } },
          },
        },
      }
    );

  } catch (err) {
    if (section) section.innerHTML = `<div class="alert alert-error">Failed to load history charts: ${err.message}</div>`;
  }
}

function renderBarChart(canvasId, labels, datasets, unit, suggestedMax = undefined) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  // Destroy existing chart
  if (state.charts[canvasId]) {
    state.charts[canvasId].destroy();
  }

  state.charts[canvasId] = new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      ...CHART_DEFAULTS,
      responsive: true,
      plugins: {
        ...CHART_DEFAULTS.plugins,
        tooltip: {
          ...CHART_DEFAULTS.plugins.tooltip,
          callbacks: {
            label: ctx => {
              const v = ctx.raw;
              return v != null ? `${ctx.dataset.label}: ${typeof v === 'number' ? v.toFixed(2) : v} ${unit}` : 'No data';
            },
          },
        },
      },
      scales: {
        x: { ...CHART_DEFAULTS.scales.x },
        y: {
          ...CHART_DEFAULTS.scales.y,
          beginAtZero: true,
          suggestedMax,
          title: {
            display: true,
            text: unit,
            color: '#64748b',
            font: { size: 10 },
          },
        },
      },
    },
  });
}

async function exportResults(fmt) {
  window.location.href = `/api/results/export?fmt=${fmt}`;
}

// ═══════════════════════════════════════════════════════════════════════════
// HISTORY PAGE
// ═══════════════════════════════════════════════════════════════════════════
async function loadHistory() {
  const wrap = document.getElementById('history-table-wrap');
  if (!wrap) return;
  wrap.innerHTML = '<div class="loading-row"><span class="spinner"></span> Loading…</div>';

  const modeFilter = document.getElementById('history-filter-mode')?.value || '';

  try {
    const url = modeFilter ? `/api/experiments/?mode=${modeFilter}&limit=100` : '/api/experiments/?limit=100';
    const data = await apiFetch(url);

    if (!data.experiments.length) {
      wrap.innerHTML = '<div class="empty-state">No experiments yet. Run your first benchmark!</div>';
      return;
    }

    const tagClass = { classical: 'tag-classical', pqc: 'tag-pqc', hybrid: 'tag-hybrid' };
    const statusClass = { completed: 'tag-ok', failed: 'tag-fail', running: 'tag-running', pending: 'tag-running' };

    let html = `<table>
      <thead><tr>
        <th>ID</th><th>Mode</th><th>Status</th><th>Reps</th><th>Concurrency</th>
        <th>Target</th><th>Mean Latency</th><th>Success Rate</th><th>Created</th><th>Actions</th>
      </tr></thead><tbody>`;

    data.experiments.forEach(exp => {
      html += `<tr>
        <td>${exp.id}</td>
        <td><span class="tag ${tagClass[exp.mode] || ''}">${exp.mode}</span></td>
        <td><span class="tag ${statusClass[exp.status] || ''}">${exp.status}</span></td>
        <td>${exp.repetitions}</td>
        <td>${exp.concurrency}</td>
        <td>${exp.target_host}:${exp.target_port}</td>
        <td>${fmtMs(exp.mean_latency_ms)}</td>
        <td>${exp.success_rate_pct != null ? exp.success_rate_pct.toFixed(1) + '%' : '—'}</td>
        <td style="font-size:11px">${formatDate(exp.created_at)}</td>
        <td>
          <button class="btn btn-secondary" style="padding:4px 8px;font-size:11px" onclick="openHistoryDetail(${exp.id})">Detail</button>
          <button class="btn btn-danger" style="padding:4px 8px;font-size:11px;margin-left:4px" onclick="deleteExperiment(${exp.id})">✕</button>
        </td>
      </tr>`;
    });

    html += '</tbody></table>';
    wrap.innerHTML = html;
  } catch (err) {
    wrap.innerHTML = `<div class="alert alert-error">Failed to load history: ${err.message}</div>`;
  }
}

async function openHistoryDetail(id) {
  const modal = document.getElementById('history-modal');
  const body  = document.getElementById('modal-body');
  const title = document.getElementById('modal-title');

  title.textContent = `Experiment #${id}`;
  modal.style.display = 'flex';
  body.innerHTML = '<div class="loading-row"><span class="spinner"></span> Loading…</div>';

  try {
    const data = await apiFetch(`/api/experiments/${id}`);
    const exp = data.experiment;
    const hs  = data.handshake_results;

    const tagClass = { classical: 'tag-classical', pqc: 'tag-pqc', hybrid: 'tag-hybrid' };
    const statusClass = { completed: 'tag-ok', failed: 'tag-fail', running: 'tag-running' };

    let html = `
      <div class="latest-exp-grid" style="margin-bottom:16px">
        <div class="latest-exp-item"><div class="lei-label">Mode</div>
          <div class="lei-val"><span class="tag ${tagClass[exp.mode]}">${exp.mode}</span></div></div>
        <div class="latest-exp-item"><div class="lei-label">Status</div>
          <div class="lei-val"><span class="tag ${statusClass[exp.status]}">${exp.status}</span></div></div>
        <div class="latest-exp-item"><div class="lei-label">Repetitions</div><div class="lei-val">${exp.repetitions}</div></div>
        <div class="latest-exp-item"><div class="lei-label">Concurrency</div><div class="lei-val">${exp.concurrency}</div></div>
        <div class="latest-exp-item"><div class="lei-label">Target</div><div class="lei-val">${exp.target_host}:${exp.target_port}</div></div>
        <div class="latest-exp-item"><div class="lei-label">Mean Latency</div><div class="lei-val">${fmtMs(exp.mean_latency_ms)}</div></div>
        <div class="latest-exp-item"><div class="lei-label">Success Rate</div>
          <div class="lei-val">${exp.success_rate_pct != null ? exp.success_rate_pct.toFixed(1) + '%' : '—'}</div></div>
        <div class="latest-exp-item"><div class="lei-label">TLS Version</div><div class="lei-val">${exp.negotiated_tls_ver || '—'}</div></div>
        <div class="latest-exp-item"><div class="lei-label">Group</div><div class="lei-val">${exp.negotiated_group || '—'}</div></div>
        <div class="latest-exp-item"><div class="lei-label">OpenSSL</div>
          <div class="lei-val" style="font-size:10px">${exp.openssl_version || '—'}</div></div>
      </div>`;

    if (exp.error_summary) {
      html += `<div class="alert alert-error" style="margin-bottom:16px"><strong>Error:</strong> ${exp.error_summary}</div>`;
    }

    // TLS note
    html += `<div class="alert alert-info" style="margin-bottom:12px;font-size:11px">
      <strong>¹ TLS Version / ² Group Notes:</strong> Python's ssl module on OpenSSL 1.1.x does not expose the
      negotiated key-exchange group name via the ssl.SSLSocket API. The TLS version is extracted from
      ssl.SSLSocket.version(). Group negotiation requires OpenSSL 3.x + oqs-provider.
    </div>`;

    // Handshake results table
    if (hs.length) {
      const nonWarmup = hs.filter(r => !r.is_warmup);
      const warmup    = hs.filter(r =>  r.is_warmup);

      html += `<div class="card-title">Individual Handshake Results (${nonWarmup.length} measurement + ${warmup.length} warmup)</div>`;
      html += `<div class="hs-table-wrap"><table>
        <thead><tr><th>Run</th><th>Type</th><th>Latency (ms)</th><th>Success</th><th>Cipher Suite</th><th>Error</th></tr></thead><tbody>`;

      hs.slice(0, 100).forEach(r => {
        html += `<tr>
          <td>${r.run_index}</td>
          <td>${r.is_warmup ? '<span class="tag" style="background:#f1f5f9;color:#475569;border:1px solid #e2e8f0">warmup</span>' : 'measure'}</td>
          <td>${r.latency_ms != null ? r.latency_ms.toFixed(2) : '—'}</td>
          <td>${r.success ? '<span class="td-good">✓</span>' : '<span class="td-bad">✗</span>'}</td>
          <td style="font-size:11px">${r.cipher_suite || '—'}</td>
          <td style="font-size:11px;color:#b91c1c">${r.error_type ? r.error_type + ': ' + (r.error_detail || '').slice(0,60) : ''}</td>
        </tr>`;
      });

      if (hs.length > 100) html += `<tr><td colspan="6" style="text-align:center;color:#64748b">…${hs.length - 100} more rows</td></tr>`;
      html += '</tbody></table></div>';
    }

    body.innerHTML = html;
  } catch (err) {
    body.innerHTML = `<div class="alert alert-error">Failed to load: ${err.message}</div>`;
  }
}

function closeHistoryModal(event) {
  if (!event || event.target === document.getElementById('history-modal') || event.currentTarget === event.target) {
    document.getElementById('history-modal').style.display = 'none';
  }
}

async function deleteExperiment(id) {
  if (!confirm(`Delete experiment #${id}? This cannot be undone.`)) return;
  try {
    await apiFetch(`/api/experiments/${id}`, { method: 'DELETE' });
    loadHistory();
  } catch (err) {
    alert(`Delete failed: ${err.message}`);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// SYSTEM INFO PAGE
// ═══════════════════════════════════════════════════════════════════════════
async function loadSystemInfo() {
  document.getElementById('system-loading').style.display = 'block';
  document.getElementById('system-content').style.display = 'none';

  try {
    const caps = await apiFetch('/api/system/capabilities');
    state.capabilities = caps;

    renderModeAvailability(caps.modes);
    renderOpenSSLDetails(caps);

    document.getElementById('system-loading').style.display = 'none';
    document.getElementById('system-content').style.display = 'block';
  } catch (err) {
    document.getElementById('system-loading').innerHTML =
      `<div class="alert alert-error">Failed to load capabilities: ${err.message}</div>`;
  }
}

function renderModeAvailability(modes) {
  const grid = document.getElementById('mode-availability-grid');
  const modeOrder = ['classical', 'pqc', 'hybrid'];

  grid.innerHTML = '<div class="mode-avail-grid">' +
    modeOrder.map(m => {
      const mode = modes[m];
      const avail = mode.available;
      const icon = avail ? '✓' : '✗';
      const iconColor = avail ? 'var(--accent-ok)' : 'var(--accent-er)';
      return `
        <div class="mode-avail-row">
          <div class="mode-avail-status">
            <span style="font-size:20px;color:${iconColor}">${icon}</span>
          </div>
          <div class="mode-avail-body">
            <div class="mode-avail-name">${mode.name}</div>
            <div class="mode-avail-desc">${mode.description}</div>
            ${mode.limitations ? `<div class="mode-avail-limit">⚠ ${mode.limitations}</div>` : ''}
          </div>
          <div>
            <span class="metric-badge ${avail ? 'badge-available' : 'badge-unavailable'}">
              ${avail ? 'Available' : 'Unavailable'}
            </span>
          </div>
        </div>`;
    }).join('') +
  '</div>';
}

function renderOpenSSLDetails(caps) {
  const table = document.getElementById('openssl-detail-table');
  const ossl = caps.openssl;
  const pqc  = caps.pqc_detection;
  const tls  = caps.tls_versions;
  const cgrp = caps.classical_groups;

  const rows = [
    ['OpenSSL Version',        ossl.string],
    ['Python Version',         caps.python_version.split(' ')[0]],
    ['Platform',               caps.platform],
    ['TLS 1.3 Support',        tls['TLSv1.3'] ? '✓ Yes' : '✗ No'],
    ['TLS 1.2 Support',        tls['TLSv1.2'] ? '✓ Yes' : '✗ No'],
    ['Classical Groups',       Object.entries(cgrp).filter(([,v])=>v).map(([k])=>k).join(', ') || 'None detected'],
    ['Native PQC Possible',    ossl.supports_native_pqc ? '✓ OpenSSL 3.3+' : '✗ Requires OpenSSL 3.3+'],
    ['OQS Provider Possible',  ossl.supports_oqs_provider ? '✓ OpenSSL 3.x' : '✗ Requires OpenSSL 3.x'],
    ['liboqs-python',          pqc.liboqs_python_available ? `✓ v${pqc.liboqs_python_version}` : '✗ Not installed'],
    ['OQS Provider Configured',pqc.oqs_provider_configured ? '✓ Active' : '✗ Not active'],
    ['PQC Groups Detected',    pqc.pqc_groups_detected.length ? pqc.pqc_groups_detected.join(', ') : 'None'],
  ];

  table.innerHTML = '<table class="sys-table">' +
    rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('') +
    '</table>';

  if (pqc.details?.length) {
    table.innerHTML += '<div style="margin-top:12px"><div class="card-title" style="margin-bottom:8px">Detection Notes</div>' +
      pqc.details.map(d => `<p style="font-size:12px;color:#475569;margin-bottom:6px">• ${d}</p>`).join('') +
      '</div>';
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════════════════
function fmtMs(val) {
  if (val == null || val === '') return '—';
  return parseFloat(val).toFixed(2) + ' ms';
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch { return iso; }
}

// ═══════════════════════════════════════════════════════════════════════════
// INITIALISE
// ═══════════════════════════════════════════════════════════════════════════
(async () => {
  // Initial mode selection (classical is always available)
  selectModeUI('classical');
  document.getElementById('mode-description').innerHTML = MODE_DESCRIPTIONS['classical'];

  // Load capabilities early (needed for mode buttons)
  await loadCapabilities();
  updateModeButtons();
  updateModeBadges();

  // Load overview
  showPage('overview');
})();
