/* OCDR — shared JS utilities */

/**
 * Generic fetch wrapper with JSON body.
 */
async function apiRequest(method, url, body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || res.statusText);
  }
  return res.json();
}

/**
 * Format a currency value.
 */
function formatCurrency(val) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val || 0);
}

/**
 * Format an ISO date string to locale.
 */
function formatDate(isoStr) {
  if (!isoStr) return "—";
  return new Date(isoStr).toLocaleDateString("en-US");
}

/**
 * Status badge HTML.
 */
function statusBadge(status) {
  const cls = `status-${status}`;
  return `<span class="badge ${cls}">${status}</span>`;
}
