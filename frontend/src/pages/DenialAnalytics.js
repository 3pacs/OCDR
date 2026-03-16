import React, { useState, useEffect } from "react";
import { Card, Col, Row, Spinner, Alert, Badge, Table } from "react-bootstrap";
import {
  BarChart, Bar, LineChart, Line, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import api from "../services/api";

function DenialAnalytics() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get("/analytics/denial-analytics")
      .then(res => setData(res.data))
      .catch(() => setError("Could not load denial analytics"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-center mt-5"><Spinner animation="border" /> Loading denial analytics...</div>;

  return (
    <>
      <h2 className="mb-4">Denial Reason Analytics</h2>
      {error && <Alert variant="warning">{error}</Alert>}

      <Row className="g-3 mb-4">
        <Col md={4}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Total Denied</Card.Title>
              <div className="fs-3 fw-bold text-danger">{(data?.total_denied || 0).toLocaleString()}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={4}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Unique Reason Codes</Card.Title>
              <div className="fs-3 fw-bold text-primary">{data?.by_reason?.length || 0}</div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={4}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title className="text-muted small text-uppercase">Top Code Covers</Card.Title>
              <div className="fs-3 fw-bold text-info">
                {data?.by_reason?.length > 0 ? data.by_reason[0].cumulative_pct + "%" : "N/A"}
              </div>
              <small className="text-muted">of all denials ({data?.by_reason?.[0]?.code})</small>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {data?.by_reason?.length > 0 && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            <Card.Title>Pareto Chart — Denial Reasons (80/20)</Card.Title>
            <ResponsiveContainer width="100%" height={350}>
              <ComposedChart data={data.by_reason}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="code" />
                <YAxis yAxisId="left" />
                <YAxis yAxisId="right" orientation="right" domain={[0, 100]} unit="%" />
                <Tooltip />
                <Bar yAxisId="left" dataKey="count" fill="#dc3545" name="Count" />
                <Line yAxisId="right" type="monotone" dataKey="cumulative_pct" stroke="#0d6efd" strokeWidth={2} name="Cumulative %" dot={{ r: 3 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </Card.Body>
        </Card>
      )}

      <Row className="g-3 mb-4">
        <Col md={6}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title>Reason Code Details</Card.Title>
              <Table striped hover responsive size="sm">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Description</th>
                    <th className="text-end">Count</th>
                    <th>Action</th>
                    <th>Recoverable</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.by_reason?.map((r, i) => (
                    <tr key={i}>
                      <td><Badge bg="dark">{r.code}</Badge></td>
                      <td className="small">{r.description}</td>
                      <td className="text-end">{r.count}</td>
                      <td><small>{r.recommended_action}</small></td>
                      <td>{r.recoverable ? <Badge bg="success">Yes</Badge> : <Badge bg="secondary">No</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title>By Carrier</Card.Title>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={data?.by_carrier || []} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis type="category" dataKey="carrier" width={80} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#6f42c1" name="Denials" />
                </BarChart>
              </ResponsiveContainer>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body>
              <Card.Title>By Modality</Card.Title>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={data?.by_modality || []} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis type="category" dataKey="modality" width={60} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#fd7e14" name="Denials" />
                </BarChart>
              </ResponsiveContainer>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  );
}

export default DenialAnalytics;
