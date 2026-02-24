/* ═══════════════════════════════════════════════════════════════
   OCDR Dashboard — Shared JS utilities
   ═══════════════════════════════════════════════════════════════ */

async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${url}`);
    return resp.json();
}

function formatCurrency(val) {
    if (val == null) return '$0';
    if (Math.abs(val) >= 1000000) {
        return '$' + (val / 1000000).toFixed(2) + 'M';
    }
    if (Math.abs(val) >= 1000) {
        return '$' + (val / 1000).toFixed(1) + 'K';
    }
    return '$' + val.toFixed(2);
}

function formatNumber(val) {
    if (val == null) return '0';
    return val.toLocaleString('en-US');
}

function formatDate(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr + 'T00:00:00');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function statusBadge(status) {
    const map = {
        'PAST_DEADLINE': 'badge-past-deadline',
        'WARNING': 'badge-warning',
        'SAFE': 'badge-safe',
        'DENIED': 'badge-denied',
        'APPEALED': 'badge-appealed',
        'RESOLVED': 'badge-resolved',
        'WRITTEN_OFF': 'badge-written-off',
    };
    const cls = map[status] || 'badge-warning';
    return `<span class="badge-status ${cls}">${status}</span>`;
}

// Chart.js global defaults
if (typeof Chart !== 'undefined') {
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.borderColor = 'rgba(148,163,184,0.08)';
    Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
}

// Auto-update timestamp
document.addEventListener('DOMContentLoaded', function() {
    const el = document.getElementById('last-updated');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
});
