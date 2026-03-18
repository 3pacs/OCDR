import React, { useState, useEffect } from "react";
import { Card, Spinner, Alert, Row, Col, Form, Badge, Button } from "react-bootstrap";
import api from "../services/api";
import { formatMoney } from "../utils/format";
import SortableTable from "../components/SortableTable";
import { PatientLink } from "../components/PatientDrilldown";

function Underpayments() {
  const [summary, setSummary] = useState(null);
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [carrier, setCarrier] = useState("");
  const [modality, setModality] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.get("/underpayments/summary").then((r) => setSummary(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    const params = { page, per_page: 50 };
    if (carrier) params.carrier = carrier;
    if (modality) params.modality = modality;

    api.get("/underpayments", { params })
      .then((r) => setClaims(r.data.underpaid_claims || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [carrier, modality, page]);

  const columns = [
    {
      key: "patient_name", label: "Patient", filterable: true, filterPlaceholder: "Name...",
      render: (v) => <PatientLink name={v}>{v}</PatientLink>,
    },
    { key: "service_date", label: "Date" },
    { key: "insurance_carrier", label: "Carrier", filterable: true },
    { key: "modality", label: "Modality" },
    { key: "total_payment", label: "Paid", className: "text-end", render: (v) => formatMoney(v) },
    { key: "expected_rate", label: "Expected", className: "text-end", render: (v) => formatMoney(v) },
    { key: "variance", label: "Variance", className: "text-end text-danger", render: (v) => formatMoney(v) },
    { key: "variance_pct", label: "%", className: "text-end", render: (v) => `${v}%` },
    {
      key: "gado_used", label: "Flags", sortable: false,
      render: (v, row) => (
        <>
          {v && <Badge bg="info" className="me-1">GADO</Badge>}
          {row.is_psma && <Badge bg="purple">PSMA</Badge>}
        </>
      ),
    },
  ];

  return (
    <>
      <h2 className="mb-4">Underpayment Detection (F-05)</h2>

      {summary && (
        <Row className="g-3 mb-4">
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Flagged Claims</div>
                <div className="fs-3 fw-bold text-danger">{summary.total_flagged?.toLocaleString()}</div>
                <small className="text-muted">{summary.flagged_pct}% of paid</small>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Total Variance</div>
                <div className="fs-3 fw-bold text-warning">{formatMoney(summary.total_variance)}</div>
                <small className="text-muted">vs. fee schedule</small>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Total Paid Claims</div>
                <div className="fs-3 fw-bold">{summary.total_paid_claims?.toLocaleString()}</div>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Worst Carrier</div>
                <div className="fs-5 fw-bold text-danger">
                  {summary.by_carrier?.[0]?.carrier ?? "--"}
                </div>
                <small className="text-muted">
                  {summary.by_carrier?.[0] ? `${summary.by_carrier[0].count} claims` : ""}
                </small>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}

      <Card className="border-0 shadow-sm">
        <Card.Body>
          <Row className="mb-3">
            <Col md={4}>
              <Form.Control
                placeholder="Filter by carrier..."
                value={carrier}
                onChange={(e) => { setCarrier(e.target.value.toUpperCase()); setPage(1); }}
              />
            </Col>
            <Col md={4}>
              <Form.Select value={modality} onChange={(e) => { setModality(e.target.value); setPage(1); }}>
                <option value="">All Modalities</option>
                <option value="CT">CT</option>
                <option value="HMRI">HMRI</option>
                <option value="PET">PET</option>
                <option value="BONE">BONE</option>
                <option value="OPEN">OPEN</option>
                <option value="DX">DX</option>
              </Form.Select>
            </Col>
          </Row>

          {loading ? (
            <div className="text-center py-4"><Spinner animation="border" /></div>
          ) : claims.length === 0 ? (
            <Alert variant="info">No underpaid claims found. Import data first.</Alert>
          ) : (
            <SortableTable columns={columns} data={claims} rowKey="id" />
          )}

          <div className="d-flex justify-content-between mt-3">
            <Button size="sm" variant="outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <span className="text-muted small">Page {page}</span>
            <Button size="sm" variant="outline-secondary" disabled={claims.length < 50} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </Card.Body>
      </Card>
    </>
  );
}

export default Underpayments;
