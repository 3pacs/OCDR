import React, { useState, useCallback } from "react";
import { Card, Col, Row, Spinner, Alert, Badge, Table, Form, InputGroup, Button } from "react-bootstrap";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import api from "../services/api";

const STATUS_COLORS = {
  PAID: "success",
  UNPAID: "danger",
  UNDERPAID: "warning",
  DENIED: "danger",
  NO_CHARGE: "secondary",
};

const STATUS_LABELS = {
  PAID: "Paid",
  UNPAID: "Unpaid",
  UNDERPAID: "Underpaid",
  DENIED: "Denied",
  NO_CHARGE: "No Charge",
};

function PatientLookup() {
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [detail, setDetail] = useState(null);
  const [searching, setSearching] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState(null);

  const doSearch = useCallback(async () => {
    if (query.length < 2) return;
    setSearching(true);
    setError(null);
    setDetail(null);
    setSelectedPatient(null);
    try {
      const res = await api.get(`/analytics/patients/search?q=${encodeURIComponent(query)}`);
      setSearchResults(res.data.patients);
    } catch (err) {
      setError("Search failed");
    } finally {
      setSearching(false);
    }
  }, [query]);

  const selectPatient = async (name) => {
    setSelectedPatient(name);
    setLoadingDetail(true);
    try {
      const res = await api.get(`/analytics/patients/${encodeURIComponent(name)}/detail`);
      setDetail(res.data);
    } catch (err) {
      setError("Could not load patient details");
    } finally {
      setLoadingDetail(false);
    }
  };

  const fmt = (v) => "$" + (v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const handleKeyDown = (e) => { if (e.key === "Enter") doSearch(); };

  const summary = detail?.summary;
  const visits = detail?.visits || [];

  // Build chart data from visits
  const statusCounts = {};
  visits.forEach((v) => {
    statusCounts[v.status] = (statusCounts[v.status] || 0) + 1;
  });
  const chartData = Object.entries(statusCounts).map(([status, count]) => ({
    status: STATUS_LABELS[status] || status,
    count,
  }));

  return (
    <>
      <h2 className="mb-4">Patient Lookup</h2>

      <Card className="border-0 shadow-sm mb-4">
        <Card.Body>
          <InputGroup>
            <Form.Control
              type="text"
              placeholder="Search by name, chart ID, patient ID, or DOB (e.g., SMITH or 9125 or 03/15/1960)..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              size="lg"
              autoFocus
            />
            <Button variant="primary" onClick={doSearch} disabled={query.length < 2 || searching}>
              {searching ? <Spinner animation="border" size="sm" /> : "Search"}
            </Button>
          </InputGroup>
        </Card.Body>
      </Card>

      {error && <Alert variant="warning">{error}</Alert>}

      {searchResults && !selectedPatient && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            <Card.Title>
              {searchResults.length} patient{searchResults.length !== 1 ? "s" : ""} found
            </Card.Title>
            {searchResults.length === 0 ? (
              <Alert variant="info">No patients found. Try a partial name, chart ID, patient ID, or date of birth (MM/DD/YYYY).</Alert>
            ) : (
              <Table striped hover responsive>
                <thead>
                  <tr>
                    <th>Patient Name</th>
                    <th>Chart ID</th>
                    <th>DOB</th>
                    <th>Insurance</th>
                    <th className="text-end">Visits</th>
                    <th className="text-end">Total Paid</th>
                    <th className="text-end">Unpaid</th>
                    <th>Last Visit</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {searchResults.map((p, i) => (
                    <tr key={i} style={{ cursor: "pointer" }} onClick={() => selectPatient(p.patient_name)}>
                      <td><strong>{p.patient_name}</strong></td>
                      <td>{p.patient_id || "—"}</td>
                      <td>{p.birth_date || "—"}</td>
                      <td>{p.insurance}</td>
                      <td className="text-end">{p.visit_count}</td>
                      <td className="text-end">{fmt(p.total_paid)}</td>
                      <td className="text-end">
                        {p.unpaid_count > 0
                          ? <Badge bg="danger">{p.unpaid_count}</Badge>
                          : <Badge bg="success">0</Badge>
                        }
                      </td>
                      <td>{p.last_visit}</td>
                      <td><small className="text-primary">View &rarr;</small></td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card.Body>
        </Card>
      )}

      {loadingDetail && (
        <div className="text-center mt-4"><Spinner animation="border" /> Loading patient history...</div>
      )}

      {summary && (
        <>
          {/* Patient header */}
          <Card className="border-0 shadow-sm mb-4">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start">
                <div>
                  <h3 className="mb-1">{summary.patient_name}</h3>
                  <div className="text-muted">
                    Chart ID: <strong>{summary.patient_id || "—"}</strong>
                    {summary.topaz_id && <> | Topaz ID: <strong>{summary.topaz_id}</strong></>}
                    {summary.birth_date && <> | DOB: <strong>{summary.birth_date}</strong></>}
                    {" | "}Insurance: <strong>{summary.carriers?.join(", ")}</strong>
                  </div>
                </div>
                <Button variant="outline-secondary" size="sm" onClick={() => { setSelectedPatient(null); setDetail(null); }}>
                  &larr; Back to search
                </Button>
              </div>
            </Card.Body>
          </Card>

          {/* KPI cards */}
          <Row className="g-3 mb-4">
            <Col md={2}>
              <Card className="border-0 shadow-sm h-100">
                <Card.Body className="text-center">
                  <div className="text-muted small text-uppercase">Visits</div>
                  <div className="fs-3 fw-bold text-primary">{summary.total_visits}</div>
                  <small className="text-muted">{summary.first_visit} — {summary.last_visit}</small>
                </Card.Body>
              </Card>
            </Col>
            <Col md={2}>
              <Card className="border-0 shadow-sm h-100">
                <Card.Body className="text-center">
                  <div className="text-muted small text-uppercase">Total Paid</div>
                  <div className="fs-3 fw-bold text-success">{fmt(summary.total_paid)}</div>
                </Card.Body>
              </Card>
            </Col>
            <Col md={2}>
              <Card className="border-0 shadow-sm h-100">
                <Card.Body className="text-center">
                  <div className="text-muted small text-uppercase">Expected</div>
                  <div className="fs-3 fw-bold">{fmt(summary.total_expected)}</div>
                </Card.Body>
              </Card>
            </Col>
            <Col md={2}>
              <Card className="border-0 shadow-sm h-100">
                <Card.Body className="text-center">
                  <div className="text-muted small text-uppercase">Collection Rate</div>
                  <div className={`fs-3 fw-bold ${summary.collection_rate >= 80 ? "text-success" : summary.collection_rate >= 50 ? "text-warning" : "text-danger"}`}>
                    {summary.collection_rate}%
                  </div>
                </Card.Body>
              </Card>
            </Col>
            <Col md={2}>
              <Card className="border-0 shadow-sm h-100">
                <Card.Body className="text-center">
                  <div className="text-muted small text-uppercase">Unpaid</div>
                  <div className={`fs-3 fw-bold ${summary.total_unpaid > 0 ? "text-danger" : "text-success"}`}>
                    {summary.total_unpaid}
                  </div>
                </Card.Body>
              </Card>
            </Col>
            <Col md={2}>
              <Card className="border-0 shadow-sm h-100">
                <Card.Body className="text-center">
                  <div className="text-muted small text-uppercase">Underpaid</div>
                  <div className={`fs-3 fw-bold ${summary.total_underpaid > 0 ? "text-warning" : "text-success"}`}>
                    {summary.total_underpaid}
                  </div>
                </Card.Body>
              </Card>
            </Col>
          </Row>

          {/* Status breakdown chart */}
          {chartData.length > 0 && (
            <Row className="g-3 mb-4">
              <Col md={4}>
                <Card className="border-0 shadow-sm h-100">
                  <Card.Body>
                    <Card.Title>Visit Status Breakdown</Card.Title>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="status" />
                        <YAxis />
                        <Tooltip />
                        <Bar dataKey="count" fill="#0d6efd" />
                      </BarChart>
                    </ResponsiveContainer>
                  </Card.Body>
                </Card>
              </Col>
              <Col md={8}>
                <Card className="border-0 shadow-sm h-100">
                  <Card.Body>
                    <Card.Title>Legend</Card.Title>
                    <div className="mt-2">
                      <Badge bg="success" className="me-2 mb-2 p-2">PAID</Badge> Services fully paid by insurance<br/>
                      <Badge bg="danger" className="me-2 mb-2 p-2">UNPAID</Badge> $0 received — needs follow-up or filing<br/>
                      <Badge bg="warning" className="me-2 mb-2 p-2">UNDERPAID</Badge> Paid less than 80% of expected rate<br/>
                      <Badge bg="danger" className="me-2 mb-2 p-2">DENIED</Badge> Insurance denied the claim — see reason<br/>
                      <Badge bg="secondary" className="me-2 mb-2 p-2">NO CHARGE</Badge> No expected payment (comp, charity, etc.)
                    </div>
                  </Card.Body>
                </Card>
              </Col>
            </Row>
          )}

          {/* Visit detail table */}
          <Card className="border-0 shadow-sm">
            <Card.Body>
              <Card.Title>All Visits ({visits.length})</Card.Title>
              <Table striped hover responsive size="sm">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Modality</th>
                    <th>Scan</th>
                    <th>Doctor</th>
                    <th>Insurance</th>
                    <th className="text-end">Primary</th>
                    <th className="text-end">Secondary</th>
                    <th className="text-end">Total</th>
                    <th className="text-end">Expected</th>
                    <th>Status</th>
                    <th>Why</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visits.map((v, i) => (
                    <tr key={i} className={v.status === "DENIED" || v.status === "UNPAID" ? "table-danger" : v.status === "UNDERPAID" ? "table-warning" : ""}>
                      <td>{v.service_date}</td>
                      <td>{v.modality}</td>
                      <td>
                        {v.scan_type}
                        {v.gado_used && <Badge bg="info" className="ms-1">Gado</Badge>}
                      </td>
                      <td className="small">{v.referring_doctor}</td>
                      <td>{v.insurance_carrier}</td>
                      <td className="text-end">{fmt(v.primary_payment)}</td>
                      <td className="text-end">
                        {fmt(v.secondary_payment)}
                        {v.missing_secondary && <Badge bg="warning" className="ms-1" title="Expected secondary payment missing">!</Badge>}
                      </td>
                      <td className="text-end fw-bold">{fmt(v.total_payment)}</td>
                      <td className="text-end text-muted">{fmt(v.expected_payment)}</td>
                      <td>
                        <Badge bg={STATUS_COLORS[v.status] || "secondary"}>
                          {STATUS_LABELS[v.status] || v.status}
                        </Badge>
                      </td>
                      <td className="small" style={{ maxWidth: 200 }}>
                        {v.reason || "—"}
                        {v.denial_reason_code && <div><Badge bg="dark" className="mt-1">{v.denial_reason_code}</Badge></div>}
                      </td>
                      <td className="small" style={{ maxWidth: 150 }}>
                        {v.action && <Badge bg="outline-dark" className="border">{v.action}</Badge>}
                        {v.fix && <div className="text-muted mt-1" style={{ fontSize: "0.75rem" }}>{v.fix}</div>}
                        {v.appeal_deadline && <div className="text-danger mt-1" style={{ fontSize: "0.75rem" }}>Deadline: {v.appeal_deadline}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card.Body>
          </Card>
        </>
      )}
    </>
  );
}

export default PatientLookup;
