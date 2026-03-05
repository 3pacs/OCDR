import React, { useState, useEffect } from "react";
import { Card, Row, Col, Button, Alert, Spinner, Table, Badge, Tab, Tabs, ProgressBar } from "react-bootstrap";
import api from "../services/api";

function MatchSummary({ summary, onRefresh }) {
  if (!summary) return null;

  const rate = summary.match_rate || 0;
  const barVariant = rate > 80 ? "success" : rate > 50 ? "warning" : "danger";

  return (
    <Card className="border-0 shadow-sm mb-4">
      <Card.Body>
        <Card.Title>Match Overview</Card.Title>
        <Row className="g-3 mb-3">
          <Col md={2} className="text-center">
            <div className="fs-3 fw-bold">{summary.total_era_claims?.toLocaleString()}</div>
            <small className="text-muted">ERA Claims</small>
          </Col>
          <Col md={2} className="text-center">
            <div className="fs-3 fw-bold text-success">{summary.matched?.toLocaleString()}</div>
            <small className="text-muted">Matched</small>
          </Col>
          <Col md={2} className="text-center">
            <div className="fs-3 fw-bold text-danger">{summary.unmatched?.toLocaleString()}</div>
            <small className="text-muted">Unmatched</small>
          </Col>
          <Col md={2} className="text-center">
            <div className="fs-3 fw-bold text-primary">{summary.billing_records_linked?.toLocaleString()}</div>
            <small className="text-muted">Billing Linked</small>
          </Col>
          <Col md={2} className="text-center">
            <div className="fs-3 fw-bold text-warning">{summary.denied_claims?.toLocaleString()}</div>
            <small className="text-muted">Denied</small>
          </Col>
          <Col md={2} className="text-center">
            <div className="fs-3 fw-bold">{rate}%</div>
            <small className="text-muted">Match Rate</small>
          </Col>
        </Row>
        <ProgressBar now={rate} variant={barVariant} label={`${rate}%`} style={{ height: 24 }} />

        {summary.by_confidence && (
          <Row className="g-2 mt-3">
            <Col><Badge bg="success" className="w-100 py-2">Exact (99%): {summary.by_confidence.exact_99}</Badge></Col>
            <Col><Badge bg="primary" className="w-100 py-2">Strong (95%): {summary.by_confidence.strong_95}</Badge></Col>
            <Col><Badge bg="info" className="w-100 py-2">Medium (85%): {summary.by_confidence.medium_85}</Badge></Col>
            <Col><Badge bg="warning" className="w-100 py-2">Amount (75%): {summary.by_confidence.amount_75}</Badge></Col>
            <Col><Badge bg="secondary" className="w-100 py-2">Weak (70%): {summary.by_confidence.weak_70}</Badge></Col>
          </Row>
        )}
      </Card.Body>
    </Card>
  );
}

function MatchedTable() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    setLoading(true);
    api.get("/matching/matched", { params: { page, per_page: 50 } })
      .then((r) => { setItems(r.data.items || []); setTotal(r.data.total || 0); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page]);

  if (loading) return <div className="text-center py-3"><Spinner animation="border" size="sm" /></div>;
  if (items.length === 0) return <Alert variant="info">No matched claims yet. Run the matcher first.</Alert>;

  const confidenceBadge = (c) => {
    if (c >= 0.95) return <Badge bg="success">{(c * 100).toFixed(0)}%</Badge>;
    if (c >= 0.85) return <Badge bg="primary">{(c * 100).toFixed(0)}%</Badge>;
    if (c >= 0.75) return <Badge bg="warning">{(c * 100).toFixed(0)}%</Badge>;
    return <Badge bg="secondary">{(c * 100).toFixed(0)}%</Badge>;
  };

  return (
    <>
      <p className="text-muted small">{total.toLocaleString()} matched claims</p>
      <Table size="sm" striped hover responsive className="small">
        <thead>
          <tr>
            <th>Confidence</th>
            <th>ERA Patient</th>
            <th>Billing Patient</th>
            <th>Date</th>
            <th>ERA Payer</th>
            <th>Billing Carrier</th>
            <th>CPT</th>
            <th>Modality</th>
            <th className="text-end">ERA Paid</th>
            <th className="text-end">Billing Total</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m, i) => (
            <tr key={i}>
              <td>{confidenceBadge(m.confidence)}</td>
              <td>{m.era_patient}</td>
              <td>{m.billing_patient}</td>
              <td>{m.service_date}</td>
              <td className="text-truncate" style={{ maxWidth: 120 }}>{m.era_payer}</td>
              <td>{m.carrier}</td>
              <td>{m.cpt_code}</td>
              <td>{m.modality}</td>
              <td className="text-end">{m.era_paid != null ? `$${m.era_paid.toLocaleString()}` : "--"}</td>
              <td className="text-end">{m.billing_total != null ? `$${m.billing_total.toLocaleString()}` : "--"}</td>
              <td><Badge bg={m.status === "DENIED" ? "danger" : "secondary"}>{m.status || "--"}</Badge></td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="d-flex justify-content-between">
        <Button size="sm" variant="outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
        <span className="text-muted small">Page {page}</span>
        <Button size="sm" variant="outline-secondary" disabled={items.length < 50} onClick={() => setPage(page + 1)}>Next</Button>
      </div>
    </>
  );
}

function UnmatchedTable() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    setLoading(true);
    api.get("/matching/unmatched", { params: { page, per_page: 50 } })
      .then((r) => { setItems(r.data.items || []); setTotal(r.data.total || 0); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page]);

  if (loading) return <div className="text-center py-3"><Spinner animation="border" size="sm" /></div>;
  if (items.length === 0) return <Alert variant="success">All ERA claims have been matched!</Alert>;

  return (
    <>
      <p className="text-muted small">{total.toLocaleString()} unmatched claims</p>
      <Table size="sm" striped hover responsive className="small">
        <thead>
          <tr>
            <th>Patient (835)</th>
            <th>Date</th>
            <th>Payer</th>
            <th>CPT</th>
            <th>Topaz ID</th>
            <th className="text-end">Billed</th>
            <th className="text-end">Paid</th>
            <th>Status</th>
            <th>Adj Code</th>
            <th>Source File</th>
          </tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.id}>
              <td>{c.patient_name || "--"}</td>
              <td>{c.service_date || "--"}</td>
              <td className="text-truncate" style={{ maxWidth: 120 }}>{c.payer_name || "--"}</td>
              <td>{c.cpt_code || "--"}</td>
              <td>{c.claim_id || "--"}</td>
              <td className="text-end">{c.billed_amount != null ? `$${c.billed_amount.toLocaleString()}` : "--"}</td>
              <td className="text-end">{c.paid_amount != null ? `$${c.paid_amount.toLocaleString()}` : "--"}</td>
              <td><Badge bg={c.claim_status === "DENIED" ? "danger" : "secondary"}>{c.claim_status || "--"}</Badge></td>
              <td>{c.cas_reason_code || "--"}</td>
              <td className="text-truncate" style={{ maxWidth: 150 }}>{c.source_file}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="d-flex justify-content-between">
        <Button size="sm" variant="outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
        <span className="text-muted small">Page {page}</span>
        <Button size="sm" variant="outline-secondary" disabled={items.length < 50} onClick={() => setPage(page + 1)}>Next</Button>
      </div>
    </>
  );
}

function CrosswalkTab() {
  const [stats, setStats] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [propagating, setPropagating] = useState(false);
  const [propagateResult, setPropagateResult] = useState(null);

  const loadData = () => {
    setLoading(true);
    Promise.allSettled([
      api.get("/matching/crosswalk/stats"),
      api.get("/matching/crosswalk/analyze"),
    ]).then(([statsRes, analysisRes]) => {
      if (statsRes.status === "fulfilled") setStats(statsRes.value.data);
      if (analysisRes.status === "fulfilled") setAnalysis(analysisRes.value.data);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const propagate = async (offset) => {
    setPropagating(true);
    setPropagateResult(null);
    try {
      const res = await api.post("/matching/crosswalk/propagate", { offset });
      setPropagateResult(res.data);
      loadData();
    } catch (err) {
      setPropagateResult({ status: "error", message: err.message });
    } finally {
      setPropagating(false);
    }
  };

  if (loading) return <div className="text-center py-3"><Spinner animation="border" size="sm" /></div>;

  return (
    <>
      <p className="text-muted small mb-3">
        Chart Number (from OCMRI.xlsx column M) &harr; Topaz ID (from ERA 835 claim_id).
        The matcher learns this crosswalk from confirmed matches.
      </p>

      {stats && (
        <Row className="g-3 mb-4">
          <Col md={3}><Card className="border-0 bg-light text-center p-3"><div className="fs-4 fw-bold">{stats.total_records?.toLocaleString()}</div><small>Total Records</small></Card></Col>
          <Col md={3}><Card className="border-0 bg-light text-center p-3"><div className="fs-4 fw-bold">{stats.has_chart_number?.toLocaleString()}</div><small>Have Chart #</small></Card></Col>
          <Col md={3}><Card className="border-0 bg-light text-center p-3"><div className="fs-4 fw-bold text-success">{stats.has_topaz_id?.toLocaleString()}</div><small>Have Topaz ID</small></Card></Col>
          <Col md={3}><Card className="border-0 bg-light text-center p-3"><div className="fs-4 fw-bold text-warning">{stats.missing_topaz?.toLocaleString()}</div><small>Missing Topaz ID</small></Card></Col>
        </Row>
      )}

      {analysis && analysis.total_pairs > 0 && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            <Card.Title>Discovered Patterns ({analysis.total_pairs} pairs analyzed)</Card.Title>
            <Table size="sm" className="small mb-3">
              <thead><tr><th>Pattern</th><th>Count</th></tr></thead>
              <tbody>
                <tr><td>Direct equality</td><td>{analysis.patterns?.direct_equal}</td></tr>
                <tr><td>Numeric offset</td><td>{analysis.patterns?.numeric_offset_total}</td></tr>
                <tr><td>String prefix</td><td>{analysis.patterns?.string_prefix}</td></tr>
                <tr><td>String suffix</td><td>{analysis.patterns?.string_suffix}</td></tr>
                <tr><td>No pattern found</td><td>{analysis.patterns?.no_pattern}</td></tr>
              </tbody>
            </Table>

            {analysis.dominant_offset != null && (
              <Alert variant="info">
                <strong>Dominant pattern:</strong> topaz_id = chart_number + {analysis.dominant_offset}{" "}
                ({analysis.dominant_offset_pct}% of pairs)
                <Button
                  variant="outline-primary"
                  size="sm"
                  className="ms-3"
                  disabled={propagating}
                  onClick={() => propagate(analysis.dominant_offset)}
                >
                  {propagating ? "Propagating..." : `Apply offset +${analysis.dominant_offset} to missing records`}
                </Button>
              </Alert>
            )}

            {analysis.patterns?.top_offsets?.length > 1 && (
              <>
                <strong className="small">All offsets found:</strong>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Offset</th><th>Count</th><th></th></tr></thead>
                  <tbody>
                    {analysis.patterns.top_offsets.map((o, i) => (
                      <tr key={i}>
                        <td>chart + {o.offset}</td>
                        <td>{o.count}</td>
                        <td><Button size="sm" variant="outline-secondary" onClick={() => propagate(o.offset)}>Apply</Button></td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </>
            )}

            {propagateResult && (
              <Alert variant={propagateResult.status === "success" ? "success" : "warning"} className="mt-3">
                {propagateResult.status === "success"
                  ? `Propagated topaz_id to ${propagateResult.propagated} records using offset +${propagateResult.offset_used}`
                  : propagateResult.message}
              </Alert>
            )}

            {analysis.sample_pairs?.length > 0 && (
              <>
                <strong className="small">Sample crosswalk pairs:</strong>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Patient</th><th>Chart #</th><th>Topaz ID</th><th>Offset</th></tr></thead>
                  <tbody>
                    {analysis.sample_pairs.slice(0, 10).map((p, i) => {
                      let offset = "--";
                      try { offset = parseInt(p.topaz_id) - parseInt(p.chart_number); } catch (e) {}
                      return (
                        <tr key={i}>
                          <td>{p.patient}</td>
                          <td>{p.chart_number}</td>
                          <td>{p.topaz_id}</td>
                          <td>{offset}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              </>
            )}
          </Card.Body>
        </Card>
      )}

      {analysis && analysis.total_pairs === 0 && (
        <Alert variant="info">
          No crosswalk data yet. Run the auto-matcher first &mdash; it will learn chart# &harr; Topaz ID
          mappings from name/date/amount matches.
        </Alert>
      )}
    </>
  );
}

function Matching() {
  const [summary, setSummary] = useState(null);
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [error, setError] = useState(null);

  const loadSummary = () => {
    api.get("/matching/summary").then((r) => setSummary(r.data)).catch(() => {});
  };

  useEffect(() => { loadSummary(); }, []);

  const runMatcher = async () => {
    setRunning(true);
    setError(null);
    setLastResult(null);
    try {
      const res = await api.post("/matching/run", {}, { timeout: 300000 });
      setLastResult(res.data);
      loadSummary();
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <h2 className="mb-4">Data Matching &amp; Association</h2>

      <MatchSummary summary={summary} />

      <Card className="border-0 shadow-sm mb-4">
        <Card.Body>
          <div className="d-flex align-items-center gap-3">
            <Button variant="primary" size="lg" onClick={runMatcher} disabled={running}>
              {running ? <><Spinner size="sm" className="me-2" /> Matching...</> : "Run Auto-Match Engine"}
            </Button>
            <span className="text-muted small">
              6-pass matching: Topaz ID crosswalk + name/date/amount fuzzy
            </span>
          </div>

          {error && <Alert variant="danger" className="mt-3">{error}</Alert>}

          {lastResult && (
            <Alert variant={lastResult.matched_total > 0 ? "success" : "info"} className="mt-3">
              <strong>Matching complete!</strong>{" "}
              {lastResult.matched_total}/{lastResult.total} claims matched ({lastResult.match_rate}%)
              {lastResult.pass_0_topaz_id > 0 && <span> &mdash; Topaz ID: {lastResult.pass_0_topaz_id}</span>}
              {lastResult.pass_1_exact > 0 && <span> &mdash; Exact: {lastResult.pass_1_exact}</span>}
              {lastResult.pass_2_strong > 0 && <span> &mdash; Strong: {lastResult.pass_2_strong}</span>}
              {lastResult.pass_3_medium > 0 && <span> &mdash; Medium: {lastResult.pass_3_medium}</span>}
              {lastResult.pass_4_weak > 0 && <span> &mdash; Weak: {lastResult.pass_4_weak}</span>}
              {lastResult.pass_5_amount > 0 && <span> &mdash; Amount: {lastResult.pass_5_amount}</span>}
            </Alert>
          )}
        </Card.Body>
      </Card>

      <Tabs defaultActiveKey="matched" className="mb-3">
        <Tab eventKey="matched" title="Matched Claims">
          <MatchedTable />
        </Tab>
        <Tab eventKey="unmatched" title="Unmatched Claims">
          <UnmatchedTable />
        </Tab>
        <Tab eventKey="crosswalk" title="ID Crosswalk">
          <CrosswalkTab />
        </Tab>
      </Tabs>
    </>
  );
}

export default Matching;
