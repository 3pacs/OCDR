import React, { useState, useEffect } from "react";
import { Card, Table, Spinner, Alert, Row, Col, Form, Badge } from "react-bootstrap";
import api from "../services/api";

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

  const formatMoney = (v) => {
    if (v == null) return "--";
    const prefix = v < 0 ? "-$" : "$";
    return prefix + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2 });
  };

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
            <Table striped hover responsive size="sm">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Date</th>
                  <th>Carrier</th>
                  <th>Modality</th>
                  <th className="text-end">Paid</th>
                  <th className="text-end">Expected</th>
                  <th className="text-end">Variance</th>
                  <th className="text-end">%</th>
                  <th>Flags</th>
                </tr>
              </thead>
              <tbody>
                {claims.map((c) => (
                  <tr key={c.id}>
                    <td>{c.patient_name}</td>
                    <td>{c.service_date}</td>
                    <td>{c.insurance_carrier}</td>
                    <td>{c.modality}</td>
                    <td className="text-end">{formatMoney(c.total_payment)}</td>
                    <td className="text-end">{formatMoney(c.expected_rate)}</td>
                    <td className="text-end text-danger">{formatMoney(c.variance)}</td>
                    <td className="text-end">{c.variance_pct}%</td>
                    <td>
                      {c.gado_used && <Badge bg="info" className="me-1">GADO</Badge>}
                      {c.is_psma && <Badge bg="purple" className="me-1">PSMA</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}

          <div className="d-flex justify-content-between mt-3">
            <button className="btn btn-sm btn-outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="text-muted small">Page {page}</span>
            <button className="btn btn-sm btn-outline-secondary" disabled={claims.length < 50} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </Card.Body>
      </Card>
    </>
  );
}

export default Underpayments;
