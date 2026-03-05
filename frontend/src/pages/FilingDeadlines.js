import React, { useState, useEffect } from "react";
import { Card, Table, Spinner, Alert, Row, Col, Form, Badge } from "react-bootstrap";
import api from "../services/api";

function FilingDeadlines() {
  const [alerts, setAlerts] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.get("/filing-deadlines/alerts").then((r) => setAlerts(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    const params = { page, per_page: 50 };
    if (statusFilter) params.status = statusFilter;

    api.get("/filing-deadlines", { params })
      .then((r) => setItems(r.data.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [statusFilter, page]);

  const statusBadge = (status) => {
    const map = {
      PAST_DEADLINE: "danger",
      WARNING_30DAY: "warning",
      SAFE: "success",
    };
    return <Badge bg={map[status] || "secondary"}>{status}</Badge>;
  };

  return (
    <>
      <h2 className="mb-4">Filing Deadline Tracker (F-06)</h2>

      {alerts && (
        <Row className="g-3 mb-4">
          <Col md={4}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Past Deadline</div>
                <div className="fs-3 fw-bold text-danger">{alerts.past_deadline_count}</div>
                <small className="text-muted">Expired &mdash; may not be recoverable</small>
              </Card.Body>
            </Card>
          </Col>
          <Col md={4}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Warning (30 days)</div>
                <div className="fs-3 fw-bold text-warning">{alerts.warning_count}</div>
                <small className="text-muted">Act now to avoid expiration</small>
              </Card.Body>
            </Card>
          </Col>
          <Col md={4}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Total Unpaid</div>
                <div className="fs-3 fw-bold">
                  {alerts.past_deadline_count + alerts.warning_count +
                    (items.length > 0 ? items.filter(i => i.status === "SAFE").length : 0)}
                </div>
                <small className="text-muted">Claims with $0 payment</small>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}

      <Card className="border-0 shadow-sm">
        <Card.Body>
          <Row className="mb-3">
            <Col md={4}>
              <Form.Select
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              >
                <option value="">All Statuses</option>
                <option value="PAST_DEADLINE">Past Deadline</option>
                <option value="WARNING_30DAY">Warning (30 days)</option>
                <option value="SAFE">Safe</option>
              </Form.Select>
            </Col>
          </Row>

          {loading ? (
            <div className="text-center py-4"><Spinner animation="border" /></div>
          ) : items.length === 0 ? (
            <Alert variant="info">No unpaid claims found. Import data first.</Alert>
          ) : (
            <Table striped hover responsive size="sm">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Patient</th>
                  <th>Service Date</th>
                  <th>Carrier</th>
                  <th>Modality</th>
                  <th>Scan</th>
                  <th>Filing Deadline</th>
                  <th>Days Left</th>
                  <th>Doctor</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>{statusBadge(item.status)}</td>
                    <td>{item.patient_name}</td>
                    <td>{item.service_date}</td>
                    <td>{item.insurance_carrier}</td>
                    <td>{item.modality}</td>
                    <td>{item.scan_type}</td>
                    <td>{item.filing_deadline}</td>
                    <td className={item.days_remaining < 0 ? "text-danger fw-bold" : item.days_remaining <= 30 ? "text-warning" : ""}>
                      {item.days_remaining}
                    </td>
                    <td>{item.referring_doctor}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}

          <div className="d-flex justify-content-between mt-3">
            <button className="btn btn-sm btn-outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="text-muted small">Page {page}</span>
            <button className="btn btn-sm btn-outline-secondary" disabled={items.length < 50} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </Card.Body>
      </Card>
    </>
  );
}

export default FilingDeadlines;
