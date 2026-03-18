import React, { useState, useEffect } from "react";
import { Card, Row, Col, Badge, Alert, Spinner, Table, ProgressBar, Button } from "react-bootstrap";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import api from "../services/api";

const SEVERITY_COLORS = {
  CRITICAL: "danger",
  HIGH: "warning",
  MEDIUM: "info",
  LOW: "secondary",
};

const EFFORT_LABELS = {
  QUICK_WIN: { label: "Quick Win", color: "success", desc: "1-2 days, minimal effort" },
  MODERATE: { label: "Moderate", color: "warning", desc: "1-2 weeks, some integration" },
  MAJOR_PROJECT: { label: "Major Project", color: "danger", desc: "1+ months, significant effort" },
};

const CATEGORY_LABELS = {
  REVENUE_LEAK: "Revenue Leak",
  COMPLIANCE: "Compliance",
  EFFICIENCY: "Efficiency",
  DATA_QUALITY: "Data Quality",
  BEST_PRACTICE: "Best Practice",
};

function formatMoney(val) {
  if (val == null || val === 0) return "$0";
  if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`;
  if (val >= 1000) return `$${(val / 1000).toFixed(0)}K`;
  return `$${val.toFixed(0)}`;
}

function SeverityBadge({ severity }) {
  return <Badge bg={SEVERITY_COLORS[severity] || "secondary"}>{severity}</Badge>;
}

function EffortBadge({ effort }) {
  const info = EFFORT_LABELS[effort];
  if (!info) return null;
  return <Badge bg={info.color} title={info.desc}>{info.label}</Badge>;
}

function ImpactSummary({ data }) {
  if (!data) return null;

  const chartData = Object.entries(data.by_category || {}).map(([cat, count]) => ({
    name: CATEGORY_LABELS[cat] || cat,
    count,
  }));

  const sevData = [
    { name: "Critical", count: data.by_severity?.CRITICAL || 0, fill: "#dc3545" },
    { name: "High", count: data.by_severity?.HIGH || 0, fill: "#ffc107" },
    { name: "Medium", count: data.by_severity?.MEDIUM || 0, fill: "#0dcaf0" },
    { name: "Low", count: data.by_severity?.LOW || 0, fill: "#6c757d" },
  ].filter(d => d.count > 0);

  return (
    <>
      <Row className="g-3 mb-4">
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body className="text-center">
              <div className="text-muted small text-uppercase">Total Impact</div>
              <div className="fs-2 fw-bold text-success">{formatMoney(data.total_impact)}</div>
              <small className="text-muted">estimated recoverable</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body className="text-center">
              <div className="text-muted small text-uppercase">Suggestions</div>
              <div className="fs-2 fw-bold">{data.total}</div>
              <small className="text-muted">actionable improvements</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body className="text-center">
              <div className="text-muted small text-uppercase">Critical / High</div>
              <div className="fs-2 fw-bold text-danger">
                {(data.by_severity?.CRITICAL || 0) + (data.by_severity?.HIGH || 0)}
              </div>
              <small className="text-muted">need attention</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body className="text-center">
              <div className="text-muted small text-uppercase">Quick Wins</div>
              <div className="fs-2 fw-bold text-success">
                {(data.suggestions || []).filter(s => s.effort === "QUICK_WIN").length}
              </div>
              <small className="text-muted">low effort, high return</small>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {chartData.length > 0 && (
        <Row className="g-3 mb-4">
          <Col md={6}>
            <Card className="border-0 shadow-sm">
              <Card.Body>
                <Card.Title className="small text-uppercase text-muted">By Category</Card.Title>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={chartData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#0d6efd" name="Suggestions" />
                  </BarChart>
                </ResponsiveContainer>
              </Card.Body>
            </Card>
          </Col>
          <Col md={6}>
            <Card className="border-0 shadow-sm">
              <Card.Body>
                <Card.Title className="small text-uppercase text-muted">By Severity</Card.Title>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={sevData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count" name="Count">
                      {sevData.map((entry, i) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Bar>
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

function SuggestionCard({ suggestion, index }) {
  const s = suggestion;
  const [expanded, setExpanded] = useState(index < 3); // First 3 auto-expanded

  return (
    <Card className={`border-0 shadow-sm mb-3 border-start border-4 border-${SEVERITY_COLORS[s.severity] || "secondary"}`}>
      <Card.Body>
        <div className="d-flex justify-content-between align-items-start mb-2">
          <div className="d-flex align-items-center gap-2 flex-wrap">
            <span className="fw-bold">{index + 1}.</span>
            <SeverityBadge severity={s.severity} />
            <Badge bg="light" text="dark">{CATEGORY_LABELS[s.subcategory] || s.subcategory}</Badge>
            <EffortBadge effort={s.effort} />
            {s.entity_id && <Badge bg="outline-dark" className="border">{s.entity_id}</Badge>}
          </div>
          <div className="text-end">
            {s.estimated_impact > 0 && (
              <div className="fs-5 fw-bold text-success">{formatMoney(s.estimated_impact)}</div>
            )}
            {s.affected_count > 0 && (
              <small className="text-muted">{s.affected_count.toLocaleString()} claims</small>
            )}
          </div>
        </div>

        <h6 className="mb-2">{s.title}</h6>

        <Button
          variant="link"
          size="sm"
          className="p-0 text-muted"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Collapse" : "Show details"}
        </Button>

        {expanded && (
          <div className="mt-2">
            <p className="small mb-2">{s.description}</p>

            <div className="bg-light rounded p-2 mb-2">
              <strong className="small">Recommendation:</strong>
              <pre className="small mb-0 mt-1" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>
                {s.recommendation}
              </pre>
            </div>

            {s.best_practice && (
              <div className="small text-muted">
                <strong>Industry reference:</strong> {s.best_practice}
              </div>
            )}

            {s.benchmark != null && s.current_value != null && (
              <div className="mt-2">
                <div className="d-flex justify-content-between small mb-1">
                  <span>Current: {s.current_value}%</span>
                  <span>Target: {s.benchmark}%</span>
                </div>
                <ProgressBar>
                  <ProgressBar
                    now={Math.min(s.current_value, 100)}
                    variant={s.current_value >= s.benchmark ? "success" : s.current_value >= s.benchmark * 0.7 ? "warning" : "danger"}
                    label={`${s.current_value}%`}
                  />
                </ProgressBar>
              </div>
            )}
          </div>
        )}
      </Card.Body>
    </Card>
  );
}

function BenchmarkTable({ benchmarks }) {
  if (!benchmarks) return null;

  const rows = [
    { key: "denial_rate_target", label: "Denial Rate", unit: "%", direction: "lower is better" },
    { key: "clean_claim_rate", label: "Clean Claim Rate", unit: "%", direction: "higher is better" },
    { key: "match_rate_target", label: "ERA Match Rate", unit: "%", direction: "higher is better" },
    { key: "crosswalk_coverage", label: "ID Crosswalk Coverage", unit: "%", direction: "higher is better" },
    { key: "ar_days_target", label: "A/R Days", unit: " days", direction: "lower is better" },
    { key: "days_to_submit", label: "Days to Submit Claim", unit: " days", direction: "lower is better" },
    { key: "secondary_capture_rate", label: "Secondary Capture Rate", unit: "%", direction: "higher is better" },
  ];

  return (
    <Card className="border-0 shadow-sm mb-4">
      <Card.Body>
        <Card.Title className="small text-uppercase text-muted">Industry Benchmarks</Card.Title>
        <Table size="sm" className="small mb-0">
          <thead>
            <tr><th>Metric</th><th>Target</th><th>Note</th></tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.key}>
                <td className="fw-bold">{r.label}</td>
                <td>{benchmarks[r.key] != null ? `${benchmarks[r.key]}${r.unit}` : "--"}</td>
                <td className="text-muted">{r.direction}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card.Body>
    </Card>
  );
}

function PipelineImprovements() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all"); // all, CRITICAL, HIGH, QUICK_WIN

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await api.get("/analytics/pipeline-suggestions", { timeout: 60000 });
        setData(res.data);
      } catch (err) {
        setError("Failed to load pipeline suggestions. The backend may still be starting up.");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get("/analytics/pipeline-suggestions", { timeout: 60000 });
      setData(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="text-center mt-5">
        <Spinner animation="border" />
        <div className="mt-2">Analyzing billing pipeline...</div>
      </div>
    );
  }

  const suggestions = data?.suggestions || [];
  const filtered = filter === "all"
    ? suggestions
    : filter === "QUICK_WIN"
      ? suggestions.filter(s => s.effort === "QUICK_WIN")
      : suggestions.filter(s => s.severity === filter);

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-4">
        <div>
          <h2 className="mb-1">Pipeline Improvements</h2>
          <small className="text-muted">
            Data-driven suggestions based on your billing patterns vs. industry best practices.
            {data?.generated_at && <> Last analyzed: {data.generated_at}</>}
          </small>
        </div>
        <Button variant="outline-primary" size="sm" onClick={refresh} disabled={loading}>
          {loading ? <Spinner size="sm" /> : "Refresh Analysis"}
        </Button>
      </div>

      {error && <Alert variant="warning">{error}</Alert>}

      <ImpactSummary data={data} />

      <Row className="g-3">
        <Col md={9}>
          {/* Filter buttons */}
          <div className="d-flex gap-2 mb-3 flex-wrap">
            {[
              { key: "all", label: "All", count: suggestions.length },
              { key: "CRITICAL", label: "Critical", count: data?.by_severity?.CRITICAL || 0 },
              { key: "HIGH", label: "High", count: data?.by_severity?.HIGH || 0 },
              { key: "QUICK_WIN", label: "Quick Wins", count: suggestions.filter(s => s.effort === "QUICK_WIN").length },
            ].map(f => (
              <Button
                key={f.key}
                variant={filter === f.key ? "primary" : "outline-secondary"}
                size="sm"
                onClick={() => setFilter(f.key)}
              >
                {f.label} <Badge bg="light" text="dark">{f.count}</Badge>
              </Button>
            ))}
          </div>

          {filtered.length === 0 && (
            <Alert variant="success">No suggestions in this category. Your pipeline is looking good!</Alert>
          )}

          {filtered.map((s, i) => (
            <SuggestionCard key={i} suggestion={s} index={i} />
          ))}
        </Col>

        <Col md={3}>
          <BenchmarkTable benchmarks={data?.benchmarks} />

          <Card className="border-0 shadow-sm mb-4">
            <Card.Body>
              <Card.Title className="small text-uppercase text-muted">How This Works</Card.Title>
              <ul className="small mb-0">
                <li>Analyzes your billing data daily</li>
                <li>Compares against MGMA/HFMA/RBMA benchmarks</li>
                <li>Identifies revenue leaks and compliance gaps</li>
                <li>Prioritizes by financial impact</li>
                <li>Tags quick wins vs. major projects</li>
              </ul>
            </Card.Body>
          </Card>

          <Card className="border-0 shadow-sm">
            <Card.Body>
              <Card.Title className="small text-uppercase text-muted">Key Sources</Card.Title>
              <ul className="small mb-0">
                <li>ANSI X12 835/837 standards</li>
                <li>CMS CARC/RARC code database</li>
                <li>MGMA radiology benchmarks</li>
                <li>HFMA denial management guide</li>
                <li>RBMA billing best practices</li>
                <li>ACR coding standards</li>
              </ul>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  );
}

export default PipelineImprovements;
