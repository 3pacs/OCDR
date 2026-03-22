import React, { useState, useEffect } from "react";
import { Card, Col, Row, Spinner, Alert, Badge, Table } from "react-bootstrap";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import api from "../services/api";

function PSMADashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get("/analytics/psma")
      .then(res => setData(res.data))
      .catch(() => setError("Could not load PSMA data"))
      .finally(() => setLoading(false));
  }, []);

  const fmt = (v) => "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

  if (loading) return <div className="text-center mt-5"><Spinner animation="border" /> Loading PSMA data...</div>;

  const psma = data?.psma || {};
  const std = data?.standard_pet || {};
  const multiplier = std.avg_payment > 0 ? (psma.avg_payment / std.avg_payment).toFixed(1) : "N/A";

  return (
    <>
      <h2 className="mb-4">PSMA PET Tracking</h2>
      {error && <Alert variant="warning">{error}</Alert>}

      <Row className="g-3 mb-4">
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">PSMA Scans</Card.Title>
              <div className="fs-3 fw-bold text-primary">{psma.count || 0}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">PSMA Revenue</Card.Title>
              <div className="fs-3 fw-bold text-success">{fmt(psma.revenue || 0)}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Avg PSMA Payment</Card.Title>
              <div className="fs-3 fw-bold text-info">{fmt(psma.avg_payment || 0)}</div>
              <small className="text-muted">vs {fmt(std.avg_payment || 0)} standard PET</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">PSMA Premium</Card.Title>
              <div className="fs-3 fw-bold text-warning">{multiplier}x</div>
              <small className="text-muted">vs standard PET reimbursement</small>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-3 mb-4">
        <Col md={6}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title>PSMA vs Standard PET</Card.Title>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={[
                  { name: "PSMA PET", scans: psma.count || 0, revenue: psma.revenue || 0 },
                  { name: "Standard PET", scans: std.count || 0, revenue: std.revenue || 0 },
                ]}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis tickFormatter={(v) => `$${(v/1000).toFixed(0)}K`} />
                  <Tooltip formatter={(v, name) => name === "revenue" ? fmt(v) : v} />
                  <Bar dataKey="revenue" fill="#0d6efd" name="Revenue" />
                </BarChart>
              </ResponsiveContainer>
            </Card.Body>
          </Card>
        </Col>
        <Col md={6}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title>PSMA by Year</Card.Title>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={data?.by_year || []}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="year" />
                  <YAxis yAxisId="left" tickFormatter={(v) => `$${(v/1000).toFixed(0)}K`} />
                  <YAxis yAxisId="right" orientation="right" />
                  <Tooltip formatter={(v, name) => name === "revenue" ? fmt(v) : v} />
                  <Bar yAxisId="left" dataKey="revenue" fill="#198754" name="Revenue" />
                  <Bar yAxisId="right" dataKey="count" fill="#ffc107" name="Scans" />
                </BarChart>
              </ResponsiveContainer>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {data?.by_physician?.length > 0 && (
        <Card className="border-0 shadow-sm">
          <Card.Body>
            <Card.Title>Top Referring Physicians (PSMA)</Card.Title>
            <Table striped hover responsive size="sm">
              <thead>
                <tr>
                  <th>Physician</th>
                  <th className="text-end">Scans</th>
                  <th className="text-end">Revenue</th>
                  <th className="text-end">Avg/Scan</th>
                </tr>
              </thead>
              <tbody>
                {data.by_physician.map((p, i) => (
                  <tr key={i}>
                    <td>{p.name}</td>
                    <td className="text-end">{p.count}</td>
                    <td className="text-end">{fmt(p.revenue)}</td>
                    <td className="text-end">{p.count > 0 ? fmt(p.revenue / p.count) : "$0"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card.Body>
        </Card>
      )}
    </>
  );
}

export default PSMADashboard;
