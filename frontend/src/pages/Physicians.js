import React, { useState, useEffect } from "react";
import { Card, Col, Row, Spinner, Alert, Table, Badge } from "react-bootstrap";
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import api from "../services/api";

function Physicians() {
  const [physicians, setPhysicians] = useState(null);
  const [totalRevenue, setTotalRevenue] = useState(0);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get("/analytics/physicians?limit=50")
      .then(res => { setPhysicians(res.data.physicians); setTotalRevenue(res.data.total_revenue); })
      .catch(() => setError("Could not load physician data"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedDoc) { setDetail(null); return; }
    api.get(`/analytics/physicians/${encodeURIComponent(selectedDoc)}`)
      .then(res => setDetail(res.data))
      .catch(() => setDetail(null));
  }, [selectedDoc]);

  const fmt = (v) => "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

  if (loading) return <div className="text-center mt-5"><Spinner animation="border" /> Loading physician data...</div>;

  return (
    <>
      <h2 className="mb-4">Physician Analytics</h2>
      {error && <Alert variant="warning">{error}</Alert>}

      <Row className="g-3 mb-4">
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Total Physicians</Card.Title>
              <div className="fs-3 fw-bold text-primary">{physicians?.length || 0}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Total Revenue</Card.Title>
              <div className="fs-3 fw-bold text-success">{fmt(totalRevenue)}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Top 10 Share</Card.Title>
              <div className="fs-3 fw-bold text-info">
                {physicians ? (physicians.slice(0, 10).reduce((s, p) => s + p.revenue_share_pct, 0)).toFixed(1) : 0}%
              </div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Avg Revenue/Doc</Card.Title>
              <div className="fs-3 fw-bold">{physicians?.length ? fmt(totalRevenue / physicians.length) : "$0"}</div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {physicians?.length > 0 && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            <Card.Title>Top 15 by Revenue</Card.Title>
            <ResponsiveContainer width="100%" height={400}>
              <BarChart data={physicians.slice(0, 15)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tickFormatter={(v) => `$${(v/1000).toFixed(0)}K`} />
                <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => fmt(v)} />
                <Bar dataKey="total_revenue" fill="#0d6efd" name="Revenue" />
              </BarChart>
            </ResponsiveContainer>
          </Card.Body>
        </Card>
      )}

      <Card className="border-0 shadow-sm mb-4">
        <Card.Body>
          <Card.Title>All Physicians</Card.Title>
          <Table striped hover responsive size="sm">
            <thead>
              <tr>
                <th>#</th>
                <th>Physician</th>
                <th className="text-end">Revenue</th>
                <th className="text-end">Share</th>
                <th className="text-end">Claims</th>
                <th className="text-end">Avg Payment</th>
                <th className="text-end">Carriers</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {physicians?.map((p, i) => (
                <tr key={i} style={{ cursor: "pointer" }} onClick={() => setSelectedDoc(p.name)}
                    className={selectedDoc === p.name ? "table-primary" : ""}>
                  <td>{i + 1}</td>
                  <td><strong>{p.name}</strong></td>
                  <td className="text-end">{fmt(p.total_revenue)}</td>
                  <td className="text-end"><Badge bg="info">{p.revenue_share_pct}%</Badge></td>
                  <td className="text-end">{p.total_claims.toLocaleString()}</td>
                  <td className="text-end">{fmt(p.avg_payment)}</td>
                  <td className="text-end">{p.carrier_count}</td>
                  <td><small className="text-primary">Details &rarr;</small></td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card.Body>
      </Card>

      {detail && (
        <>
          <h4 className="mt-4 mb-3">{detail.name} — Detail</h4>
          <Row className="g-3 mb-4">
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>By Modality</Card.Title>
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={detail.by_modality} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" tickFormatter={(v) => fmt(v)} />
                      <YAxis type="category" dataKey="modality" width={60} />
                      <Tooltip formatter={(v) => fmt(v)} />
                      <Bar dataKey="revenue" fill="#198754" />
                    </BarChart>
                  </ResponsiveContainer>
                </Card.Body>
              </Card>
            </Col>
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>By Carrier</Card.Title>
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={detail.by_carrier.slice(0, 8)} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" tickFormatter={(v) => fmt(v)} />
                      <YAxis type="category" dataKey="carrier" width={80} />
                      <Tooltip formatter={(v) => fmt(v)} />
                      <Bar dataKey="revenue" fill="#6f42c1" />
                    </BarChart>
                  </ResponsiveContainer>
                </Card.Body>
              </Card>
            </Col>
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>Gado Usage</Card.Title>
                  <div className="fs-1 fw-bold text-center mt-4">{detail.gado_pct}%</div>
                  <div className="text-center text-muted">{detail.gado_claims} of {detail.total_claims} claims use Gado</div>
                </Card.Body>
              </Card>
            </Col>
          </Row>
          <Card className="border-0 shadow-sm mb-4">
            <Card.Body>
              <Card.Title>Monthly Revenue Trend</Card.Title>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={detail.monthly}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" angle={-45} textAnchor="end" height={60} tick={{ fontSize: 11 }} />
                  <YAxis tickFormatter={(v) => `$${(v/1000).toFixed(0)}K`} />
                  <Tooltip formatter={(v) => fmt(v)} />
                  <Line type="monotone" dataKey="revenue" stroke="#0d6efd" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </Card.Body>
          </Card>
        </>
      )}
    </>
  );
}

export default Physicians;
