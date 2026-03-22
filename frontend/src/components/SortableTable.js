import React, { useState, useMemo } from "react";
import { Table, Form } from "react-bootstrap";

/**
 * SortableTable — drop-in replacement for React Bootstrap Table with:
 * - Click-to-sort on any column header
 * - Optional per-column text filter row
 *
 * Props:
 *   columns: [{ key, label, className?, render?, sortable?, filterable?, filterPlaceholder? }]
 *   data: array of row objects
 *   rowKey: string key or function(row,i) => unique key
 *   rowClassName?: function(row) => className string
 *   onRowClick?: function(row) => void
 *   selectable?: boolean  (shows checkbox column)
 *   selected?: Set of ids
 *   onToggleSelect?: function(id) => void
 *   onToggleAll?: function() => void
 *   size?: "sm" | undefined
 *   hover?: boolean
 *   striped?: boolean
 *   extraHead?: ReactNode (placed in thead before filter row)
 */
export default function SortableTable({
  columns,
  data,
  rowKey = "id",
  rowClassName,
  onRowClick,
  selectable,
  selected,
  onToggleSelect,
  onToggleAll,
  size = "sm",
  hover = true,
  striped = true,
}) {
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState("asc");
  const [filters, setFilters] = useState({});

  const hasFilters = columns.some((c) => c.filterable);

  const handleSort = (key) => {
    if (sortCol === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(key);
      setSortDir("asc");
    }
  };

  const handleFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const filteredData = useMemo(() => {
    let result = data;
    for (const [key, val] of Object.entries(filters)) {
      if (!val) continue;
      const lower = val.toLowerCase();
      result = result.filter((row) => {
        const cell = row[key];
        if (cell == null) return false;
        return String(cell).toLowerCase().includes(lower);
      });
    }
    return result;
  }, [data, filters]);

  const sortedData = useMemo(() => {
    if (!sortCol) return filteredData;
    const col = columns.find((c) => c.key === sortCol);
    if (col && col.sortable === false) return filteredData;

    return [...filteredData].sort((a, b) => {
      let va = a[sortCol];
      let vb = b[sortCol];
      // Handle nulls
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      // Numeric sort if both are numbers
      if (typeof va === "number" && typeof vb === "number") {
        return sortDir === "asc" ? va - vb : vb - va;
      }
      // String sort
      va = String(va).toLowerCase();
      vb = String(vb).toLowerCase();
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [filteredData, sortCol, sortDir, columns]);

  const getKey = (row, i) =>
    typeof rowKey === "function" ? rowKey(row, i) : row[rowKey];

  const sortIcon = (key) => {
    if (sortCol !== key) return <span className="text-muted ms-1" style={{ fontSize: "0.7em" }}>&#x25B4;&#x25BE;</span>;
    return sortDir === "asc"
      ? <span className="ms-1" style={{ fontSize: "0.7em" }}>&#x25B4;</span>
      : <span className="ms-1" style={{ fontSize: "0.7em" }}>&#x25BE;</span>;
  };

  return (
    <Table striped={striped} hover={hover} responsive size={size}>
      <thead>
        <tr>
          {selectable && (
            <th style={{ width: 32 }}>
              <Form.Check
                type="checkbox"
                onChange={onToggleAll}
                checked={selected?.size === data.length && data.length > 0}
              />
            </th>
          )}
          {columns.map((col) => (
            <th
              key={col.key}
              className={`${col.className || ""} ${col.sortable !== false ? "user-select-none" : ""}`}
              style={col.sortable !== false ? { cursor: "pointer" } : undefined}
              onClick={col.sortable !== false ? () => handleSort(col.key) : undefined}
            >
              {col.label}
              {col.sortable !== false && sortIcon(col.key)}
            </th>
          ))}
        </tr>
        {hasFilters && (
          <tr>
            {selectable && <th />}
            {columns.map((col) => (
              <th key={col.key} className="p-1">
                {col.filterable ? (
                  <Form.Control
                    size="sm"
                    placeholder={col.filterPlaceholder || "Filter..."}
                    value={filters[col.key] || ""}
                    onChange={(e) => handleFilter(col.key, e.target.value)}
                    style={{ fontSize: "0.75rem" }}
                  />
                ) : null}
              </th>
            ))}
          </tr>
        )}
      </thead>
      <tbody>
        {sortedData.map((row, i) => (
          <tr
            key={getKey(row, i)}
            className={rowClassName ? rowClassName(row) : undefined}
            style={onRowClick ? { cursor: "pointer" } : undefined}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
          >
            {selectable && (
              <td onClick={(e) => e.stopPropagation()}>
                <Form.Check
                  type="checkbox"
                  checked={selected?.has(row[typeof rowKey === "function" ? "id" : rowKey])}
                  onChange={() => onToggleSelect?.(row[typeof rowKey === "function" ? "id" : rowKey])}
                />
              </td>
            )}
            {columns.map((col) => (
              <td key={col.key} className={col.className || ""}>
                {col.render ? col.render(row[col.key], row) : (row[col.key] ?? "--")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
