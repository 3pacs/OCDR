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

function TopazUpload({ onImported }) {
  const [uploading, setUploading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [result, setResult] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const fileRef = React.useRef();

  const handlePreview = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setPreviewing(true);
    setError(null);
    setPreview(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await api.post("/matching/crosswalk/preview-topaz", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });
      setPreview(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.response?.data?.message || err.message);
    } finally {
      setPreviewing(false);
    }
  };

  const handleImport = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await api.post("/matching/crosswalk/import-topaz", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 300000,
      });
      setResult(res.data);
      if (onImported) onImported();
    } catch (err) {
      setError(err.response?.data?.detail || err.response?.data?.message || err.message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <Card className="border-0 shadow-sm mb-4">
      <Card.Body>
        <Card.Title>Upload Topaz Export</Card.Title>
        <p className="text-muted small mb-3">
          Upload a data export from the Topaz billing server to map Chart Numbers to Topaz IDs.
          Supports any format &mdash; pipe-delimited, tab, CSV, XML, or extensionless .NET files.
        </p>

        <div className="d-flex align-items-center gap-2 mb-3">
          <input type="file" ref={fileRef} className="form-control form-control-sm" style={{ maxWidth: 350 }}
            onChange={() => { setPreview(null); setResult(null); setError(null); }} />
          <Button variant="outline-secondary" size="sm" onClick={handlePreview}
            disabled={previewing || uploading}>
            {previewing ? <><Spinner size="sm" className="me-1" />Previewing...</> : "Preview"}
          </Button>
          <Button variant="primary" size="sm" onClick={handleImport}
            disabled={uploading || previewing}>
            {uploading ? <><Spinner size="sm" className="me-1" />Importing...</> : "Import & Apply"}
          </Button>
        </div>

        {error && <Alert variant="danger" className="small">{error}</Alert>}

        {preview && (
          <Alert variant="info" className="small">
            <strong>Preview:</strong> Detected format: <Badge bg="secondary">{preview.format}</Badge>{" "}
            &mdash; {preview.total_rows} rows found
            {preview.column_mapping && Object.keys(preview.column_mapping).length > 0 && (
              <span> &mdash; Mapped: {Object.entries(preview.column_mapping).map(([k, v]) =>
                <Badge key={k} bg="outline-dark" className="border me-1">{k} &larr; &ldquo;{v}&rdquo;</Badge>
              )}</span>
            )}
            {preview.warnings?.length > 0 && (
              <div className="mt-1 text-warning">Warnings: {preview.warnings.join("; ")}</div>
            )}
            {preview.sample_pairs?.length > 0 && (
              <Table size="sm" className="mt-2 mb-0 small">
                <thead><tr><th>Chart #</th><th>Topaz ID</th><th>Patient</th></tr></thead>
                <tbody>
                  {preview.sample_pairs.slice(0, 5).map((p, i) => (
                    <tr key={i}>
                      <td>{p.chart_number || "--"}</td>
                      <td>{p.topaz_id || "--"}</td>
                      <td>{p.patient_name || "--"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Alert>
        )}

        {result && (
          <Alert variant={result.crosswalk_applied?.applied > 0 ? "success" : "warning"} className="small">
            {result.status === "no_crosswalk_data" ? (
              <>{result.message}</>
            ) : (
              <>
                <strong>Import complete!</strong>{" "}
                {result.total_rows_parsed} rows parsed from <Badge bg="secondary">{result.format}</Badge> file.{" "}
                {result.crosswalk_applied?.applied > 0
                  ? <>Applied Topaz ID to <strong>{result.crosswalk_applied.applied}</strong> billing records
                    ({result.crosswalk_applied.by_chart_number} by chart#, {result.crosswalk_applied.by_name_match} by name).
                  </>
                  : "No new records needed updating."
                }
                {result.warnings?.length > 0 && (
                  <div className="mt-1 text-warning">Warnings: {result.warnings.join("; ")}</div>
                )}
              </>
            )}
          </Alert>
        )}
      </Card.Body>
    </Card>
  );
}

function FileVerifier() {
  const [verifying, setVerifying] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const fileRef = React.useRef();

  const handleVerify = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setVerifying(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await api.post("/matching/crosswalk/verify-file", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setVerifying(false);
    }
  };

  const verdictColor = (v) => {
    if (v === "jacket_id_list") return "success";
    if (v === "topaz_id_list") return "info";
    if (v === "multi_field") return "primary";
    return "secondary";
  };

  return (
    <Card className="border-0 shadow-sm mb-4">
      <Card.Body>
        <Card.Title>Verify File Against Records</Card.Title>
        <p className="text-muted small mb-3">
          Upload any file (extensionless .NET exports, text, etc.) to test whether its
          contents match Jacket IDs or Topaz IDs in your billing records.
        </p>

        <div className="d-flex align-items-center gap-2 mb-3">
          <input type="file" ref={fileRef} className="form-control form-control-sm" style={{ maxWidth: 350 }}
            onChange={() => { setResult(null); setError(null); }} />
          <Button variant="outline-primary" size="sm" onClick={handleVerify} disabled={verifying}>
            {verifying ? <><Spinner size="sm" className="me-1" />Verifying...</> : "Test File"}
          </Button>
        </div>

        {error && <Alert variant="danger" className="small">{error}</Alert>}

        {result && result.verdict === "fixed_width" && (
          <>
            <Alert variant="primary" className="small">
              <strong>Fixed-Width Record File</strong> &mdash; {result.verdict_detail}
            </Alert>

            <Row className="g-2 mb-3">
              <Col md={3}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.total_records?.toLocaleString()}</div><small>Total Records</small></div></Col>
              <Col md={3}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.record_width} bytes</div><small>Record Width</small></div></Col>
              <Col md={3}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.field_zones?.length}</div><small>Field Zones</small></div></Col>
              <Col md={3}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.unique_jacket_ids_in_db}</div><small>Jacket IDs in DB</small></div></Col>
            </Row>

            {result.position_crosswalk && (
              <Row className="g-2 mb-3">
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.position_crosswalk.total_known_topaz_ids}</div><small>Known Topaz IDs</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.position_crosswalk.total_checked}</div><small>Positions Checked</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-success">{result.position_crosswalk.name_corroborated}</div><small>Name Corroborated</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-danger">{result.position_crosswalk.name_mismatch}</div><small>Name Mismatch</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-primary">{result.position_crosswalk.corroboration_rate}%</div><small>Corroboration Rate</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.unique_topaz_ids_in_db}</div><small>Topaz IDs in DB</small></div></Col>
              </Row>
            )}

            {result.sample_corroborated?.length > 0 && (
              <details className="mb-3" open>
                <summary className="small fw-bold text-success">
                  Corroborated Matches &mdash; line# = Topaz ID, name verified
                </summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Line#/Topaz ID</th><th>File Name</th><th>DB Patient</th><th>Jacket ID</th><th>Name Match</th></tr></thead>
                  <tbody>
                    {result.sample_corroborated.map((m, i) => (
                      <tr key={i}>
                        <td><code>{m.topaz_id}</code></td>
                        <td>{m.file_name || <span className="text-muted">--</span>}</td>
                        <td>{m.db_patient}</td>
                        <td>{m.db_jacket_id || "--"}</td>
                        <td><Badge bg={m.name_similarity >= 85 ? "success" : m.name_similarity >= 70 ? "warning" : "danger"}>{m.name_similarity}%</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.sample_mismatches?.length > 0 && (
              <details className="mb-3" open>
                <summary className="small fw-bold text-danger">
                  Name Mismatches &mdash; line# matched Topaz ID but name doesn&apos;t match
                </summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Line#/Topaz ID</th><th>File Name</th><th>DB Patient</th><th>Jacket ID</th><th>Similarity</th></tr></thead>
                  <tbody>
                    {result.sample_mismatches.map((m, i) => (
                      <tr key={i}>
                        <td><code>{m.topaz_id}</code></td>
                        <td>{m.file_name || "--"}</td>
                        <td>{m.db_patient}</td>
                        <td>{m.db_jacket_id || "--"}</td>
                        <td><Badge bg="danger">{m.name_similarity}%</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.jacket_id_cross_ref?.length > 0 && (
              <details className="mb-3">
                <summary className="small fw-bold">
                  Jacket ID Cross-Ref &mdash; data fields matching Jacket IDs at other positions
                </summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Line#</th><th>Field</th><th>Jacket ID</th><th>File Name</th><th>DB Patient</th><th>DB Topaz</th><th>Name Match</th></tr></thead>
                  <tbody>
                    {result.jacket_id_cross_ref.map((m, i) => (
                      <tr key={i}>
                        <td>{m.line_num}</td>
                        <td><Badge bg="secondary">{m.id_field}</Badge></td>
                        <td><code>{m.id_value}</code></td>
                        <td>{m.file_name || "--"}</td>
                        <td>{m.db_patient}</td>
                        <td>{m.db_topaz_id || "--"}</td>
                        <td>{m.name_similarity != null ? <Badge bg={m.name_similarity >= 85 ? "success" : m.name_similarity >= 70 ? "warning" : "danger"}>{m.name_similarity}%</Badge> : "--"}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.field_zones?.length > 0 && (
              <details className="mb-3">
                <summary className="small fw-bold">Field Zones (byte positions)</summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Label</th><th>Pos</th><th>Width</th><th>Type</th><th>Sample Values</th></tr></thead>
                  <tbody>
                    {result.field_zones.map((z, i) => (
                      <tr key={i} className={z.label.startsWith("id_") ? "table-info" : z.label.startsWith("name_") ? "table-success" : z.label.startsWith("date_") ? "table-warning" : ""}>
                        <td><strong>{z.label}</strong></td>
                        <td>{z.start}-{z.end}</td>
                        <td>{z.width}</td>
                        <td><Badge bg={z.type === "digit" ? "info" : z.type === "alpha" ? "success" : z.type === "date" ? "warning" : "secondary"}>{z.type}</Badge></td>
                        <td className="text-truncate" style={{ maxWidth: 300 }}>{z.sample_values?.slice(0, 3).map((v, j) => <code key={j} className="me-2">{v}</code>)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.sample_records?.length > 0 && (
              <details className="mb-3">
                <summary className="small fw-bold">Sample Records (first 10)</summary>
                <pre className="bg-light p-2 small mt-1" style={{ maxHeight: 250, overflow: "auto" }}>
                  {result.sample_records.slice(0, 10).map((r, i) =>
                    `Record ${r._line_num || i + 1} (Topaz ID ${r._topaz_id || "?"}): ${JSON.stringify(
                      Object.fromEntries(Object.entries(r).filter(([k]) => !k.startsWith("_")))
                    )}`
                  ).join("\n")}
                </pre>
              </details>
            )}
          </>
        )}

        {result && result.verdict !== "fixed_width" && (
          <>
            <Alert variant={verdictColor(result.verdict)} className="small">
              <strong>Verdict: <Badge bg={verdictColor(result.verdict)}>{result.verdict}</Badge></strong>{" "}
              &mdash; {result.verdict_detail}
            </Alert>

            <Row className="g-2 mb-3">
              <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.total_lines}</div><small>Total Lines</small></div></Col>
              <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-success">{result.jacket_id_matches}</div><small>Jacket ID Matches</small></div></Col>
              <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-info">{result.topaz_id_matches}</div><small>Topaz ID Matches</small></div></Col>
              <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-primary">{result.multi_field_lines}</div><small>Multi-field Lines</small></div></Col>
              <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-muted">{result.no_match}</div><small>No Match</small></div></Col>
              <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{result.unique_jacket_ids_in_db}</div><small>Jacket IDs in DB</small></div></Col>
            </Row>

            {result.first_10_lines?.length > 0 && (
              <details className="mb-3">
                <summary className="small fw-bold">First 10 lines of file</summary>
                <pre className="bg-light p-2 small mt-1" style={{ maxHeight: 200, overflow: "auto" }}>
                  {result.first_10_lines.map((l, i) => `${i + 1}: ${l}`).join("\n")}
                </pre>
              </details>
            )}

            {result.sample_jacket_matches?.length > 0 && (
              <details className="mb-3" open>
                <summary className="small fw-bold">Jacket ID Matches (sample)</summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Line</th><th>Value</th><th>Patient</th><th>Topaz ID</th><th>Records</th></tr></thead>
                  <tbody>
                    {result.sample_jacket_matches.slice(0, 15).map((m, i) => (
                      <tr key={i}>
                        <td>{m.line_num}</td>
                        <td><code>{m.value}</code></td>
                        <td>{m.sample_patient}</td>
                        <td>{m.sample_topaz || "--"}</td>
                        <td>{m.record_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.sample_topaz_matches?.length > 0 && (
              <details className="mb-3" open>
                <summary className="small fw-bold">Topaz ID Matches (sample)</summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Line</th><th>Value</th><th>Patient</th><th>Jacket ID</th><th>Records</th></tr></thead>
                  <tbody>
                    {result.sample_topaz_matches.slice(0, 15).map((m, i) => (
                      <tr key={i}>
                        <td>{m.line_num}</td>
                        <td><code>{m.value}</code></td>
                        <td>{m.sample_patient}</td>
                        <td>{m.sample_patient_id || "--"}</td>
                        <td>{m.record_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.sample_field_analysis?.length > 0 && (
              <details className="mb-3" open>
                <summary className="small fw-bold">Multi-field Line Analysis (sample)</summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Line</th><th>Fields</th><th>Matched Field</th><th>Match Type</th><th>Patient</th></tr></thead>
                  <tbody>
                    {result.sample_field_analysis.slice(0, 15).map((fa, i) => (
                      <tr key={i}>
                        <td>{fa.line_num}</td>
                        <td className="text-truncate" style={{ maxWidth: 250 }}><code>{fa.fields.join(" | ")}</code></td>
                        <td>{fa.matches.map(m => <Badge key={m.field_index} bg="light" text="dark" className="me-1">col {m.field_index}: {m.value}</Badge>)}</td>
                        <td>{fa.matches.map(m => <Badge key={m.field_index} bg={m.match_type === "jacket_id" ? "success" : "info"} className="me-1">{m.match_type}</Badge>)}</td>
                        <td>{fa.matches[0]?.sample_patient}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.sample_no_match?.length > 0 && (
              <details className="mb-3">
                <summary className="small fw-bold">Unmatched Lines (sample)</summary>
                <pre className="bg-light p-2 small mt-1" style={{ maxHeight: 150, overflow: "auto" }}>
                  {result.sample_no_match.map(m => `Line ${m.line_num}: ${m.value}`).join("\n")}
                </pre>
              </details>
            )}
          </>
        )}
      </Card.Body>
    </Card>
  );
}

function IntegrityCheck() {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const runCheck = async () => {
    setChecking(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.get("/matching/crosswalk/integrity", { timeout: 120000 });
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setChecking(false);
    }
  };

  return (
    <Card className="border-0 shadow-sm mb-4">
      <Card.Body>
        <div className="d-flex align-items-center justify-content-between mb-2">
          <Card.Title className="mb-0">Crosswalk Integrity Check</Card.Title>
          <Button variant="outline-warning" size="sm" onClick={runCheck} disabled={checking}>
            {checking ? <><Spinner size="sm" className="me-1" />Checking...</> : "Run Integrity Check"}
          </Button>
        </div>
        <p className="text-muted small mb-3">
          Audits all matched claims and crosswalk pairs for inconsistencies:
          conflicting ID mappings, patient name mismatches, and date discrepancies.
        </p>

        {error && <Alert variant="danger" className="small">{error}</Alert>}

        {result && (
          <>
            <Alert variant={result.status === "clean" ? "success" : "warning"} className="small">
              {result.status === "clean"
                ? <><strong>Clean!</strong> No integrity issues found across {result.total_crosswalk_pairs} crosswalk pairs and {result.total_matched_claims} matched claims.</>
                : <><strong>{result.issues_found} issues found</strong> across {result.total_crosswalk_pairs} crosswalk pairs and {result.total_matched_claims} matched claims.</>
              }
            </Alert>

            {result.summary && result.issues_found > 0 && (
              <Row className="g-2 mb-3">
                <Col md={3}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-danger">{result.summary.jacket_conflicts}</div><small>Jacket ID Conflicts</small></div></Col>
                <Col md={3}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-danger">{result.summary.topaz_conflicts}</div><small>Topaz ID Conflicts</small></div></Col>
                <Col md={3}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-warning">{result.summary.name_mismatches}</div><small>Name Mismatches</small></div></Col>
                <Col md={3}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-warning">{result.summary.date_mismatches}</div><small>Date Mismatches</small></div></Col>
              </Row>
            )}

            {result.conflicting_jacket_to_topaz?.length > 0 && (
              <details className="mb-3" open>
                <summary className="small fw-bold text-danger">
                  Jacket ID Conflicts &mdash; same Jacket ID maps to multiple Topaz IDs
                </summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Jacket ID</th><th>Topaz IDs</th><th>Patient(s)</th><th>Records</th></tr></thead>
                  <tbody>
                    {result.conflicting_jacket_to_topaz.map((c, i) => (
                      <tr key={i}>
                        <td><code>{c.jacket_id}</code></td>
                        <td>{c.topaz_ids.map(t => <Badge key={t} bg="danger" className="me-1">{t}</Badge>)}</td>
                        <td>{c.patient_names.join(", ")}</td>
                        <td>{c.record_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.conflicting_topaz_to_jacket?.length > 0 && (
              <details className="mb-3" open>
                <summary className="small fw-bold text-danger">
                  Topaz ID Conflicts &mdash; same Topaz ID maps to multiple Jacket IDs
                </summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Topaz ID</th><th>Jacket IDs</th><th>Patient(s)</th><th>Records</th></tr></thead>
                  <tbody>
                    {result.conflicting_topaz_to_jacket.map((c, i) => (
                      <tr key={i}>
                        <td><code>{c.topaz_id}</code></td>
                        <td>{c.jacket_ids.map(j => <Badge key={j} bg="danger" className="me-1">{j}</Badge>)}</td>
                        <td>{c.patient_names.join(", ")}</td>
                        <td>{c.record_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.name_mismatches?.length > 0 && (
              <details className="mb-3" open>
                <summary className="small fw-bold text-warning">
                  Name Mismatches &mdash; matched claims where ERA and billing patient names differ significantly
                </summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Claim ID</th><th>ERA Patient</th><th>Billing Patient</th><th>Similarity</th><th>Confidence</th><th>Jacket ID</th></tr></thead>
                  <tbody>
                    {result.name_mismatches.map((m, i) => (
                      <tr key={i}>
                        <td><code>{m.claim_id}</code></td>
                        <td>{m.era_patient}</td>
                        <td>{m.billing_patient}</td>
                        <td><Badge bg={m.name_similarity < 50 ? "danger" : "warning"}>{m.name_similarity}%</Badge></td>
                        <td>{m.confidence ? `${(m.confidence * 100).toFixed(0)}%` : "--"}</td>
                        <td>{m.jacket_id || "--"}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {result.date_mismatches?.length > 0 && (
              <details className="mb-3">
                <summary className="small fw-bold text-warning">
                  Date Mismatches &mdash; matched claims with service dates more than 3 days apart
                </summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>Claim ID</th><th>ERA Date</th><th>Billing Date</th><th>Days Apart</th><th>Patient</th></tr></thead>
                  <tbody>
                    {result.date_mismatches.map((m, i) => (
                      <tr key={i}>
                        <td><code>{m.claim_id}</code></td>
                        <td>{m.era_date}</td>
                        <td>{m.billing_date}</td>
                        <td><Badge bg="warning">{m.days_apart}</Badge></td>
                        <td>{m.era_patient}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}
          </>
        )}
      </Card.Body>
    </Card>
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
      <IntegrityCheck />
      <FileVerifier />
      <TopazUpload onImported={loadData} />

      <p className="text-muted small mb-3">
        Jacket ID &harr; Topaz ID mapping from your OCMRI spreadsheet.
        Both IDs are imported directly &mdash; no offset calculation needed.
      </p>

      {stats && (
        <Row className="g-3 mb-4">
          <Col md={3}><Card className="border-0 bg-light text-center p-3"><div className="fs-4 fw-bold">{stats.total_records?.toLocaleString()}</div><small>Total Records</small></Card></Col>
          <Col md={3}><Card className="border-0 bg-light text-center p-3"><div className="fs-4 fw-bold">{stats.has_chart_number?.toLocaleString()}</div><small>Have Jacket ID</small></Card></Col>
          <Col md={3}><Card className="border-0 bg-light text-center p-3"><div className="fs-4 fw-bold text-success">{stats.has_topaz_id?.toLocaleString()}</div><small>Have Topaz ID</small></Card></Col>
          <Col md={3}><Card className="border-0 bg-light text-center p-3"><div className="fs-4 fw-bold text-warning">{stats.missing_topaz?.toLocaleString()}</div><small>Missing Topaz ID</small></Card></Col>
        </Row>
      )}

      {analysis && analysis.total_pairs > 0 && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            {analysis.mapping_type === "direct" ? (
              <>
                <Card.Title>
                  Direct Mapping &mdash; {analysis.total_pairs} Jacket ID / Topaz ID pairs
                </Card.Title>
                <Alert variant="success" className="mb-3">
                  Both IDs are imported from the OCMRI spreadsheet. Each patient&apos;s Jacket ID maps
                  directly to their Topaz ID &mdash; no numeric offset or formula.
                  The auto-matcher uses Topaz ID for instant claim matching (Pass 0).
                </Alert>
                <Row className="g-3 mb-3">
                  <Col md={4}><div className="text-center"><div className="fs-5 fw-bold">{analysis.unique_jacket_ids}</div><small className="text-muted">Unique Jacket IDs</small></div></Col>
                  <Col md={4}><div className="text-center"><div className="fs-5 fw-bold">{analysis.unique_topaz_ids}</div><small className="text-muted">Unique Topaz IDs</small></div></Col>
                  <Col md={4}><div className="text-center"><div className="fs-5 fw-bold">{analysis.total_pairs}</div><small className="text-muted">Total Pairs</small></div></Col>
                </Row>
              </>
            ) : analysis.mapping_type === "offset" ? (
              <>
                <Card.Title>Offset Pattern ({analysis.total_pairs} pairs analyzed)</Card.Title>
                <Alert variant="info">
                  <strong>Dominant pattern:</strong> topaz_id = jacket_id + {analysis.dominant_offset}{" "}
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
              </>
            ) : (
              <>
                <Card.Title>Crosswalk Analysis ({analysis.total_pairs} pairs)</Card.Title>
                <Table size="sm" className="small mb-3">
                  <thead><tr><th>Pattern</th><th>Count</th></tr></thead>
                  <tbody>
                    <tr><td>Direct equality</td><td>{analysis.patterns?.direct_equal}</td></tr>
                    <tr><td>Numeric offset</td><td>{analysis.patterns?.numeric_offset_total} ({analysis.patterns?.unique_offsets} unique)</td></tr>
                    <tr><td>String prefix</td><td>{analysis.patterns?.string_prefix}</td></tr>
                    <tr><td>String suffix</td><td>{analysis.patterns?.string_suffix}</td></tr>
                    <tr><td>Independent IDs</td><td>{analysis.patterns?.no_pattern}</td></tr>
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
                  <thead><tr><th>Patient</th><th>Jacket ID</th><th>Topaz ID</th></tr></thead>
                  <tbody>
                    {analysis.sample_pairs.slice(0, 10).map((p, i) => (
                      <tr key={i}>
                        <td>{p.patient}</td>
                        <td>{p.jacket_id}</td>
                        <td>{p.topaz_id}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </>
            )}
          </Card.Body>
        </Card>
      )}

      {analysis && analysis.total_pairs === 0 && (
        <Alert variant="info">
          No crosswalk data yet. Import your OCMRI spreadsheet &mdash; both the Jacket ID
          and Topaz ID columns will be mapped automatically.
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
      const res = await api.post("/matching/run", {}, { timeout: 900000 });
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
