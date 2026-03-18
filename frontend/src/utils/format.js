/**
 * Shared formatting utilities used across all pages.
 */

export const formatMoney = (v, decimals = 2) => {
  if (v == null) return "--";
  const prefix = v < 0 ? "-$" : "$";
  return prefix + Math.abs(v).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};

export const formatDate = (d) => {
  if (!d) return "--";
  return d;
};

export const formatPct = (v) => {
  if (v == null) return "--";
  return `${v}%`;
};
