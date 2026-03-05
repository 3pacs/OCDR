import React, { useState, useEffect, useCallback } from "react";
import {
  Card, Table, Spinner, Alert, Row, Col, Badge, Button,
  Accordion, Tab, Tabs,
} from "react-bootstrap";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";
import { toast } from "react-toastify";
import api from "../services/api";

const SEVERITY_COLORS = {
  CRITICAL: "#dc3545",
  HIGH: "#fd7e14",
  MEDIUM: "#ffc107",
  LOW: "#0dcaf0",
  INFO: "#6c757d",
};

const CATEGORY_LABELS = {
  DENIAL_PATTERN: "Denial Patterns",
  UNDERPAYMENT: "Underpayments",
  SECONDARY_MISSING: "Missing Secondary",
  PAYER_TREND: "Payer Trends",
  PHYSICIAN_ALERT: "Physician Alerts",
  FILING_RISK: "Filing Risks",
  REVENUE_OPPORTUNITY: "Revenue Opportunities",
  PROCESS_IMPROVEMENT: "Process Improvements",
};

const PIE_COLORS = ["#0d6efd", "#6610f2", "#6f42c1", "#d63384", "#dc3545", "#fd7e14", "#ffc107", "#198754"];

function Insights() {
  const [tab, setTab] = useState("recommendations");
  const [recs, setRecs] = useState(null);
  const [graph, setGraph] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState({});

  const formatMoney = (v) => {
    if (v == null) return "--";
    return "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  };

  const loadRecs = useCallback(() => {
    setLoading((p) => ({ ...p, recs: true }));
    api.get("/insights/recommendations", { params: { persist: true } })
      .then((r) => setRecs(r.data))
      .catch(() => toast.error("Failed to load recommendations"))
      .finally(() => setLoading((p) => ({ ...p, recs: false })));
  }, []);

  const loadGraph = useCallback(() => {
    setLoading((p) => ({ ...p, graph: true }));
    api.get("/insights/graph")
      .then((r) => setGraph(r.data))
      .catch(() => toast.error("Failed to load knowledge graph"))
      .finally(() => setLoading((p) => ({ ...p, graph: false })));
  }, []);

  const loadReport = useCallback(() => {
    setLoading((p) => ({ ...p, report: true }));
    api.get("/insights/report")
      .then((r) => setReport(r.data))
      .catch(() => toast.error("Failed to load session report"))
      .finally(() => setLoading((p) => ({ ...p, report: false })));
  }, []);

  useEffect(() => {
    if (tab === "recommendations" && !recs) loadRecs();
    if (tab === "graph" && !graph) loadGraph();
    if (tab === "report" && !report) loadReport();
  }, [tab, recs, graph, report, loadRecs, loadGraph, loadReport]);

  const handleAcknowledge = async (id) => {
    await api.post(`/insights/${id}/status`, { status: "ACKNOWLEDGED" });
    toast.success("Insight acknowledged");
    loadReport();
  };

  // --- Graph visualization data ---
  const graphNodesByType = (type) =>
    (graph?.nodes || []).filter((n) => n.type === type).sort((a, b) => (b.total_revenue || 0) - (a.total_revenue || 0));

  const payerDenialData = graphNodesByType("PAYER")
    .filter((n) => n.denial_rate > 0)
    .slice(0, 15)
    .map((n) => ({ name: n.label, denial_rate: n.denial_rate, claims: n.claim_count }));

  const modalityRevData = graphNodesByType("MODALITY")
    .map((n) => ({ name: n.label, revenue: n.total_revenue, scans: n.scan_count }));

  const edgesByType = (type) => (graph?.edges || []).filter((e) => e.type === type);

  const topPayerModalityEdges = edgesByType("PAYS_FOR")
    .filter((e) => e.denial_rate > 10 && e.count >= 5)
    .sort((a, b) => b.denial_rate - a.denial_rate)
    .slice(0, 20)
    .map((e) => ({
      combo: `${e.source.replace("payer:", "")} + ${e.target.replace("modality:", "")}`,
      denial_rate: e.denial_rate,
      count: e.count,
      revenue: e.weight,
    }));

  // Category breakdown for recommendations
  const recsByCategory = {};
  (recs?.recommendations || []).forEach((r) => {
    if (!recsByCategory[r.category]) recsByCategory[r.category] = [];
    recsByCategory[r.category].push(r);
  });

  const categoryPieData = Object.entries(recsByCategory).map(([cat, items]) => ({
    name: CATEGORY_LABELS[cat] || cat,
    value: items.reduce((sum, i) => sum + (i.estimated_impact || 0), 0),
  })).filter((d) => d.value > 0).sort((a, b) => b.value - a.value);

  return (
    <>
      <h2 className="mb-4">Insights & Knowledge Graph</h2>

      <Tabs activeKey={tab} onSelect={setTab} className="mb-4">
        {/* ===== RECOMMENDATIONS TAB ===== */}
        <Tab eventKey="recommendations" title="Recommendations">
          {loading.recs ? (
            <div className="text-center py-4"><Spinner animation="border" /></div>
          ) : !recs ? (
            <Alert variant="info">Click to load recommendations</Alert>
          ) : (
            <>
              <Row className="g-3 mb-4">
                <Col md={3}>
                  <Card className="border-0 shadow-sm text-center">
                    <Card.Body>
                      <div className="text-muted small">Total Insights</div>
                      <div className="fs-3 fw-bold">{recs.total}</div>
                    </Card.Body>
                  </Card>
                </Col>
                <Col md={3}>
                  <Card className="border-0 shadow-sm text-center">
                    <Card.Body>
                      <div className="text-muted small">Total Est. Impact</div>
                      <div className="fs-3 fw-bold text-success">{formatMoney(recs.total_impact)}</div>
                    </Card.Body>
                  </Card>
                </Col>
                <Col md={3}>
                  <Card className="border-0 shadow-sm text-center">
                    <Card.Body>
                      <div className="text-muted small">Critical</div>
                      <div className="fs-3 fw-bold text-danger">
                        {(recs.recommendations || []).filter((r) => r.severity === "CRITICAL").length}
                      </div>
                    </Card.Body>
                  </Card>
                </Col>
                <Col md={3}>
                  <Card className="border-0 shadow-sm text-center">
                    <Card.Body>
                      <div className="text-muted small">Saved to Log</div>
                      <div className="fs-3 fw-bold text-info">{recs.persisted}</div>
                    </Card.Body>
                  </Card>
                </Col>
              </Row>

              {categoryPieData.length > 0 && (
                <Card className="border-0 shadow-sm mb-4">
                  <Card.Body>
                    <h6>Impact by Category</h6>
                    <ResponsiveContainer width="100%" height={250}>
                      <PieChart>
                        <Pie data={categoryPieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, value }) => `${name}: ${formatMoney(value)}`}>
                          {categoryPieData.map((_, i) => (
                            <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(v) => formatMoney(v)} />
                      </PieChart>
                    </ResponsiveContainer>
                  </Card.Body>
                </Card>
              )}

              <Accordion defaultActiveKey="0">
                {Object.entries(recsByCategory).map(([cat, items], idx) => (
                  <Accordion.Item eventKey={String(idx)} key={cat}>
                    <Accordion.Header>
                      <span className="fw-bold me-2">{CATEGORY_LABELS[cat] || cat}</span>
                      <Badge bg="secondary" className="me-2">{items.length}</Badge>
                      <span className="text-success small">{formatMoney(items.reduce((s, i) => s + (i.estimated_impact || 0), 0))} potential</span>
                    </Accordion.Header>
                    <Accordion.Body>
                      {items.map((rec, i) => (
                        <Card key={i} className="mb-3 border-start border-4" style={{ borderColor: SEVERITY_COLORS[rec.severity] }}>
                          <Card.Body>
                            <div className="d-flex justify-content-between align-items-start mb-2">
                              <div>
                                <Badge bg="none" style={{ backgroundColor: SEVERITY_COLORS[rec.severity], color: "#fff" }} className="me-2">{rec.severity}</Badge>
                                <strong>{rec.title}</strong>
                              </div>
                              {rec.estimated_impact > 0 && (
                                <Badge bg="success" className="fs-6">{formatMoney(rec.estimated_impact)}</Badge>
                              )}
                            </div>
                            <p className="text-muted mb-2 small">{rec.description}</p>
                            <div className="bg-light rounded p-2">
                              <strong className="small">Recommendation:</strong>
                              <p className="mb-0 small">{rec.recommendation}</p>
                            </div>
                            {rec.affected_count > 0 && (
                              <small className="text-muted mt-1 d-block">{rec.affected_count} claims affected</small>
                            )}
                          </Card.Body>
                        </Card>
                      ))}
                    </Accordion.Body>
                  </Accordion.Item>
                ))}
              </Accordion>

              <div className="mt-3">
                <Button variant="outline-primary" size="sm" onClick={loadRecs}>Refresh</Button>
              </div>
            </>
          )}
        </Tab>

        {/* ===== KNOWLEDGE GRAPH TAB ===== */}
        <Tab eventKey="graph" title="Knowledge Graph">
          {loading.graph ? (
            <div className="text-center py-4"><Spinner animation="border" /></div>
          ) : !graph ? (
            <Alert variant="info">Loading graph...</Alert>
          ) : (
            <>
              <Row className="g-3 mb-4">
                <Col md={4}>
                  <Card className="border-0 shadow-sm text-center">
                    <Card.Body>
                      <div className="text-muted small">Entities</div>
                      <div className="fs-3 fw-bold">{graph.node_count}</div>
                    </Card.Body>
                  </Card>
                </Col>
                <Col md={4}>
                  <Card className="border-0 shadow-sm text-center">
                    <Card.Body>
                      <div className="text-muted small">Relationships</div>
                      <div className="fs-3 fw-bold">{graph.edge_count}</div>
                    </Card.Body>
                  </Card>
                </Col>
                <Col md={4}>
                  <Card className="border-0 shadow-sm text-center">
                    <Card.Body>
                      <div className="text-muted small">Total Revenue</div>
                      <div className="fs-3 fw-bold text-success">{formatMoney(graph.metrics?.totals?.total_revenue)}</div>
                    </Card.Body>
                  </Card>
                </Col>
              </Row>

              {/* Payer denial rates */}
              {payerDenialData.length > 0 && (
                <Card className="border-0 shadow-sm mb-4">
                  <Card.Body>
                    <h6>Payer Denial Rates</h6>
                    <ResponsiveContainer width="100%" height={300}>
                      <BarChart data={payerDenialData} layout="vertical">
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis type="number" unit="%" />
                        <YAxis type="category" dataKey="name" width={100} />
                        <Tooltip formatter={(v, n) => n === "denial_rate" ? `${v}%` : v} />
                        <Bar dataKey="denial_rate" fill="#dc3545" name="Denial Rate %" />
                      </BarChart>
                    </ResponsiveContainer>
                  </Card.Body>
                </Card>
              )}

              {/* Modality revenue */}
              {modalityRevData.length > 0 && (
                <Card className="border-0 shadow-sm mb-4">
                  <Card.Body>
                    <h6>Revenue by Modality</h6>
                    <ResponsiveContainer width="100%" height={250}>
                      <BarChart data={modalityRevData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="name" />
                        <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}K`} />
                        <Tooltip formatter={(v) => formatMoney(v)} />
                        <Bar dataKey="revenue" fill="#0d6efd" name="Revenue" />
                      </BarChart>
                    </ResponsiveContainer>
                  </Card.Body>
                </Card>
              )}

              {/* Problem combos: payer+modality denial hotspots */}
              {topPayerModalityEdges.length > 0 && (
                <Card className="border-0 shadow-sm mb-4">
                  <Card.Body>
                    <h6>Denial Hotspots (Payer + Modality)</h6>
                    <Table striped size="sm">
                      <thead>
                        <tr>
                          <th>Combination</th>
                          <th className="text-end">Denial Rate</th>
                          <th className="text-end">Claims</th>
                          <th className="text-end">Revenue</th>
                        </tr>
                      </thead>
                      <tbody>
                        {topPayerModalityEdges.map((e, i) => (
                          <tr key={i}>
                            <td><strong>{e.combo}</strong></td>
                            <td className="text-end">
                              <Badge bg={e.denial_rate > 30 ? "danger" : "warning"}>{e.denial_rate}%</Badge>
                            </td>
                            <td className="text-end">{e.count}</td>
                            <td className="text-end">{formatMoney(e.revenue)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </Card.Body>
                </Card>
              )}

              {/* Payer trends */}
              {graph.metrics?.payer_trends && (() => {
                const allYears = [...new Set(
                  Object.values(graph.metrics.payer_trends).flatMap((yrs) => yrs.map((y) => y.year))
                )].sort();
                return (
                <Card className="border-0 shadow-sm mb-4">
                  <Card.Body>
                    <h6>Payer Year-over-Year Trends</h6>
                    <Table striped size="sm">
                      <thead>
                        <tr>
                          <th>Payer</th>
                          {allYears.map((y) => (
                            <th key={y} className="text-end">{y}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(graph.metrics.payer_trends)
                          .sort((a, b) => {
                            const aMax = Math.max(...a[1].map((y) => y.revenue));
                            const bMax = Math.max(...b[1].map((y) => y.revenue));
                            return bMax - aMax;
                          })
                          .slice(0, 12)
                          .map(([carrier, years]) => {
                            const yearMap = {};
                            years.forEach((y) => { yearMap[y.year] = y; });
                            return (
                              <tr key={carrier}>
                                <td><strong>{carrier}</strong></td>
                                {allYears.map((y) => (
                                  <td key={y} className="text-end small">
                                    {yearMap[y] ? (
                                      <span>{formatMoney(yearMap[y].revenue)}<br /><span className="text-muted">{yearMap[y].count} claims</span></span>
                                    ) : "--"}
                                  </td>
                                ))}
                              </tr>
                            );
                          })}
                      </tbody>
                    </Table>
                  </Card.Body>
                </Card>
                );
              })()
              )}
            </>
          )}
        </Tab>

        {/* ===== SESSION REPORT TAB ===== */}
        <Tab eventKey="report" title="Session Log">
          {loading.report ? (
            <div className="text-center py-4"><Spinner animation="border" /></div>
          ) : !report ? (
            <Alert variant="info">Loading report...</Alert>
          ) : (
            <>
              {/* System state */}
              <Card className="border-0 shadow-sm mb-4">
                <Card.Body>
                  <h6>System State</h6>
                  <Row className="g-3">
                    <Col md={3}>
                      <div className="text-muted small">Total Records</div>
                      <div className="fs-5 fw-bold">{report.system_state?.total_billing_records?.toLocaleString()}</div>
                    </Col>
                    <Col md={3}>
                      <div className="text-muted small">Total Revenue</div>
                      <div className="fs-5 fw-bold">{formatMoney(report.system_state?.total_revenue)}</div>
                    </Col>
                    <Col md={3}>
                      <div className="text-muted small">Denial Rate</div>
                      <div className="fs-5 fw-bold text-danger">{report.system_state?.denial_rate_pct}%</div>
                    </Col>
                    <Col md={3}>
                      <div className="text-muted small">ERA Link Rate</div>
                      <div className="fs-5 fw-bold">{report.system_state?.era_link_rate_pct}%</div>
                    </Col>
                  </Row>
                </Card.Body>
              </Card>

              {/* Priority actions */}
              {report.priority_actions?.length > 0 && (
                <Card className="border-0 shadow-sm mb-4">
                  <Card.Body>
                    <h6>Priority Actions</h6>
                    {report.priority_actions.map((a, i) => (
                      <Alert
                        key={i}
                        variant={a.severity === "CRITICAL" ? "danger" : a.severity === "HIGH" ? "warning" : "info"}
                        className="py-2 mb-2"
                      >
                        <strong>#{a.priority}</strong> [{a.category}] {a.action}
                        {a.estimated_impact > 0 && (
                          <Badge bg="success" className="ms-2">{formatMoney(a.estimated_impact)}</Badge>
                        )}
                      </Alert>
                    ))}
                  </Card.Body>
                </Card>
              )}

              {/* Open insights */}
              {report.open_insights?.length > 0 && (
                <Card className="border-0 shadow-sm mb-4">
                  <Card.Body>
                    <h6>Open Insights ({report.open_insights.length})</h6>
                    <Table striped size="sm">
                      <thead>
                        <tr>
                          <th>Severity</th>
                          <th>Category</th>
                          <th>Title</th>
                          <th className="text-end">Impact</th>
                          <th>Status</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.open_insights.slice(0, 20).map((ins) => (
                          <tr key={ins.id}>
                            <td><Badge bg="none" style={{ backgroundColor: SEVERITY_COLORS[ins.severity], color: "#fff" }}>{ins.severity}</Badge></td>
                            <td className="small">{CATEGORY_LABELS[ins.category] || ins.category}</td>
                            <td className="small">{ins.title}</td>
                            <td className="text-end">{ins.estimated_impact ? formatMoney(ins.estimated_impact) : "--"}</td>
                            <td><Badge bg="info">{ins.status}</Badge></td>
                            <td>
                              {ins.status === "OPEN" && (
                                <Button size="sm" variant="outline-primary" onClick={() => handleAcknowledge(ins.id)}>Ack</Button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </Card.Body>
                </Card>
              )}

              {/* Session context (raw text for AI) */}
              <Card className="border-0 shadow-sm mb-4">
                <Card.Body>
                  <h6>Session Context (for AI handoff)</h6>
                  <pre className="bg-dark text-light p-3 rounded small" style={{ whiteSpace: "pre-wrap", maxHeight: "400px", overflow: "auto" }}>
                    {report.session_context}
                  </pre>
                  <Button
                    size="sm"
                    variant="outline-secondary"
                    onClick={() => {
                      navigator.clipboard.writeText(report.session_context);
                      toast.success("Copied to clipboard");
                    }}
                  >Copy to Clipboard</Button>
                </Card.Body>
              </Card>

              <div className="mt-3">
                <Button variant="outline-primary" size="sm" onClick={loadReport}>Refresh Report</Button>
              </div>
            </>
          )}
        </Tab>
      </Tabs>
    </>
  );
}

export default Insights;
