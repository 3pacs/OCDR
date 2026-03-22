import React, { useState, useEffect } from "react";
import { Card, Col, Row, Spinner, Alert, Badge } from "react-bootstrap";
import { Link } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import api from "../services/api";

function KpiCard({ title, value, subtitle, link, color = "primary" }) {
  return (
    <Col md={3} sm={6}>
      <Card className="h-100 border-0 shadow-sm">
        <Card.Body>
          <Card.Title className="text-muted small text-uppercase">{title}</Card.Title>
          <Card.Text className={`fs-3 fw-bold text-${color}`}>{value}</Card.Text>
          {subtitle && <small className="text-muted">{subtitle}</small>}
          {link && (
            <div className="mt-2">
              <Link to={link} className="small">View details &rarr;</Link>
            </div>
          )}
        </Card.Body>
      </Card>
    </Col>
  );
}

function Dashboard() {
  const [health, setHealth] = useState(null);
  const [underpaymentSummary, setUnderpaymentSummary] = useState(null);
  const [filingAlerts, setFilingAlerts] = useState(null);
  const [matchSummary, setMatchSummary] = useState(null);
  const [denialSummary, setDenialSummary] = useState(null);
  const [secondarySummary, setSecondarySummary] = useState(null);
  const [topInsights, setTopInsights] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchData() {
      try {
        // Fire all requests in parallel — each resolves independently
        const results = await Promise.allSettled([
          api.get("/import/status"),
          api.get("/underpayments/summary"),
          api.get("/filing-deadlines/alerts"),
          api.get("/matching/summary"),
          api.get("/denials/summary"),
          api.get("/secondary-followup/summary"),
          api.get("/insights/recommendations", { timeout: 15000 }),
        ]);

        if (results[0].status === "fulfilled") setHealth(results[0].value.data);
        if (results[1].status === "fulfilled") setUnderpaymentSummary(results[1].value.data);
        if (results[2].status === "fulfilled") setFilingAlerts(results[2].value.data);
        if (results[3].status === "fulfilled") setMatchSummary(results[3].value.data);
        if (results[4].status === "fulfilled") setDenialSummary(results[4].value.data);
        if (results[5].status === "fulfilled") setSecondarySummary(results[5].value.data);
        if (results[6].status === "fulfilled") setTopInsights(results[6].value.data);
      } catch (err) {
        setError("Could not connect to backend API");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="text-center mt-5">
        <Spinner animation="border" /> Loading dashboard...
      </div>
    );
  }

  const formatMoney = (val) => {
    if (val == null) return "$0";
    return "$" + Math.abs(val).toLocaleString(undefined, { maximumFractionDigits: 0 });
  };

  return (
    <>
      <h2 className="mb-4">Dashboard</h2>

      {error && <Alert variant="warning">{error}</Alert>}

      <Row className="g-3 mb-4">
        <KpiCard
          title="Total Records"
          value={health?.total_records?.toLocaleString() ?? "0"}
          subtitle={health?.last_import ? `Last import: ${new Date(health.last_import).toLocaleDateString()}` : "No imports yet"}
          link="/import"
        />
        <KpiCard
          title="Underpaid Claims"
          value={underpaymentSummary?.total_flagged?.toLocaleString() ?? "0"}
          subtitle={underpaymentSummary ? `${underpaymentSummary.flagged_pct}% of paid claims` : null}
          link="/underpayments"
          color="danger"
        />
        <KpiCard
          title="Underpayment Gap"
          value={underpaymentSummary ? formatMoney(underpaymentSummary.total_variance) : "$0"}
          subtitle="vs. fee schedule"
          link="/underpayments"
          color="warning"
        />
        <KpiCard
          title="Filing Deadline Alerts"
          value={
            (filingAlerts?.past_deadline_count ?? 0) + (filingAlerts?.warning_count ?? 0)
          }
          subtitle={`${filingAlerts?.past_deadline_count ?? 0} past deadline, ${filingAlerts?.warning_count ?? 0} warning`}
          link="/filing-deadlines"
          color={(filingAlerts?.past_deadline_count ?? 0) > 0 ? "danger" : "success"}
        />
      </Row>

      <Row className="g-3 mb-4">
        <KpiCard
          title="Denied Claims"
          value={denialSummary?.total_denied?.toLocaleString() ?? "0"}
          subtitle={denialSummary ? `${denialSummary.pending} pending, ${denialSummary.appealed} appealed` : null}
          link="/denials"
          color="danger"
        />
        <KpiCard
          title="Missing Secondary"
          value={secondarySummary?.total_claims?.toLocaleString() ?? "0"}
          subtitle={secondarySummary ? `Est. ${formatMoney(secondarySummary.estimated_missing_secondary)} missing` : null}
          link="/secondary-followup"
          color="warning"
        />
        <KpiCard
          title="AI Insights"
          value={topInsights?.total ?? "0"}
          subtitle={topInsights ? `${formatMoney(topInsights.total_impact)} potential impact` : null}
          link="/insights"
          color="info"
        />
        <KpiCard
          title="Critical Insights"
          value={(topInsights?.recommendations || []).filter((r) => r.severity === "CRITICAL").length}
          subtitle="need immediate attention"
          link="/insights"
          color={(topInsights?.recommendations || []).some((r) => r.severity === "CRITICAL") ? "danger" : "success"}
        />
      </Row>

      {matchSummary && matchSummary.total_era_claims > 0 && (
        <Row className="g-3 mb-4">
          <Col md={6}>
            <Card className="border-0 shadow-sm">
              <Card.Body>
                <Card.Title>ERA &harr; Billing Match Rate</Card.Title>
                <div className="d-flex align-items-center gap-3">
                  <div className="fs-1 fw-bold" style={{ color: matchSummary.match_rate > 80 ? "#198754" : matchSummary.match_rate > 50 ? "#ffc107" : "#dc3545" }}>
                    {matchSummary.match_rate}%
                  </div>
                  <div>
                    <div>{matchSummary.matched?.toLocaleString()} matched / {matchSummary.total_era_claims?.toLocaleString()} ERA claims</div>
                    <div className="text-muted small">{matchSummary.unmatched?.toLocaleString()} unmatched &mdash; {matchSummary.denied_claims} denied</div>
                    <Link to="/matching" className="small">View details &rarr;</Link>
                  </div>
                </div>
              </Card.Body>
            </Card>
          </Col>
          <Col md={6}>
            <Card className="border-0 shadow-sm">
              <Card.Body>
                <Card.Title>Billing Records Linked</Card.Title>
                <div className="d-flex align-items-center gap-3">
                  <div className="fs-1 fw-bold text-primary">{matchSummary.billing_records_linked?.toLocaleString()}</div>
                  <div>
                    <div>records linked to ERA payment data</div>
                    <div className="text-muted small">
                      {health?.total_records ? `${Math.round(matchSummary.billing_records_linked / health.total_records * 100)}% of ${health.total_records.toLocaleString()} total` : ""}
                    </div>
                    <Link to="/matching" className="small">Run matcher &rarr;</Link>
                  </div>
                </div>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}

      {underpaymentSummary?.by_carrier?.length > 0 && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            <Card.Title>Underpayment Variance by Carrier</Card.Title>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={underpaymentSummary.by_carrier.slice(0, 10)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tickFormatter={(v) => `$${Math.abs(v).toLocaleString()}`} />
                <YAxis type="category" dataKey="carrier" width={100} />
                <Tooltip formatter={(v) => `$${Math.abs(v).toLocaleString()}`} />
                <Bar dataKey="variance" fill="#dc3545" name="Variance ($)" />
              </BarChart>
            </ResponsiveContainer>
          </Card.Body>
        </Card>
      )}

      {(filingAlerts?.past_deadline?.length > 0 || filingAlerts?.warning?.length > 0) && (
        <Card className="border-0 shadow-sm">
          <Card.Body>
            <Card.Title>Urgent Filing Deadlines</Card.Title>
            {filingAlerts.past_deadline?.slice(0, 5).map((item) => (
              <Alert variant="danger" key={item.id} className="py-2 mb-2">
                <strong>{item.patient_name}</strong> &mdash; {item.insurance_carrier} &mdash; {item.modality} &mdash;
                Deadline: {item.filing_deadline} ({Math.abs(item.days_remaining)} days overdue)
              </Alert>
            ))}
            {filingAlerts.warning?.slice(0, 5).map((item) => (
              <Alert variant="warning" key={item.id} className="py-2 mb-2">
                <strong>{item.patient_name}</strong> &mdash; {item.insurance_carrier} &mdash; {item.modality} &mdash;
                Deadline: {item.filing_deadline} ({item.days_remaining} days left)
              </Alert>
            ))}
            {(filingAlerts.past_deadline?.length > 5 || filingAlerts.warning?.length > 5) && (
              <Link to="/filing-deadlines">View all alerts &rarr;</Link>
            )}
          </Card.Body>
        </Card>
      )}

      {topInsights?.recommendations?.length > 0 && (
        <Card className="border-0 shadow-sm mt-4">
          <Card.Body>
            <Card.Title>Top Recommendations</Card.Title>
            {topInsights.recommendations.slice(0, 5).map((rec, i) => (
              <Alert
                key={i}
                variant={rec.severity === "CRITICAL" ? "danger" : rec.severity === "HIGH" ? "warning" : "info"}
                className="py-2 mb-2"
              >
                <div className="d-flex justify-content-between align-items-start">
                  <div>
                    <Badge bg={rec.severity === "CRITICAL" ? "danger" : rec.severity === "HIGH" ? "warning" : "info"} className="me-2">{rec.severity}</Badge>
                    <strong>{rec.title}</strong>
                    <div className="small text-muted mt-1">{rec.recommendation.substring(0, 200)}{rec.recommendation.length > 200 ? "..." : ""}</div>
                  </div>
                  {rec.estimated_impact > 0 && (
                    <Badge bg="success" className="ms-2 fs-6">{formatMoney(rec.estimated_impact)}</Badge>
                  )}
                </div>
              </Alert>
            ))}
            <Link to="/insights" className="small">View all {topInsights.total} insights &rarr;</Link>
          </Card.Body>
        </Card>
      )}
    </>
  );
}

export default Dashboard;
