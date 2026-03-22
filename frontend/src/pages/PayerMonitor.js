import React, { useState, useEffect } from "react";
import { Card, Col, Row, Spinner, Alert, Badge, Table, Form } from "react-bootstrap";
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import api from "../services/api";

function PayerMonitor() {
  const [alerts, setAlerts] = useState(null);
  const [carriers, setCarriers] = useState(null);
  const [selectedCarrier, setSelectedCarrier] = useState(null);
  const [carrierDetail, setCarrierDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [alertRes, monitorRes] = await Promise.all([
          api.get("/analytics/payer-alerts"),
          api.get("/analytics/payer-monitor"),
        ]);
        setAlerts(alertRes.data);
        setCarriers(monitorRes.data.carriers);
      } catch (err) {
        setError("Could not load payer data");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  useEffect(() => {
    if (!selectedCarrier) { setCarrierDetail(null); return; }
    api.get(`/analytics/payer-monitor/${encodeURIComponent(selectedCarrier)}`)
      .then(res => setCarrierDetail(res.data))
      .catch(() => setCarrierDetail(null));
  }, [selectedCarrier]);

  const fmt = (v) => "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

  if (loading) return <div className="text-center mt-5"><Spinner animation="border" /> Loading payer data...</div>;

  return (
    <>
      <h2 className="mb-4">Payer Contract Monitor</h2>
      {error && <Alert variant="warning">{error}</Alert>}

      {alerts?.alerts?.length > 0 && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            <Card.Title>Active Alerts ({alerts.total})</Card.Title>
            {alerts.alerts.map((a, i) => (
              <Alert key={i} variant={a.severity === "RED" ? "danger" : "warning"} className="py-2 mb-2">
                <div className="d-flex justify-content-between align-items-center">
                  <div>
                    <Badge bg={a.severity === "RED" ? "danger" : "warning"} className="me-2">{a.severity}</Badge>
                    <strong>{a.carrier}</strong> {a.display_name && `(${a.display_name})`}
                  </div>
                  <div className="text-end small">
                    Revenue: {fmt(a.current_revenue)} vs {fmt(a.avg_prior_revenue)} avg
                    <Badge bg="dark" className="ms-2">-{a.revenue_drop_pct}%</Badge>
                  </div>
                </div>
              </Alert>
            ))}
          </Card.Body>
        </Card>
      )}

      <Card className="border-0 shadow-sm mb-4">
        <Card.Body>
          <Card.Title>All Carriers</Card.Title>
          <Table striped hover responsive size="sm">
            <thead>
              <tr>
                <th>Carrier</th>
                <th className="text-end">Revenue</th>
                <th className="text-end">Claims</th>
                <th className="text-end">Avg Payment</th>
                <th className="text-end">$0 Claims</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {carriers?.map((c, i) => (
                <tr key={i} style={{ cursor: "pointer" }} onClick={() => setSelectedCarrier(c.carrier)}
                    className={selectedCarrier === c.carrier ? "table-primary" : ""}>
                  <td><strong>{c.carrier}</strong></td>
                  <td className="text-end">{fmt(c.total_revenue)}</td>
                  <td className="text-end">{c.total_claims.toLocaleString()}</td>
                  <td className="text-end">{fmt(c.avg_payment)}</td>
                  <td className="text-end">
                    {c.zero_pay_count} <small className="text-muted">({c.zero_pay_pct}%)</small>
                  </td>
                  <td><small className="text-primary">Details &rarr;</small></td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card.Body>
      </Card>

      {carrierDetail && (
        <Row className="g-3">
          <Col md={8}>
            <Card className="border-0 shadow-sm">
              <Card.Body>
                <Card.Title>{carrierDetail.carrier} — Monthly Trend</Card.Title>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={carrierDetail.monthly}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="month" angle={-45} textAnchor="end" height={60} tick={{ fontSize: 11 }} />
                    <YAxis tickFormatter={(v) => `$${(v/1000).toFixed(0)}K`} />
                    <Tooltip formatter={(v) => fmt(v)} />
                    <Line type="monotone" dataKey="revenue" stroke="#0d6efd" strokeWidth={2} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </Card.Body>
            </Card>
          </Col>
          <Col md={4}>
            <Card className="border-0 shadow-sm">
              <Card.Body>
                <Card.Title>By Modality</Card.Title>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={carrierDetail.by_modality} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tickFormatter={(v) => `$${(v/1000).toFixed(0)}K`} />
                    <YAxis type="category" dataKey="modality" width={60} />
                    <Tooltip formatter={(v) => fmt(v)} />
                    <Bar dataKey="revenue" fill="#198754" />
                  </BarChart>
                </ResponsiveContainer>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}
    </>
  );
}

export default PayerMonitor;
