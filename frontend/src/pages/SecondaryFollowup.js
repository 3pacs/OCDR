import React, { useState, useEffect, useCallback } from "react";
import {
  Card, Spinner, Alert, Row, Col, Form, Badge, Button,
  ButtonGroup, Table,
} from "react-bootstrap";
import { toast } from "react-toastify";
import api from "../services/api";
import { formatMoney } from "../utils/format";
import SortableTable from "../components/SortableTable";
import { PatientLink } from "../components/PatientDrilldown";

function SecondaryFollowup() {
  const [summary, setSummary] = useState(null);
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [carrier, setCarrier] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState(new Set());

  const loadSummary = useCallback(() => {
    api.get("/secondary-followup/summary").then((r) => setSummary(r.data)).catch(() => {});
  }, []);

  const loadClaims = useCallback(() => {
    setLoading(true);
    const params = { page, per_page: 50 };
    if (carrier) params.carrier = carrier;
    api.get("/secondary-followup", { params })
      .then((r) => {
        setClaims(r.data.claims || []);
        setTotal(r.data.total || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [carrier, page]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadClaims(); }, [loadClaims]);

  const statusBadge = (s) => {
    const map = {
      PENDING: "warning",
      BILLED: "info",
      RECEIVED: "success",
      WRITTEN_OFF: "secondary",
    };
    return <Badge bg={map[s] || "warning"}>{s || "PENDING"}</Badge>;
  };

  const priorityBadge = (p) => (
    <Badge bg={p === "HIGH" ? "danger" : "warning"}>{p}</Badge>
  );

  const handleMark = async (id, status) => {
    await api.post(`/secondary-followup/${id}/mark`, { status });
    toast.success(`Claim marked as ${status.toLowerCase()}`);
    loadClaims();
    loadSummary();
  };

  const handleBulkMark = async (status) => {
    if (selected.size === 0) return;
    await api.post("/secondary-followup/bulk-mark", {
      ids: Array.from(selected),
      status,
    });
    toast.success(`${selected.size} claims marked as ${status.toLowerCase()}`);
    setSelected(new Set());
    loadClaims();
    loadSummary();
  };

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === claims.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(claims.map((c) => c.id)));
    }
  };

  const columns = [
    {
      key: "patient_name", label: "Patient", filterable: true, filterPlaceholder: "Name...",
      render: (v) => <PatientLink name={v}>{v}</PatientLink>,
    },
    { key: "service_date", label: "Date" },
    { key: "insurance_carrier", label: "Carrier", filterable: true },
    { key: "modality", label: "Modality" },
    { key: "primary_payment", label: "Primary", className: "text-end", render: (v) => formatMoney(v) },
    { key: "estimated_secondary", label: "Est. Secondary", className: "text-end text-warning", render: (v) => formatMoney(v) },
    { key: "priority", label: "Priority", render: (v) => priorityBadge(v) },
    { key: "followup_status", label: "Status", render: (v) => statusBadge(v) },
    { key: "days_since_service", label: "Days" },
    {
      key: "id", label: "Actions", sortable: false,
      render: (v, row) => (
        <ButtonGroup size="sm">
          {row.followup_status === "PENDING" && (
            <Button variant="outline-info" size="sm" onClick={(e) => { e.stopPropagation(); handleMark(row.id, "BILLED"); }}>Billed</Button>
          )}
          {(row.followup_status === "PENDING" || row.followup_status === "BILLED") && (
            <Button variant="outline-success" size="sm" onClick={(e) => { e.stopPropagation(); handleMark(row.id, "RECEIVED"); }}>Received</Button>
          )}
          {row.followup_status !== "WRITTEN_OFF" && row.followup_status !== "RECEIVED" && (
            <Button variant="outline-secondary" size="sm" onClick={(e) => { e.stopPropagation(); handleMark(row.id, "WRITTEN_OFF"); }}>W/O</Button>
          )}
        </ButtonGroup>
      ),
    },
  ];

  return (
    <>
      <h2 className="mb-4">Secondary Insurance Follow-Up (F-07)</h2>

      {summary && (
        <Row className="g-3 mb-4">
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Missing Secondary</div>
                <div className="fs-3 fw-bold text-danger">{summary.total_claims?.toLocaleString()}</div>
                <small className="text-muted">claims with primary paid, no secondary</small>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Total Primary Paid</div>
                <div className="fs-3 fw-bold">{formatMoney(summary.total_primary_paid)}</div>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Est. Missing Secondary</div>
                <div className="fs-3 fw-bold text-warning">{formatMoney(summary.estimated_missing_secondary)}</div>
                <small className="text-muted">~33.5% of primary</small>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Carriers Affected</div>
                <div className="fs-3 fw-bold">{summary.by_carrier?.length || 0}</div>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}

      {summary?.by_carrier?.length > 0 && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            <h6>Breakdown by Carrier</h6>
            <Table striped size="sm" className="mb-0">
              <thead>
                <tr>
                  <th>Carrier</th>
                  <th className="text-end">Claims</th>
                  <th className="text-end">Primary Paid</th>
                  <th className="text-end">Est. Missing</th>
                </tr>
              </thead>
              <tbody>
                {summary.by_carrier.map((c) => (
                  <tr key={c.carrier}>
                    <td><strong>{c.carrier}</strong></td>
                    <td className="text-end">{c.count.toLocaleString()}</td>
                    <td className="text-end">{formatMoney(c.primary_total)}</td>
                    <td className="text-end text-warning">{formatMoney(c.estimated_secondary)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card.Body>
        </Card>
      )}

      <Card className="border-0 shadow-sm">
        <Card.Body>
          <Row className="mb-3 align-items-center">
            <Col md={3}>
              <Form.Control
                size="sm"
                placeholder="Filter by carrier..."
                value={carrier}
                onChange={(e) => { setCarrier(e.target.value.toUpperCase()); setPage(1); }}
              />
            </Col>
            <Col md="auto" className="ms-auto">
              {selected.size > 0 && (
                <ButtonGroup size="sm">
                  <Button variant="info" onClick={() => handleBulkMark("BILLED")}>
                    Mark Billed ({selected.size})
                  </Button>
                  <Button variant="success" onClick={() => handleBulkMark("RECEIVED")}>
                    Mark Received ({selected.size})
                  </Button>
                  <Button variant="secondary" onClick={() => handleBulkMark("WRITTEN_OFF")}>
                    Write Off ({selected.size})
                  </Button>
                </ButtonGroup>
              )}
            </Col>
          </Row>

          {loading ? (
            <div className="text-center py-4"><Spinner animation="border" /></div>
          ) : claims.length === 0 ? (
            <Alert variant="info">No claims missing secondary payment found.</Alert>
          ) : (
            <SortableTable
              columns={columns}
              data={claims}
              rowKey="id"
              selectable
              selected={selected}
              onToggleSelect={toggleSelect}
              onToggleAll={toggleAll}
            />
          )}

          <div className="d-flex justify-content-between mt-3">
            <Button size="sm" variant="outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <span className="text-muted small">Page {page} &middot; {total} total</span>
            <Button size="sm" variant="outline-secondary" disabled={claims.length < 50} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </Card.Body>
      </Card>
    </>
  );
}

export default SecondaryFollowup;
