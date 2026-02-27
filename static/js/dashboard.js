/* ═══════════════════════════════════════════════════════════════
   OCDR Dashboard — Shared JS utilities
   ═══════════════════════════════════════════════════════════════ */

async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${url}`);
    return resp.json();
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
    if (!isoStr) return '--';
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

// ── Toast Notifications ──────────────────────────────────────

function showToast(message, type) {
    type = type || 'info';
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const icons = {
        success: 'bi-check-circle-fill',
        error: 'bi-x-circle-fill',
        warning: 'bi-exclamation-circle-fill',
        info: 'bi-info-circle-fill'
    };
    const toast = document.createElement('div');
    toast.className = 'toast-msg toast-' + (type === 'warning' ? 'info' : type);
    toast.innerHTML = '<i class="bi ' + (icons[type] || icons.info) + '"></i> ' + message;
    container.appendChild(toast);
    setTimeout(function() {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(function() { toast.remove(); }, 300);
    }, 4000);
}

// ── Empty state helper ───────────────────────────────────────

function renderEmptyState(containerId, icon, message, actionUrl, actionLabel) {
    const el = document.getElementById(containerId);
    if (!el) return;
    let html = '<div class="empty-state">';
    html += '<i class="bi ' + icon + '"></i>';
    html += '<p>' + message + '</p>';
    if (actionUrl && actionLabel) {
        html += '<a href="' + actionUrl + '" class="btn btn-sm btn-outline-primary">' + actionLabel + '</a>';
    }
    html += '</div>';
    el.innerHTML = html;
}

// ── Chart.js global defaults ─────────────────────────────────

if (typeof Chart !== 'undefined') {
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.borderColor = 'rgba(148,163,184,0.08)';
    Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
}

// ── Bootstrap Tooltip Initialization ─────────────────────────

function initTooltips() {
    if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
        var tooltipEls = document.querySelectorAll('[data-bs-toggle="tooltip"]');
        tooltipEls.forEach(function(el) {
            new bootstrap.Tooltip(el, {
                trigger: 'hover',
                placement: el.getAttribute('data-bs-placement') || 'top',
                html: el.hasAttribute('data-bs-html'),
            });
        });
    }
}

// ── CAS Code Descriptions ───────────────────────────────────

var CAS_GROUP_CODES = {
    CO: 'Contractual Obligation — provider write-off per contract',
    CR: 'Correction/Reversal — prior claim correction',
    OA: 'Other Adjustment — not classified elsewhere',
    PI: 'Payer Initiated — payer-imposed reduction',
    PR: 'Patient Responsibility — patient owes this amount',
};

var CAS_COMMON_REASONS = {
    '1': 'Deductible',
    '2': 'Coinsurance',
    '3': 'Copayment',
    '4': 'Procedure code inconsistent with modifier',
    '5': 'Procedure code inconsistent with place of service',
    '16': 'Missing information',
    '18': 'Duplicate claim/service',
    '22': 'Care may be covered by another payer',
    '23': 'Charges exceed fee schedule',
    '24': 'Charges covered under capitation',
    '26': 'Expenses incurred prior to coverage',
    '27': 'Expenses incurred after coverage ended',
    '29': 'Time limit for filing has expired',
    '31': 'Non-covered service (patient liability)',
    '45': 'Charges exceed usual & customary',
    '50': 'Non-covered service (not patient liability)',
    '96': 'Non-covered charge(s)',
    '97': 'Payment adjusted — not authorized',
    '109': 'Not covered by this payer/contractor',
    '119': 'Benefit maximum reached',
    '197': 'Precertification/authorization absent',
    '204': 'Service not covered in this setting',
    '236': 'Level of care not covered',
    '242': 'Service not covered — plan limitation',
};

function getCasGroupTooltip(code) {
    if (!code) return '';
    return CAS_GROUP_CODES[code] || 'Adjustment group: ' + code;
}

function getCasReasonTooltip(code) {
    if (!code) return '';
    return CAS_COMMON_REASONS[code] || 'Reason code: ' + code;
}

// ── Sortable Table Headers ────────────────────────────────────

/**
 * Initialize sortable column headers for a table.
 * Expects <th data-sort="column_name"> in thead.
 * @param {string} tableId - The table element ID
 * @param {function} onSort - Callback(sortColumn, sortDir) called when sort changes
 * @returns {object} - { getSort(), reset() } for external control
 */
function initSortableTable(tableId, onSort) {
    var table = document.getElementById(tableId);
    if (!table) return { getSort: function() { return {}; }, reset: function() {} };

    var currentSort = '';
    var currentDir = '';
    var headers = table.querySelectorAll('th[data-sort]');

    headers.forEach(function(th) {
        th.addEventListener('click', function() {
            var col = th.getAttribute('data-sort');
            if (currentSort === col) {
                currentDir = currentDir === 'asc' ? 'desc' : currentDir === 'desc' ? '' : 'asc';
            } else {
                currentSort = col;
                currentDir = 'asc';
            }
            if (!currentDir) currentSort = '';

            // Update visual indicators
            headers.forEach(function(h) { h.classList.remove('sort-asc', 'sort-desc'); });
            if (currentDir) th.classList.add('sort-' + currentDir);

            if (onSort) onSort(currentSort, currentDir);
        });
    });

    return {
        getSort: function() { return { sort: currentSort, dir: currentDir }; },
        reset: function() {
            currentSort = '';
            currentDir = '';
            headers.forEach(function(h) { h.classList.remove('sort-asc', 'sort-desc'); });
        }
    };
}

// ── Expand Modal (click-to-expand for KPI/charts) ────────────

/**
 * Show an expand modal with custom content.
 * @param {string} title - Modal header title
 * @param {string|HTMLElement} content - HTML string or DOM element for the body
 * @param {object} opts - Optional: { width: '1100px', onClose: fn }
 */
function showExpandModal(title, content, opts) {
    opts = opts || {};
    closeExpandModal();  // close any existing

    var backdrop = document.createElement('div');
    backdrop.className = 'expand-modal-backdrop';
    backdrop.id = 'expand-backdrop';
    backdrop.onclick = closeExpandModal;

    var modal = document.createElement('div');
    modal.className = 'expand-modal';
    modal.id = 'expand-modal';
    if (opts.width) modal.style.maxWidth = opts.width;

    modal.innerHTML =
        '<div class="expand-modal-header">' +
            '<h5>' + escapeHtml(title) + '</h5>' +
            '<button class="expand-modal-close" onclick="closeExpandModal()">' +
                '<i class="bi bi-x-lg"></i>' +
            '</button>' +
        '</div>' +
        '<div class="expand-modal-body" id="expand-modal-body"></div>';

    document.body.appendChild(backdrop);
    document.body.appendChild(modal);

    var body = document.getElementById('expand-modal-body');
    if (typeof content === 'string') {
        body.innerHTML = content;
    } else if (content instanceof HTMLElement) {
        body.appendChild(content);
    }

    // Animate in
    requestAnimationFrame(function() {
        backdrop.classList.add('show');
        modal.classList.add('show');
    });

    // ESC to close
    modal._escHandler = function(e) { if (e.key === 'Escape') closeExpandModal(); };
    document.addEventListener('keydown', modal._escHandler);

    // Re-init tooltips inside modal
    if (typeof initTooltips === 'function') setTimeout(initTooltips, 100);
}

function closeExpandModal() {
    var backdrop = document.getElementById('expand-backdrop');
    var modal = document.getElementById('expand-modal');
    if (modal && modal._escHandler) {
        document.removeEventListener('keydown', modal._escHandler);
    }
    if (backdrop) { backdrop.classList.remove('show'); setTimeout(function() { backdrop.remove(); }, 200); }
    if (modal) { modal.classList.remove('show'); setTimeout(function() { modal.remove(); }, 200); }
}

/**
 * Render a detail stat grid for expand modals.
 * @param {Array} items - [{label, value, color}]
 * @returns {string} HTML
 */
function renderDetailStats(items) {
    return '<div class="detail-stat-grid">' +
        items.map(function(item) {
            var style = item.color ? 'color:' + item.color : '';
            return '<div class="detail-stat">' +
                '<div class="detail-stat-label">' + escapeHtml(item.label) + '</div>' +
                '<div class="detail-stat-value" style="' + style + '">' + item.value + '</div>' +
            '</div>';
        }).join('') + '</div>';
}

/**
 * Expand a Chart.js chart into a full-screen modal.
 * Clones the chart data and renders a new, larger chart.
 * @param {Chart} chartInstance - The Chart.js instance to expand
 * @param {string} title - Modal title
 */
function expandChart(chartInstance, title) {
    if (!chartInstance) return;

    var canvas = document.createElement('canvas');
    canvas.style.width = '100%';
    canvas.style.height = '500px';

    var wrapper = document.createElement('div');
    wrapper.style.position = 'relative';
    wrapper.style.height = '500px';
    wrapper.appendChild(canvas);

    showExpandModal(title, wrapper, { width: '1200px' });

    // Clone config and render larger chart
    var config = JSON.parse(JSON.stringify(chartInstance.config));
    config.options = config.options || {};
    config.options.responsive = true;
    config.options.maintainAspectRatio = false;
    if (config.options.plugins && config.options.plugins.legend) {
        config.options.plugins.legend.display = true;
    }

    setTimeout(function() {
        new Chart(canvas.getContext('2d'), config);
    }, 100);
}

// ── Auto-update timestamp ────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    var el = document.getElementById('last-updated');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
    initTooltips();
});
