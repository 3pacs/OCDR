import React, { useState, useEffect } from "react";
import { Card, Col, Row, Spinner, Alert, Table } from "react-bootstrap";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import api from "../services/api";

function GadoDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get("/analytics/gado")
      .then(res => setData(res.data))
      .catch(() => setError("Could not load Gado data"))
      .finally(() => setLoading(false));
  }, []);

  const fmt = (v) => "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

  if (loading) return <div className="text-center mt-5"><Spinner animation="border" /> Loading Gado data...</div>;

  return (
    <>
      <h2 className="mb-4">Gadolinium Contrast Analytics</h2>
      {error && <Alert variant="warning">{error}</Alert>}

      <Row className="g-3 mb-4">
        <Col md={2}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Gado Claims</Card.Title>
              <div className="fs-3 fw-bold text-primary">{(data?.total_claims || 0).toLocaleString()}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={2}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Revenue</Card.Title>
              <div className="fs-3 fw-bold text-success">{fmt(data?.total_revenue || 0)}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={2}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Total Cost</Card.Title>
              <div className="fs-3 fw-bold text-danger">{fmt(data?.total_cost || 0)}</div>
              <small className="text-muted">${data?.cost_per_dose}/dose</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={2}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Margin</Card.Title>
              <div className="fs-3 fw-bold text-success">{fmt(data?.margin || 0)}</div>
              <small className="text-muted">{data?.margin_pct}% margin</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={2}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Revenue/$1 Cost</Card.Title>
              <div className="fs-3 fw-bold text-info">${data?.revenue_per_dollar_cost || 0}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={2}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Avg Payment</Card.Title>
              <div className="fs-3 fw-bold">{fmt(data?.avg_payment || 0)}</div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-3 mb-4">
        <Col md={6}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title>Revenue by Year</Card.Title>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={data?.by_year || []}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="year" />
                  <YAxis tickFormatter={(v) => `$${(v/1000).toFixed(0)}K`} />
                  <Tooltip formatter={(v) => fmt(v)} />
                  <Bar dataKey="revenue" fill="#198754" name="Revenue" />
                </BarChart>
              </ResponsiveContainer>
            </Card.Body>
          </Card>
        </Col>
        <Col md={6}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title>By Modality</Card.Title>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={data?.by_modality || []} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" tickFormatter={(v) => `$${(v/1000).toFixed(0)}K`} />
                  <YAxis type="category" dataKey="modality" width={60} />
                  <Tooltip formatter={(v) => fmt(v)} />
                  <Bar dataKey="revenue" fill="#0d6efd" name="Revenue" />
                </BarChart>
              </ResponsiveContainer>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {data?.by_physician?.length > 0 && (
        <Card className="border-0 shadow-sm">
          <Card.Body>
            <Card.Title>Top Physicians by Gado Volume</Card.Title>
            <Table striped hover responsive size="sm">
              <thead>
                <tr>
                  <th>Physician</th>
                  <th className="text-end">Gado Claims</th>
                  <th className="text-end">Revenue</th>
                  <th className="text-end">Avg/Claim</th>
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

export default GadoDashboard;
