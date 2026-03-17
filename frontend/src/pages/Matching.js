import React, { useState, useEffect } from "react";
import { Card, Row, Col, Button, Alert, Spinner, Table, Badge, Tab, Tabs, ProgressBar, Form as BsForm } from "react-bootstrap";
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
  // 3-step flow: Upload → Map/Extract → Apply
  const [step, setStep] = useState("upload"); // upload | map | applied
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [uploadResult, setUploadResult] = useState(null); // from upload-raw
  const [extractResult, setExtractResult] = useState(null); // from extract
  const [applyResult, setApplyResult] = useState(null); // from apply
  const [fieldMapping, setFieldMapping] = useState({});
  const [pastImports, setPastImports] = useState([]);
  const fileRef = React.useRef();

  const ROLE_OPTIONS = [
    { value: "", label: "-- ignore --" },
    { value: "chart_number", label: "Chart / Jacket #" },
    { value: "patient_name", label: "Patient Name" },
    { value: "topaz_id", label: "Topaz ID" },
    { value: "service_date", label: "Service Date" },
  ];

  // Load past imports on mount
  useEffect(() => {
    api.get("/matching/crosswalk/imports").then(r => setPastImports(r.data)).catch(() => {});
  }, [applyResult]);

  // ── Step 1: Upload raw file ──
  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    setUploadResult(null);
    setExtractResult(null);
    setApplyResult(null);
    setFieldMapping({});
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await api.post("/matching/crosswalk/upload-raw", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });
      setUploadResult(res.data);
      // Seed field mapping from auto-detected mapping
      const meta = res.data.parsing_metadata;
      if (meta?.auto_mapping) {
        setFieldMapping(meta.auto_mapping);
      }
      setStep("map");
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  // ── Step 2: Extract crosswalk pairs using user's mapping ──
  const handleExtract = async () => {
    if (!uploadResult?.id) return;
    if (!fieldMapping.chart_number && !fieldMapping.patient_name) {
      setError("Assign at least Chart/Jacket # or Patient Name before extracting.");
      return;
    }
    setLoading(true);
    setError(null);
    setExtractResult(null);
    try {
      // For fixed-width: always default topaz_id to line number
      const mapping = { ...fieldMapping };
      if (uploadResult.format === "fixed_width" && !mapping.topaz_id) {
        mapping.topaz_id = "_line_num";
      }
      const res = await api.post(`/matching/crosswalk/extract/${uploadResult.id}`, mapping);
      setExtractResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  // ── Step 3: Apply to billing records ──
  const handleApply = async () => {
    if (!uploadResult?.id) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.post(`/matching/crosswalk/apply/${uploadResult.id}`);
      setApplyResult(res.data);
      setStep("applied");
      if (onImported) onImported();
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  // Reset to start over
  const handleReset = () => {
    setStep("upload");
    setUploadResult(null);
    setExtractResult(null);
    setApplyResult(null);
    setFieldMapping({});
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  // View a past import
  const handleViewImport = async (id) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get(`/matching/crosswalk/imports/${id}`);
      const data = res.data;
      setUploadResult({
        id: data.id,
        filename: data.filename,
        format: data.format,
        format_detail: data.format_detail,
        total_records: data.total_records,
        parsing_metadata: data.parsing_metadata,
      });
      if (data.field_mapping) setFieldMapping(data.field_mapping);
      if (data.status === "APPLIED") {
        setExtractResult({ extracted_count: data.extracted_count, sample_pairs: data.sample_pairs });
        setApplyResult({ apply_result: data.apply_result });
        setStep("applied");
      } else if (data.status === "MAPPED") {
        setExtractResult({ extracted_count: data.extracted_count, sample_pairs: data.sample_pairs, validation: {} });
        setStep("map");
      } else {
        setStep("map");
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  // Helpers for zone role assignment (fixed-width)
  const handleZoneRoleChange = (zoneLabel, newRole) => {
    setFieldMapping(prev => {
      const next = { ...prev };
      for (const [role, label] of Object.entries(next)) {
        if (label === zoneLabel) delete next[role];
      }
      if (newRole) {
        delete next[newRole];
        next[newRole] = zoneLabel;
      }
      return next;
    });
    setExtractResult(null); // Clear stale extract when mapping changes
  };

  const getZoneRole = (zoneLabel) => {
    for (const [role, label] of Object.entries(fieldMapping)) {
      if (label === zoneLabel) return role;
    }
    return "";
  };

  const meta = uploadResult?.parsing_metadata;
  const isFixedWidth = uploadResult?.format === "fixed_width";

  // Live preview from sample records
  const liveRows = (() => {
    if (!isFixedWidth || !meta?.sample_records) return null;
    const chartField = fieldMapping.chart_number;
    const nameField = fieldMapping.patient_name;
    if (!chartField && !nameField) return null;
    return meta.sample_records.slice(0, 10).map(rec => ({
      topaz_id: rec._line_num,
      chart_number: chartField ? (rec[chartField] || "") : "",
      patient_name: nameField ? (rec[nameField] || "") : "",
    }));
  })();

  return (
    <Card className="border-0 shadow-sm mb-4">
      <Card.Body>
        <Card.Title className="d-flex justify-content-between align-items-center">
          Crosswalk Import
          {step !== "upload" && (
            <Button variant="outline-secondary" size="sm" onClick={handleReset}>Start Over</Button>
          )}
        </Card.Title>
        <p className="text-muted small mb-3">
          Upload raw data files, examine the contents, assign field mappings, then apply to billing records.
          No auto-guessing &mdash; you control which fields map to what.
        </p>

        {/* Step indicator */}
        <div className="d-flex gap-2 mb-3">
          <Badge bg={step === "upload" ? "primary" : "success"} className="px-3 py-2">
            1. Upload{step !== "upload" && " \u2713"}
          </Badge>
          <Badge bg={step === "map" ? "primary" : step === "applied" ? "success" : "secondary"} className="px-3 py-2">
            2. Map &amp; Extract{step === "applied" && " \u2713"}
          </Badge>
          <Badge bg={step === "applied" ? "success" : "secondary"} className="px-3 py-2">
            3. Apply{step === "applied" && " \u2713"}
          </Badge>
        </div>

        {error && <Alert variant="danger" className="small" dismissible onClose={() => setError(null)}>{error}</Alert>}

        {/* ══════════════ STEP 1: Upload ══════════════ */}
        {step === "upload" && (
          <>
            <div className="d-flex align-items-center gap-2 mb-3">
              <input type="file" ref={fileRef} className="form-control form-control-sm" style={{ maxWidth: 400 }} />
              <Button variant="primary" size="sm" onClick={handleUpload} disabled={loading}>
                {loading ? <><Spinner size="sm" className="me-1" />Uploading...</> : "Upload & Examine"}
              </Button>
            </div>

            {/* Past imports */}
            {pastImports.length > 0 && (
              <details className="mb-2">
                <summary className="small fw-bold">Past Imports ({pastImports.length})</summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr><th>File</th><th>Format</th><th>Records</th><th>Status</th><th>Extracted</th><th>Applied</th><th>Date</th><th></th></tr></thead>
                  <tbody>
                    {pastImports.map(imp => (
                      <tr key={imp.id}>
                        <td>{imp.filename}</td>
                        <td><Badge bg="secondary">{imp.format}</Badge></td>
                        <td>{imp.total_records?.toLocaleString()}</td>
                        <td><Badge bg={imp.status === "APPLIED" ? "success" : imp.status === "MAPPED" ? "info" : "secondary"}>{imp.status}</Badge></td>
                        <td>{imp.extracted_count || "--"}</td>
                        <td>{imp.applied_count || "--"}</td>
                        <td>{imp.created_at ? new Date(imp.created_at).toLocaleDateString() : "--"}</td>
                        <td><Button variant="outline-primary" size="sm" onClick={() => handleViewImport(imp.id)}>View</Button></td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}
          </>
        )}

        {/* ══════════════ STEP 2: Map & Extract ══════════════ */}
        {step === "map" && uploadResult && (
          <>
            <Alert variant="info" className="small mb-3">
              <strong>File:</strong> {uploadResult.filename} &mdash;{" "}
              <Badge bg="secondary">{uploadResult.format}</Badge>{" "}
              {uploadResult.format_detail && <span>&mdash; {uploadResult.format_detail}</span>}
              {" "}({uploadResult.total_records?.toLocaleString()} records stored)
              {meta?.warnings?.length > 0 && (
                <div className="mt-1 text-warning">Warnings: {meta.warnings.join("; ")}</div>
              )}
            </Alert>

            {/* ── Fixed-width: zone table with role dropdowns ── */}
            {isFixedWidth && meta?.field_zones && (
              <div className="mb-3">
                <h6 className="mb-2">Assign Field Roles</h6>
                <p className="text-muted small mb-2">
                  Each row is a detected field zone. Use the dropdown to assign what each field contains.
                  For fixed-width files, the Topaz ID defaults to the line number unless you assign a different field.
                </p>
                <Table size="sm" className="small">
                  <thead>
                    <tr>
                      <th style={{ width: 100 }}>Label</th>
                      <th style={{ width: 80 }}>Bytes</th>
                      <th style={{ width: 50 }}>Width</th>
                      <th style={{ width: 70 }}>Type</th>
                      <th style={{ width: 180 }}>Role</th>
                      <th>Sample Values</th>
                    </tr>
                  </thead>
                  <tbody>
                    {meta.field_zones.map((z, i) => {
                      const role = getZoneRole(z.label);
                      return (
                        <tr key={i} className={role === "chart_number" ? "table-info" : role === "patient_name" ? "table-success" : role === "topaz_id" ? "table-primary" : role === "service_date" ? "table-warning" : ""}>
                          <td><strong>{z.label}</strong></td>
                          <td>{z.start}-{z.end}</td>
                          <td>{z.width}</td>
                          <td><Badge bg={z.type === "digit" ? "info" : z.type === "alpha" ? "success" : z.type === "date" ? "warning" : "secondary"}>{z.type}</Badge></td>
                          <td>
                            <BsForm.Select size="sm" value={role}
                              onChange={e => handleZoneRoleChange(z.label, e.target.value)}>
                              {ROLE_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                              ))}
                            </BsForm.Select>
                          </td>
                          <td className="text-truncate" style={{ maxWidth: 350 }}>
                            {z.sample_values?.slice(0, 5).map((v, j) => <code key={j} className="me-2">{v}</code>)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              </div>
            )}

            {/* ── Delimited: header dropdowns ── */}
            {!isFixedWidth && meta?.headers?.length > 0 && (
              <div className="mb-3">
                <h6 className="mb-2">Assign Headers</h6>
                {meta.sample_rows?.length > 0 && (
                  <details className="mb-2">
                    <summary className="small fw-bold">Sample Rows ({meta.sample_rows.length})</summary>
                    <div style={{ maxHeight: 200, overflow: "auto" }}>
                      <Table size="sm" className="small mt-1 mb-0">
                        <thead><tr>{meta.headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
                        <tbody>
                          {meta.sample_rows.slice(0, 10).map((row, i) => (
                            <tr key={i}>{meta.headers.map((h, j) => <td key={j}>{row[h] || "--"}</td>)}</tr>
                          ))}
                        </tbody>
                      </Table>
                    </div>
                  </details>
                )}
                <Row className="g-2">
                  {["chart_number", "topaz_id", "patient_name", "service_date"].map(role => (
                    <Col key={role} md={3}>
                      <BsForm.Group>
                        <BsForm.Label className="small mb-0 fw-bold">
                          {role === "chart_number" ? "Chart / Jacket #" : role === "topaz_id" ? "Topaz ID" : role === "patient_name" ? "Patient Name" : "Service Date"}
                        </BsForm.Label>
                        <BsForm.Select size="sm" value={fieldMapping[role] || ""}
                          onChange={e => {
                            setFieldMapping(prev => {
                              const next = { ...prev };
                              if (e.target.value) { next[role] = e.target.value; }
                              else { delete next[role]; }
                              return next;
                            });
                            setExtractResult(null);
                          }}>
                          <option value="">-- none --</option>
                          {meta.headers.map((h, i) => (
                            <option key={i} value={h}>{h}</option>
                          ))}
                        </BsForm.Select>
                      </BsForm.Group>
                    </Col>
                  ))}
                </Row>
              </div>
            )}

            {/* Current mapping summary */}
            <div className="mb-3">
              <strong className="small">Current Mapping: </strong>
              {isFixedWidth && !fieldMapping.topaz_id && <Badge bg="dark" className="me-1">Topaz ID = line#</Badge>}
              {fieldMapping.topaz_id && <Badge bg="dark" className="me-1">Topaz ID &larr; {fieldMapping.topaz_id}</Badge>}
              {fieldMapping.chart_number && <Badge bg="info" className="me-1">Chart/Jacket# &larr; {fieldMapping.chart_number}</Badge>}
              {fieldMapping.patient_name && <Badge bg="success" className="me-1">Patient Name &larr; {fieldMapping.patient_name}</Badge>}
              {fieldMapping.service_date && <Badge bg="warning" className="me-1">Date &larr; {fieldMapping.service_date}</Badge>}
              {!fieldMapping.chart_number && !fieldMapping.patient_name && (
                <span className="text-danger small ms-2">Assign at least Chart/Jacket# or Patient Name.</span>
              )}
            </div>

            {/* Live preview for fixed-width */}
            {liveRows && liveRows.length > 0 && (
              <details open className="mb-3">
                <summary className="small fw-bold">Live Preview (first 10 records)</summary>
                <Table size="sm" className="small mt-1">
                  <thead><tr>
                    <th>Topaz ID</th>
                    <th>Chart / Jacket #</th>
                    <th>Patient Name</th>
                  </tr></thead>
                  <tbody>
                    {liveRows.map((r, i) => (
                      <tr key={i}>
                        <td><code>{r.topaz_id}</code></td>
                        <td>{r.chart_number || <span className="text-muted">--</span>}</td>
                        <td>{r.patient_name || <span className="text-muted">--</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {/* Extract button */}
            <Button variant="primary" size="sm" onClick={handleExtract} disabled={loading} className="me-2">
              {loading ? <><Spinner size="sm" className="me-1" />Extracting...</> : "Extract Crosswalk Pairs"}
            </Button>

            {/* ── Extract results ── */}
            {extractResult && (
              <div className="mt-3">
                <Alert variant="info" className="small">
                  <strong>Extracted {extractResult.extracted_count?.toLocaleString()} pairs</strong>
                  {extractResult.validation?.chart_numbers_in_file != null && (
                    <span>
                      {" "}&mdash; {extractResult.validation.chart_numbers_found_in_db} of{" "}
                      {extractResult.validation.chart_numbers_in_file} chart numbers found in billing records
                      {extractResult.validation.chart_numbers_not_in_db > 0 && (
                        <span className="text-warning"> ({extractResult.validation.chart_numbers_not_in_db} not in DB)</span>
                      )}
                    </span>
                  )}
                </Alert>

                {extractResult.sample_pairs?.length > 0 && (
                  <details open className="mb-3">
                    <summary className="small fw-bold">
                      Sample Pairs ({Math.min(extractResult.sample_pairs.length, 30)} of {extractResult.extracted_count?.toLocaleString()})
                    </summary>
                    <Table size="sm" className="small mt-1">
                      <thead><tr><th>Topaz ID</th><th>Chart / Jacket #</th><th>Patient Name</th></tr></thead>
                      <tbody>
                        {extractResult.sample_pairs.slice(0, 30).map((p, i) => (
                          <tr key={i}>
                            <td><code>{p.topaz_id || "--"}</code></td>
                            <td>{p.chart_number || "--"}</td>
                            <td>{p.patient_name || <span className="text-muted">--</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </details>
                )}

                <Button variant="success" size="sm" onClick={handleApply} disabled={loading}>
                  {loading ? <><Spinner size="sm" className="me-1" />Applying...</> : `Apply ${extractResult.extracted_count?.toLocaleString()} Pairs to Billing Records`}
                </Button>
                <span className="text-muted small ms-2">
                  Only exact chart# matches will be updated. No fuzzy matching. Nothing is guessed.
                </span>
              </div>
            )}
          </>
        )}

        {/* ══════════════ STEP 3: Applied ══════════════ */}
        {step === "applied" && applyResult && (
          <Alert variant={applyResult.apply_result?.applied > 0 ? "success" : "warning"} className="small">
            <strong>Applied!</strong>{" "}
            {applyResult.apply_result?.applied > 0 ? (
              <>
                Updated <strong>{applyResult.apply_result.applied}</strong> billing records with Topaz IDs.
                {applyResult.apply_result.skipped_no_match > 0 && (
                  <span> {applyResult.apply_result.skipped_no_match} pairs had no matching chart# in billing records.</span>
                )}
                {applyResult.apply_result.skipped_already_set > 0 && (
                  <span> {applyResult.apply_result.skipped_already_set} already had the same Topaz ID.</span>
                )}
              </>
            ) : (
              "No billing records needed updating (all chart numbers already had Topaz IDs or no matches found)."
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

function DataReset() {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [options, setOptions] = useState({
    clear_topaz_ids: true,
    clear_era_matches: false,
    clear_era_data: false,
    clear_billing_records: false,
    clear_crosswalk_imports: true,
  });

  const loadPreview = async () => {
    try {
      const res = await api.get("/matching/reset/preview");
      setPreview(res.data);
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => { loadPreview(); }, []);

  const handleReset = async () => {
    if (!window.confirm("Are you sure? This will permanently clear the selected data. This cannot be undone.")) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.post("/matching/reset/execute", { ...options, confirm: "RESET" });
      setResult(res.data);
      loadPreview(); // Refresh counts
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const RESET_OPTIONS = [
    { key: "clear_topaz_ids", label: "Clear all Topaz IDs", desc: "Remove topaz_id from all billing records. Use this to undo bad crosswalk assignments before reimporting.", count: preview?.billing_with_topaz_id, danger: false },
    { key: "clear_era_matches", label: "Clear ERA match linkages", desc: "Unlink ERA claims from billing records (clears era_claim_id, denial_status, denial_reason_code on billing records + match links on ERA claims). ERA data itself is kept.", count: preview?.billing_with_era_claim_id, danger: false },
    { key: "clear_crosswalk_imports", label: "Clear crosswalk import history", desc: "Delete all stored crosswalk imports (raw files, mappings, results).", count: preview?.crosswalk_imports, danger: false },
    { key: "clear_era_data", label: "Delete all ERA data", desc: "Delete all ERA payments and claim lines. You'll need to re-upload 835 files.", count: preview ? (preview.era_payments + preview.era_claim_lines) : null, danger: true },
    { key: "clear_billing_records", label: "Delete ALL billing records", desc: "Full wipe — deletes every billing record. You'll need to reimport the OCMRI spreadsheet.", count: preview?.billing_records, danger: true },
  ];

  return (
    <Card className="border-0 shadow-sm mb-4">
      <Card.Body>
        <Card.Title>Database Reset</Card.Title>
        <p className="text-muted small mb-3">
          Clear corrupted data and start fresh. Pick what to clear, review the counts, then confirm.
        </p>

        {error && <Alert variant="danger" className="small">{error}</Alert>}
        {result && (
          <Alert variant="success" className="small">
            <strong>Reset complete.</strong>{" "}
            {Object.entries(result.results || {}).map(([k, v]) => (
              <span key={k} className="me-2">{k.replace(/_/g, " ")}: <strong>{v}</strong></span>
            ))}
          </Alert>
        )}

        {preview && (
          <Row className="g-2 mb-3">
            <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{preview.billing_records?.toLocaleString()}</div><small>Billing Records</small></div></Col>
            <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{preview.billing_with_topaz_id?.toLocaleString()}</div><small>With Topaz ID</small></div></Col>
            <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{preview.billing_with_era_claim_id?.toLocaleString()}</div><small>With ERA Match</small></div></Col>
            <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{preview.era_payments?.toLocaleString()}</div><small>ERA Payments</small></div></Col>
            <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{preview.era_claim_lines?.toLocaleString()}</div><small>ERA Claims</small></div></Col>
            <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{preview.crosswalk_imports?.toLocaleString()}</div><small>Crosswalk Imports</small></div></Col>
          </Row>
        )}

        <div className="mb-3">
          {RESET_OPTIONS.map(opt => (
            <div key={opt.key} className={`form-check mb-2 p-2 rounded ${options[opt.key] ? (opt.danger ? "bg-danger bg-opacity-10" : "bg-warning bg-opacity-10") : ""}`}>
              <input className="form-check-input" type="checkbox" id={opt.key}
                checked={options[opt.key]}
                onChange={e => setOptions(prev => ({ ...prev, [opt.key]: e.target.checked }))} />
              <label className="form-check-label" htmlFor={opt.key}>
                <strong>{opt.label}</strong>
                {opt.count != null && <Badge bg="secondary" className="ms-2">{opt.count.toLocaleString()}</Badge>}
                {opt.danger && <Badge bg="danger" className="ms-2">Destructive</Badge>}
                <div className="text-muted small">{opt.desc}</div>
              </label>
            </div>
          ))}
        </div>

        <Button variant="danger" size="sm" onClick={handleReset}
          disabled={loading || !Object.values(options).some(v => v)}>
          {loading ? <><Spinner size="sm" className="me-1" />Resetting...</> : "Reset Selected Data"}
        </Button>
        <span className="text-muted small ms-2">You'll be asked to confirm.</span>
      </Card.Body>
    </Card>
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

  const runMatcher = async (force = false) => {
    if (force && !window.confirm(
      "This will clear ALL existing matches and re-run from scratch. Continue?"
    )) return;
    setRunning(true);
    setError(null);
    setLastResult(null);
    try {
      const endpoint = force ? "/matching/re-match?force=true" : "/matching/run";
      const res = await api.post(endpoint, {}, { timeout: 900000 });
      const data = force ? res.data.match_result : res.data;
      if (force && res.data.cleared_previous > 0) {
        data._cleared = res.data.cleared_previous;
      }
      setLastResult(data);
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
          <div className="d-flex align-items-center gap-3 flex-wrap">
            <Button variant="primary" size="lg" onClick={() => runMatcher(false)} disabled={running}>
              {running ? <><Spinner size="sm" className="me-2" /> Matching...</> : "Run Auto-Match Engine"}
            </Button>
            <Button variant="outline-warning" onClick={() => runMatcher(true)} disabled={running}>
              Force Re-Match All
            </Button>
            <span className="text-muted small">
              13-pass matching: Topaz ID crosswalk + name/date/amount fuzzy
            </span>
          </div>

          {error && <Alert variant="danger" className="mt-3">{error}</Alert>}

          {lastResult && (
            <Alert variant={lastResult.matched_total > 0 ? "success" : "info"} className="mt-3">
              {lastResult._cleared > 0 && <div className="small text-muted mb-1">Cleared {lastResult._cleared.toLocaleString()} previous matches before re-running.</div>}
              <strong>Matching complete!</strong>{" "}
              {lastResult.matched_total}/{lastResult.total} claims matched ({lastResult.match_rate}%)
              {lastResult.pass_0_topaz_id > 0 && <span> &mdash; Topaz ID: {lastResult.pass_0_topaz_id}</span>}
              {lastResult.pass_0b_patient_id > 0 && <span> &mdash; Patient ID: {lastResult.pass_0b_patient_id}</span>}
              {lastResult.pass_1_exact > 0 && <span> &mdash; Exact: {lastResult.pass_1_exact}</span>}
              {lastResult.pass_2_strong > 0 && <span> &mdash; Strong: {lastResult.pass_2_strong}</span>}
              {lastResult.pass_3_medium > 0 && <span> &mdash; Medium: {lastResult.pass_3_medium}</span>}
              {lastResult.pass_4_weak > 0 && <span> &mdash; ±3d: {lastResult.pass_4_weak}</span>}
              {lastResult.pass_4b_wider_date > 0 && <span> &mdash; ±7d: {lastResult.pass_4b_wider_date}</span>}
              {lastResult.pass_4c_wide_date > 0 && <span> &mdash; ±14d: {lastResult.pass_4c_wide_date}</span>}
              {lastResult.pass_4d_very_wide_date > 0 && <span> &mdash; ±30d: {lastResult.pass_4d_very_wide_date}</span>}
              {lastResult.pass_5_amount > 0 && <span> &mdash; Amount: {lastResult.pass_5_amount}</span>}
              {lastResult.pass_6_name_modality > 0 && <span> &mdash; Name+Mod: {lastResult.pass_6_name_modality}</span>}
              {lastResult.pass_7_name_amount > 0 && <span> &mdash; Name+Amt: {lastResult.pass_7_name_amount}</span>}
              {lastResult.pass_8_name_only > 0 && <span> &mdash; Name only: {lastResult.pass_8_name_only}</span>}
            </Alert>
          )}

          {lastResult?.diagnostics && lastResult.unmatched > 0 && (
            <div className="mt-3">
              <h6>Why {lastResult.unmatched.toLocaleString()} claims didn't match:</h6>
              <Row className="g-2 mb-3">
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{lastResult.diagnostics.billing_records?.toLocaleString()}</div><small>Billing Records</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{lastResult.diagnostics.billing_with_topaz_id?.toLocaleString()}</div><small>w/ Topaz ID</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold">{lastResult.diagnostics.billing_with_patient_id?.toLocaleString()}</div><small>w/ Patient ID</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-danger">{lastResult.diagnostics.claims_no_name}</div><small>Claims No Name</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-danger">{lastResult.diagnostics.claims_no_date}</div><small>Claims No Date</small></div></Col>
                <Col md={2}><div className="text-center bg-light p-2 rounded"><div className="fw-bold text-danger">{lastResult.diagnostics.claims_no_claim_id}</div><small>Claims No ID</small></div></Col>
              </Row>

              {lastResult.diagnostics.unmatched_samples?.length > 0 && (
                <details open>
                  <summary className="small fw-bold">Sample Unmatched Claims (first {lastResult.diagnostics.unmatched_samples.length})</summary>
                  <Table size="sm" className="small mt-1">
                    <thead>
                      <tr>
                        <th>ERA Patient</th>
                        <th>ERA Date</th>
                        <th>Claim ID</th>
                        <th>Topaz Lookup</th>
                        <th>Patient ID Lookup</th>
                        <th>Closest Billing Name</th>
                        <th>Name Score</th>
                        <th>Billing Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lastResult.diagnostics.unmatched_samples.map((s, i) => (
                        <tr key={i}>
                          <td>{s.patient_name || <span className="text-danger">--none--</span>}</td>
                          <td>{s.service_date || <span className="text-danger">--none--</span>}</td>
                          <td><code>{s.claim_id || "--"}</code></td>
                          <td className="small">{s.topaz_id_lookup || "--"}</td>
                          <td className="small">{s.patient_id_lookup || "--"}</td>
                          <td>{s.best_name_match?.billing_name || "--"}</td>
                          <td>{s.best_name_match ? <Badge bg={s.best_name_match.score >= 85 ? "success" : s.best_name_match.score >= 70 ? "warning" : "danger"}>{s.best_name_match.score}%</Badge> : "--"}</td>
                          <td>{s.best_name_match?.billing_date || "--"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </details>
              )}
            </div>
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
        <Tab eventKey="reset" title="Reset">
          <DataReset />
        </Tab>
      </Tabs>
    </>
  );
}

export default Matching;
