import React, { useState, useEffect } from "react";
import { Card, Spinner, Alert, Row, Col, Form, Badge, Button } from "react-bootstrap";
import api from "../services/api";
import SortableTable from "../components/SortableTable";
import { PatientLink } from "../components/PatientDrilldown";

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

  const columns = [
    { key: "status", label: "Status", render: (v) => statusBadge(v) },
    {
      key: "patient_name", label: "Patient", filterable: true, filterPlaceholder: "Name...",
      render: (v) => <PatientLink name={v}>{v}</PatientLink>,
    },
    { key: "service_date", label: "Service Date" },
    { key: "insurance_carrier", label: "Carrier", filterable: true },
    { key: "modality", label: "Modality" },
    { key: "scan_type", label: "Scan" },
    { key: "filing_deadline", label: "Filing Deadline" },
    {
      key: "days_remaining", label: "Days Left",
      render: (v) => (
        <span className={v < 0 ? "text-danger fw-bold" : v <= 30 ? "text-warning" : ""}>
          {v}
        </span>
      ),
    },
    { key: "referring_doctor", label: "Doctor" },
  ];

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
            <SortableTable columns={columns} data={items} rowKey="id" />
          )}

          <div className="d-flex justify-content-between mt-3">
            <Button size="sm" variant="outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <span className="text-muted small">Page {page}</span>
            <Button size="sm" variant="outline-secondary" disabled={items.length < 50} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </Card.Body>
      </Card>
    </>
  );
}

export default FilingDeadlines;
