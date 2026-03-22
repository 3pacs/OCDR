import React, { useState, useEffect } from "react";
import { Card, Col, Row, Spinner, Alert, Badge, Table, Form } from "react-bootstrap";
import api from "../services/api";

function Duplicates() {
  const [data, setData] = useState(null);
  const [showCap, setShowCap] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = (includeLegitimate) => {
    setLoading(true);
    api.get(`/analytics/duplicates?include_legitimate=${includeLegitimate}`)
      .then(res => setData(res.data))
      .catch(() => setError("Could not load duplicate data"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(showCap); }, [showCap]);

  const fmt = (v) => "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2 });

  if (loading && !data) return <div className="text-center mt-5"><Spinner animation="border" /> Scanning for duplicates...</div>;

  return (
    <>
      <h2 className="mb-4">Duplicate Claim Detector</h2>
      {error && <Alert variant="warning">{error}</Alert>}

      <Row className="g-3 mb-4">
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Duplicate Groups</Card.Title>
              <div className="fs-3 fw-bold text-danger">{data?.total_groups || 0}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Total Duplicate Records</Card.Title>
              <div className="fs-3 fw-bold text-warning">{data?.total_duplicate_records || 0}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">C.A.P Excluded</Card.Title>
              <div className="fs-3 fw-bold text-success">{data?.cap_excluded || 0}</div>
              <small className="text-muted">Legitimate multi-scan visits</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm d-flex align-items-center justify-content-center h-100">
            <Card.Body>
              <Form.Check
                type="switch"
                label="Show C.A.P exceptions"
                checked={showCap}
                onChange={(e) => setShowCap(e.target.checked)}
              />
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {data?.duplicate_groups?.length > 0 ? (
        <Card className="border-0 shadow-sm">
          <Card.Body>
            <Card.Title>Duplicate Groups</Card.Title>
            <Table striped hover responsive size="sm">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Service Date</th>
                  <th>Scan</th>
                  <th>Modality</th>
                  <th className="text-end">Count</th>
                  <th>Descriptions</th>
                  <th className="text-end">Payments</th>
                  <th>Type</th>
                </tr>
              </thead>
              <tbody>
                {data.duplicate_groups.map((g, i) => (
                  <tr key={i}>
                    <td><strong>{g.patient_name}</strong></td>
                    <td>{g.service_date}</td>
                    <td>{g.scan_type}</td>
                    <td>{g.modality}</td>
                    <td className="text-end"><Badge bg="danger">{g.count}</Badge></td>
                    <td>
                      {g.descriptions.map((d, j) => (
                        <div key={j} className="small">{d || "(empty)"}</div>
                      ))}
                    </td>
                    <td className="text-end">
                      {g.payments.map((p, j) => (
                        <div key={j} className="small">{fmt(p)}</div>
                      ))}
                    </td>
                    <td>
                      {g.is_cap_exception
                        ? <Badge bg="success">C.A.P</Badge>
                        : <Badge bg="warning">Review</Badge>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card.Body>
        </Card>
      ) : (
        <Alert variant="success">No duplicate claims found (excluding legitimate C.A.P multi-scan visits).</Alert>
      )}
    </>
  );
}

export default Duplicates;
