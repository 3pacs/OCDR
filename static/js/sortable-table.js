/**
 * SortableTable – Reusable sortable, filterable, paginated table component.
 *
 * Usage:
 *   new SortableTable({
 *     apiUrl:       '/api/denials',
 *     filtersUrl:   '/api/denials/filters',       // optional
 *     tableId:      'queue-table',
 *     bodyId:       'queue-body',
 *     paginationId: 'pagination',
 *     totalId:      'total-count',
 *     loadingId:    'loading',
 *     filterFormId: 'filter-form',
 *     clearBtnId:   'btn-clear-filters',
 *     defaultSort:  'recoverability_score',
 *     defaultOrder: 'desc',
 *     perPage:      50,
 *     columns:      [ { key: 'patient_name', label: 'Patient', render: (v, row) => ... }, ... ],
 *     filterFields: [ { id: 'filter-status', param: 'status' }, ... ],
 *   });
 */
class SortableTable {
    constructor(opts) {
        this.apiUrl       = opts.apiUrl;
        this.filtersUrl   = opts.filtersUrl || null;
        this.columns      = opts.columns;
        this.filterFields = opts.filterFields || [];
        this.perPage      = opts.perPage || 50;

        this.state = {
            sortBy:    opts.defaultSort  || this.columns[0]?.key || 'id',
            sortOrder: opts.defaultOrder || 'desc',
            page:      1,
        };

        // DOM elements
        this.$table      = document.getElementById(opts.tableId);
        this.$body       = document.getElementById(opts.bodyId);
        this.$pagination = document.getElementById(opts.paginationId);
        this.$total      = document.getElementById(opts.totalId);
        this.$loading    = document.getElementById(opts.loadingId);
        this.$form       = document.getElementById(opts.filterFormId);
        this.$clearBtn   = document.getElementById(opts.clearBtnId);

        this._bindEvents();
        if (this.filtersUrl) this._loadFilters();
        this.fetch();
    }

    _bindEvents() {
        // Sortable headers
        this.$table.querySelector('thead').addEventListener('click', e => {
            const th = e.target.closest('th[data-sort]');
            if (!th) return;

            const col = th.dataset.sort;
            if (this.state.sortBy === col) {
                this.state.sortOrder = this.state.sortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                this.state.sortBy = col;
                this.state.sortOrder = 'desc';
            }
            this.state.page = 1;

            this.$table.querySelectorAll('th[data-sort]').forEach(h =>
                h.classList.remove('sort-asc', 'sort-desc'));
            th.classList.add(this.state.sortOrder === 'asc' ? 'sort-asc' : 'sort-desc');

            this.fetch();
        });

        // Filter form
        if (this.$form) {
            this.$form.addEventListener('submit', e => {
                e.preventDefault();
                this.state.page = 1;
                this.fetch();
            });
        }

        // Clear filters
        if (this.$clearBtn) {
            this.$clearBtn.addEventListener('click', () => {
                this.filterFields.forEach(f => {
                    const el = document.getElementById(f.id);
                    if (el) el.value = '';
                });
                this.state.page = 1;
                this.fetch();
            });
        }

        // Pagination
        if (this.$pagination) {
            this.$pagination.addEventListener('click', e => {
                e.preventDefault();
                const pg = e.target.closest('[data-page]');
                if (pg) {
                    this.state.page = parseInt(pg.dataset.page, 10);
                    this.fetch();
                }
            });
        }
    }

    async fetch() {
        this.$loading?.classList.remove('d-none');

        const params = new URLSearchParams({
            sort_by:    this.state.sortBy,
            sort_order: this.state.sortOrder,
            page:       this.state.page,
            per_page:   this.perPage,
        });

        this.filterFields.forEach(f => {
            const el = document.getElementById(f.id);
            const val = el?.value?.trim();
            if (val) params.set(f.param, val);
        });

        try {
            const resp = await fetch(this.apiUrl + '?' + params);
            const json = await resp.json();
            this._renderBody(json.data || []);
            this._renderPagination(json.page, json.total_pages, json.total);
            if (this.$total) this.$total.textContent = json.total ?? 0;
        } catch (err) {
            this.$body.innerHTML = `<tr><td colspan="${this.columns.length}" class="text-danger text-center">Failed to load data</td></tr>`;
        } finally {
            this.$loading?.classList.add('d-none');
        }
    }

    _renderBody(rows) {
        if (!rows.length) {
            this.$body.innerHTML = `<tr><td colspan="${this.columns.length}" class="text-center text-muted py-4">No records found</td></tr>`;
            return;
        }

        this.$body.innerHTML = rows.map(row =>
            '<tr>' + this.columns.map(col => {
                const val = row[col.key];
                const content = col.render ? col.render(val, row) : SortableTable.esc(val ?? '–');
                const cls = col.className || '';
                return `<td class="${cls}">${content}</td>`;
            }).join('') + '</tr>'
        ).join('');
    }

    _renderPagination(page, totalPages, total) {
        if (!this.$pagination || totalPages <= 1) {
            if (this.$pagination) this.$pagination.innerHTML = '';
            return;
        }

        let html = '';
        html += `<li class="page-item ${page <= 1 ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-page="${page - 1}">&laquo;</a></li>`;

        const start = Math.max(1, page - 2);
        const end   = Math.min(totalPages, page + 2);

        if (start > 1) html += `<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`;
        if (start > 2) html += `<li class="page-item disabled"><span class="page-link">&hellip;</span></li>`;

        for (let i = start; i <= end; i++) {
            html += `<li class="page-item ${i === page ? 'active' : ''}">
                        <a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
        }

        if (end < totalPages - 1) html += `<li class="page-item disabled"><span class="page-link">&hellip;</span></li>`;
        if (end < totalPages) html += `<li class="page-item"><a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a></li>`;

        html += `<li class="page-item ${page >= totalPages ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-page="${page + 1}">&raquo;</a></li>`;

        this.$pagination.innerHTML = html;
    }

    async _loadFilters() {
        try {
            const resp = await fetch(this.filtersUrl);
            const json = await resp.json();
            // Each key in json maps to a select element by convention:
            // e.g. json.carriers -> #filter-carrier, json.statuses -> #filter-status
            for (const [key, values] of Object.entries(json)) {
                // Try matching: key "carriers" -> id "filter-carrier" (strip trailing 's', add prefix)
                const singular = key.replace(/ies$/, 'y').replace(/ses$/, 's').replace(/s$/, '');
                const el = document.getElementById('filter-' + singular);
                if (el && Array.isArray(values)) {
                    values.forEach(v => {
                        if (v != null) {
                            el.insertAdjacentHTML('beforeend',
                                `<option value="${SortableTable.esc(v)}">${SortableTable.esc(v)}</option>`);
                        }
                    });
                }
            }
        } catch (err) {
            // Filters fail gracefully
        }
    }

    // ── Static helpers ───────────────────────────────────────────
    static esc(s) {
        if (s == null) return '';
        const d = document.createElement('div');
        d.textContent = String(s);
        return d.innerHTML;
    }

    static fmt$(n) {
        if (n == null) return '$0.00';
        return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    static fmtPct(n) {
        if (n == null) return '0%';
        return (Number(n) * 100).toFixed(1) + '%';
    }
}
