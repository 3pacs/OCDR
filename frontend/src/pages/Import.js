import React, { useState, useCallback, useEffect, useMemo } from "react";
import { Card, Row, Col, Button, Alert, Spinner, Tab, Tabs, Table, Badge, Form, ProgressBar } from "react-bootstrap";
import { useDropzone } from "react-dropzone";
import api from "../services/api";
import { buildCockpitModel } from "./importCockpit";

function FileUploader({ accept, endpoint, label, onResult }) {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const onDrop = useCallback(async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    const formData = new FormData();
    formData.append("file", file);

    setUploading(true);
    setError(null);
    setResult(null);

    try {
      const res = await api.post(endpoint, formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 600000,
      });
      setResult(res.data);
      if (onResult) onResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setUploading(false);
    }
  }, [endpoint, onResult]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
  });

  return (
    <Card className="border-0 shadow-sm">
      <Card.Body>
        <Card.Title>{label}</Card.Title>
        <div
          {...getRootProps()}
          style={{
            border: "2px dashed #ccc",
            borderRadius: 8,
            padding: 40,
            textAlign: "center",
            cursor: "pointer",
            backgroundColor: isDragActive ? "#e8f4fd" : "#fafafa",
          }}
        >
          <input {...getInputProps()} />
          {uploading ? (
            <div>
              <Spinner animation="border" className="mb-2" />
              <p className="mb-0">Importing... this may take a minute for large files</p>
            </div>
          ) : isDragActive ? (
            <p className="mb-0">Drop file here...</p>
          ) : (
            <p className="mb-0">Drag &amp; drop a file here, or click to select</p>
          )}
        </div>

        {result && (
          <Alert variant="success" className="mt-3">
            <strong>Import complete!</strong>
            <pre className="mb-0 mt-2" style={{ fontSize: "0.85rem" }}>
              {JSON.stringify(result, null, 2)}
            </pre>
          </Alert>
        )}

        {error && (
          <Alert variant="danger" className="mt-3">{error}</Alert>
        )}
      </Card.Body>
    </Card>
  );
}

function FlexibleUploader() {
  const [step, setStep] = useState("upload"); // upload | inspect | importing | done
  const [file, setFile] = useState(null);
  const [inspection, setInspection] = useState(null);
  const [selectedSheet, setSelectedSheet] = useState("");
  const [importResult, setImportResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const onDrop = useCallback(async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;
    const f = acceptedFiles[0];
    setFile(f);
    setError(null);
    setLoading(true);

    const formData = new FormData();
    formData.append("file", f);

    try {
      const res = await api.post("/import/excel-inspect", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });
      setInspection(res.data);
      const sheets = res.data.sheet_names || Object.keys(res.data.sheets || {});
      if (sheets.length > 0) setSelectedSheet(sheets[0]);
      setStep("inspect");
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
  });

  const doImport = async () => {
    if (!file) return;
    setStep("importing");
    setError(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const url = selectedSheet
        ? `/import/excel-flexible?sheet_name=${encodeURIComponent(selectedSheet)}`
        : "/import/excel-flexible";
      const res = await api.post(url, formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 600000,
      });
      setImportResult(res.data);
      setStep("done");
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      setStep("inspect");
    }
  };

  const reset = () => {
    setStep("upload");
    setFile(null);
    setInspection(null);
    setSelectedSheet("");
    setImportResult(null);
    setError(null);
  };

  const sheetInfo = inspection?.sheets?.[selectedSheet];

  return (
    <Card className="border-0 shadow-sm">
      <Card.Body>
        <Card.Title>Upload Any Excel File (Smart Import)</Card.Title>
        <p className="text-muted small">
          Auto-detects headers, fuzzy-matches columns, stores all data. Handles messy files up to 200MB.
        </p>

        {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

        {step === "upload" && (
          <div
            {...getRootProps()}
            style={{
              border: "2px dashed #0d6efd",
              borderRadius: 8,
              padding: 50,
              textAlign: "center",
              cursor: "pointer",
              backgroundColor: isDragActive ? "#e8f4fd" : "#f8f9fa",
            }}
          >
            <input {...getInputProps()} />
            {loading ? (
              <div>
                <Spinner animation="border" variant="primary" className="mb-2" />
                <p className="mb-0">Scanning file structure...</p>
              </div>
            ) : isDragActive ? (
              <p className="mb-0 fs-5">Drop Excel file here...</p>
            ) : (
              <div>
                <p className="mb-1 fs-5">Drop any Excel file here</p>
                <p className="mb-0 text-muted">.xlsx or .xls &mdash; any format, any columns</p>
              </div>
            )}
          </div>
        )}

        {step === "inspect" && inspection && (
          <>
            <Alert variant="info" className="mb-3">
              <strong>{file.name}</strong> &mdash; {(file.size / 1024 / 1024).toFixed(1)} MB
              &mdash; {inspection.sheet_names?.length ?? 0} sheet(s) detected
            </Alert>

            {inspection.sheet_names?.length > 1 && (
              <Form.Group className="mb-3">
                <Form.Label className="fw-bold">Select Sheet</Form.Label>
                <Form.Select value={selectedSheet} onChange={(e) => setSelectedSheet(e.target.value)}>
                  {inspection.sheet_names.map((name) => (
                    <option key={name} value={name}>
                      {name} ({inspection.sheets[name]?.estimated_rows ?? "?"} rows, {inspection.sheets[name]?.total_columns ?? "?"} cols)
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>
            )}

            {sheetInfo && (
              <>
                <h6 className="mt-3">Column Mapping Preview</h6>
                <Table size="sm" striped className="small">
                  <thead>
                    <tr>
                      <th>Excel Column</th>
                      <th>Maps To</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(sheetInfo.mapped_columns || {}).map(([col, field]) => (
                      <tr key={col}>
                        <td>{col}</td>
                        <td><code>{field}</code></td>
                        <td><Badge bg="success">Mapped</Badge></td>
                      </tr>
                    ))}
                    {(sheetInfo.unmapped_columns || []).map((col) => (
                      <tr key={col}>
                        <td>{col}</td>
                        <td className="text-muted">&rarr; extra_data (JSON)</td>
                        <td><Badge bg="secondary">Stored as extra</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </Table>

                <div className="d-flex gap-2 mt-3">
                  <Button variant="primary" size="lg" onClick={doImport}>
                    Import {sheetInfo.estimated_rows?.toLocaleString() ?? ""} rows from &quot;{selectedSheet}&quot;
                  </Button>
                  <Button variant="outline-secondary" onClick={reset}>Cancel</Button>
                </div>
              </>
            )}
          </>
        )}

        {step === "importing" && (
          <div className="text-center py-5">
            <Spinner animation="border" variant="primary" className="mb-3" style={{ width: 48, height: 48 }} />
            <h5>Importing {file?.name}...</h5>
            <p className="text-muted">
              Processing sheet &quot;{selectedSheet}&quot; &mdash; this may take a few minutes for large files.
            </p>
            <ProgressBar animated now={100} variant="primary" />
          </div>
        )}

        {step === "done" && importResult && (
          <>
            <Alert variant="success">
              <Alert.Heading>Import Complete!</Alert.Heading>
              <Row className="mt-2">
                <Col md={3} className="text-center">
                  <div className="fs-3 fw-bold text-success">{importResult.imported?.toLocaleString()}</div>
                  <small>Rows Imported</small>
                </Col>
                <Col md={3} className="text-center">
                  <div className="fs-3 fw-bold text-muted">{importResult.skipped?.toLocaleString()}</div>
                  <small>Skipped (dupes/empty)</small>
                </Col>
                <Col md={3} className="text-center">
                  <div className="fs-3 fw-bold text-danger">{importResult.errors?.toLocaleString()}</div>
                  <small>Errors</small>
                </Col>
                <Col md={3} className="text-center">
                  <div className="fs-3 fw-bold text-info">{importResult.total_columns_detected}</div>
                  <small>Columns Found</small>
                </Col>
              </Row>
            </Alert>

            {importResult.columns_mapped && Object.keys(importResult.columns_mapped).length > 0 && (
              <details className="mb-3">
                <summary className="small text-muted cursor-pointer">Column mapping details</summary>
                <pre className="small mt-2 bg-light p-2 rounded">
                  {JSON.stringify(importResult.columns_mapped, null, 2)}
                </pre>
              </details>
            )}

            {importResult.columns_unmapped?.length > 0 && (
              <Alert variant="info" className="small">
                <strong>Unmapped columns stored in extra_data:</strong> {importResult.columns_unmapped.join(", ")}
              </Alert>
            )}

            <Button variant="primary" onClick={reset}>Import Another File</Button>
          </>
        )}
      </Card.Body>
    </Card>
  );
}

function ImportHistory() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/import/history")
      .then((r) => setHistory(r.data.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner animation="border" size="sm" />;
  if (history.length === 0) return <p className="text-muted small">No imports yet.</p>;

  return (
    <Table size="sm" striped hover responsive className="small">
      <thead>
        <tr>
          <th>File</th>
          <th>Sheet</th>
          <th>Type</th>
          <th>Status</th>
          <th className="text-end">Imported</th>
          <th className="text-end">Skipped</th>
          <th className="text-end">Errors</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        {history.map((h) => (
          <tr key={h.id}>
            <td className="text-truncate" style={{ maxWidth: 200 }}>{h.filename}</td>
            <td>{h.sheet_name ?? "--"}</td>
            <td><Badge bg="secondary">{h.import_type}</Badge></td>
            <td>
              <Badge bg={h.status === "COMPLETED" ? "success" : h.status === "FAILED" ? "danger" : "warning"}>
                {h.status}
              </Badge>
            </td>
            <td className="text-end">{h.rows_imported?.toLocaleString()}</td>
            <td className="text-end">{h.rows_skipped?.toLocaleString()}</td>
            <td className="text-end">{h.rows_errored?.toLocaleString()}</td>
            <td>{h.created_at ? new Date(h.created_at).toLocaleString() : "--"}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function ScanSnapStatus() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/import/scansnap/status", { timeout: 15000 });
      setStatus(res.data);
    } catch (err) {
      setStatus({ available: false, error: err.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  return (
    <Card className="border-0 shadow-sm mt-3">
      <Card.Body>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <Card.Title className="mb-0">ScanSnap Queue</Card.Title>
          <Button variant="outline-secondary" size="sm" onClick={loadStatus} disabled={loading}>
            {loading ? <Spinner size="sm" /> : "Refresh"}
          </Button>
        </div>

        {status && !status.available && (
          <Alert variant="warning" className="small mb-3">
            {status.error || "Scanner status unavailable"}
          </Alert>
        )}

        <Row className="g-2">
          <Col xs={4}>
            <div className="text-center bg-light rounded p-2">
              <Badge bg={status?.watcher_running ? "success" : "secondary"}>
                {status?.watcher_running ? "Running" : "Unknown"}
              </Badge>
              <div className="small text-muted mt-1">Watcher</div>
            </div>
          </Col>
          <Col xs={4}>
            <div className="text-center bg-light rounded p-2">
              <div className="fw-bold">{status?.unclassified_count ?? "--"}</div>
              <div className="small text-muted">Queued</div>
            </div>
          </Col>
          <Col xs={4}>
            <div className="text-center bg-light rounded p-2">
              <div className="fw-bold">{status?.ocr_today_count ?? "--"}</div>
              <div className="small text-muted">OCR Today</div>
            </div>
          </Col>
        </Row>
      </Card.Body>
    </Card>
  );
}

function PortalDownloads() {
  const [status, setStatus] = useState(null);
  const [checklists, setChecklists] = useState([]);
  const [promotion, setPromotion] = useState(null);
  const [scanResult, setScanResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);

  const loadPortal = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statusRes, checklistRes] = await Promise.all([
        api.get("/import/portal/status"),
        api.get("/import/portal/checklists"),
      ]);
      setStatus(statusRes.data);
      setChecklists(checklistRes.data.items || []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPortal();
  }, [loadPortal]);

  const openPortalUrl = (url) => {
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const promote = async (dryRun) => {
    setPromoting(true);
    setError(null);
    try {
      const res = await api.post(`/import/portal/promote?dry_run=${dryRun ? "true" : "false"}`, {});
      setPromotion(res.data);
      await loadPortal();
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setPromoting(false);
    }
  };

  const scanPromoted = async () => {
    setScanning(true);
    setError(null);
    try {
      const res = await api.post("/import/scan-eobs", {}, { timeout: 600000 });
      setScanResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setScanning(false);
    }
  };

  const visibleFiles = (status?.files || []).filter((file) => file.supported && !file.temporary).slice(0, 8);

  return (
    <Card className="border-0 shadow-sm mb-3">
      <Card.Body>
        <div className="d-flex justify-content-between align-items-center mb-3">
          <Card.Title className="mb-0">Portal Downloads</Card.Title>
          <Button variant="outline-secondary" size="sm" onClick={loadPortal} disabled={loading}>
            {loading ? <Spinner size="sm" /> : "Refresh"}
          </Button>
        </div>

        {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}
        {status && !status.available && (
          <Alert variant="warning" className="small">
            {status.error}
          </Alert>
        )}

        <Row className="g-2 mb-3">
          <Col md={3} xs={6}>
            <div className="text-center bg-light rounded p-2">
              <div className="fs-5 fw-bold">{status?.supported_count ?? "--"}</div>
              <small>Ready</small>
            </div>
          </Col>
          <Col md={3} xs={6}>
            <div className="text-center bg-light rounded p-2">
              <div className="fs-5 fw-bold">{status?.staged_count ?? "--"}</div>
              <small>Staged</small>
            </div>
          </Col>
          <Col md={3} xs={6}>
            <div className="text-center bg-light rounded p-2">
              <div className="fs-5 fw-bold">{status ? formatSize(status.total_bytes || 0) : "--"}</div>
              <small>Size</small>
            </div>
          </Col>
          <Col md={3} xs={6}>
            <div className="text-center bg-light rounded p-2">
              <div className="fs-5 fw-bold">{promotion?.copied ?? 0}</div>
              <small>Promoted</small>
            </div>
          </Col>
        </Row>

        <div className="d-flex flex-wrap gap-2 mb-3">
          <Button variant="outline-primary" onClick={() => promote(true)} disabled={promoting || !status?.available}>
            Preview Promote
          </Button>
          <Button variant="primary" onClick={() => promote(false)} disabled={promoting || !status?.available}>
            {promoting ? <><Spinner size="sm" className="me-1" /> Promoting...</> : "Promote to Import Folder"}
          </Button>
          <Button variant="success" onClick={scanPromoted} disabled={scanning}>
            {scanning ? <><Spinner size="sm" className="me-1" /> Importing...</> : "Scan Import Folder"}
          </Button>
        </div>

        {promotion && (
          <Alert variant={promotion.copied > 0 || promotion.planned > 0 ? "info" : "secondary"} className="small">
            Planned {promotion.planned}, copied {promotion.copied}, duplicates {promotion.duplicates}, unsupported {promotion.unsupported}
          </Alert>
        )}

        {scanResult && (
          <Alert variant="success" className="small">
            Imported {scanResult.imported_835 + scanResult.imported_excel + scanResult.imported_topaz} file group(s);
            {" "}{scanResult.errors} error(s).
          </Alert>
        )}

        {visibleFiles.length > 0 && (
          <Table size="sm" striped responsive className="small">
            <thead>
              <tr><th>File</th><th>Type</th><th className="text-end">Size</th></tr>
            </thead>
            <tbody>
              {visibleFiles.map((file) => (
                <tr key={file.name}>
                  <td className="text-truncate" style={{ maxWidth: 320 }}>{file.name}</td>
                  <td><Badge bg="secondary">{file.extension}</Badge></td>
                  <td className="text-end">{formatSize(file.size)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}

        {checklists.length > 0 && (
          <details className="small">
            <summary className="text-muted">Payer download checklists</summary>
            <div className="mt-2">
              {checklists.map((payer) => (
                <div key={payer.id} className="mb-3">
                  <div className="fw-bold mb-1">{payer.name}</div>
                  <div className="d-flex flex-wrap gap-2 mb-2">
                    {payer.urls.map((entry) => (
                      <Button key={entry.url} variant="outline-secondary" size="sm" onClick={() => openPortalUrl(entry.url)}>
                        {entry.label}
                      </Button>
                    ))}
                  </div>
                  <ol className="mb-0">
                    {payer.steps.map((step) => <li key={step}>{step}</li>)}
                  </ol>
                </div>
              ))}
            </div>
          </details>
        )}
      </Card.Body>
    </Card>
  );
}

function EOBScanner() {
  const [step, setStep] = useState("idle"); // idle | previewing | scanning | done
  const [preview, setPreview] = useState(null);
  const [scanResult, setScanResult] = useState(null);
  const [error, setError] = useState(null);

  const doPreview = async () => {
    setStep("previewing");
    setError(null);
    try {
      const res = await api.get("/import/scan-eobs/preview");
      setPreview(res.data);
      setStep("idle");
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      setStep("idle");
    }
  };

  const doScan = async () => {
    setStep("scanning");
    setError(null);
    try {
      const res = await api.post("/import/scan-eobs", {}, { timeout: 600000 });
      setScanResult(res.data);
      setStep("done");
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      setStep("idle");
    }
  };

  return (
    <Card className="border-0 shadow-sm">
      <Card.Body>
        <Card.Title>EOB Folder Scanner</Card.Title>
        <p className="text-muted small">
          Scans the <code>/app/data/eobs</code> folder (and all subfolders) for new EOB files.
          Skips files already imported. Handles .835, .edi, .txt, .xlsx, .xls files.
        </p>

        {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

        {step === "scanning" && (
          <div className="text-center py-4">
            <Spinner animation="border" variant="primary" className="mb-2" />
            <p>Scanning and importing EOB files... this may take a while.</p>
            <ProgressBar animated now={100} variant="primary" />
          </div>
        )}

        {step !== "scanning" && step !== "done" && (
          <div className="d-flex gap-2 mb-3">
            <Button variant="outline-primary" onClick={doPreview} disabled={step === "previewing"}>
              {step === "previewing" ? <><Spinner size="sm" className="me-1" /> Scanning...</> : "Preview (Dry Run)"}
            </Button>
            <Button variant="primary" onClick={doScan}>
              Scan &amp; Import New Files
            </Button>
          </div>
        )}

        {preview && step !== "done" && (
          <>
            <Alert variant="info">
              <strong>{preview.total_files}</strong> total files found &mdash;{" "}
              <strong className="text-success">{preview.new_count}</strong> new,{" "}
              <strong className="text-muted">{preview.already_processed_count}</strong> already processed
            </Alert>

            {preview.new_files?.length > 0 && (
              <>
                <h6>New files to import:</h6>
                <Table size="sm" striped className="small">
                  <thead>
                    <tr><th>File</th><th>Type</th><th>Size</th></tr>
                  </thead>
                  <tbody>
                    {preview.new_files.map((f) => (
                      <tr key={f.path}>
                        <td>{f.path}</td>
                        <td><Badge bg="secondary">{f.extension}</Badge></td>
                        <td>{formatSize(f.size_bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </>
            )}

            {preview.new_count === 0 && (
              <Alert variant="success">All files in the EOB folder have already been processed!</Alert>
            )}
          </>
        )}

        {step === "done" && scanResult && (
          <>
            <Alert variant="success">
              <Alert.Heading>Scan Complete!</Alert.Heading>
              <Row className="mt-2">
                <Col md={2} className="text-center">
                  <div className="fs-4 fw-bold">{scanResult.total_files_found}</div>
                  <small>Total Files</small>
                </Col>
                <Col md={2} className="text-center">
                  <div className="fs-4 fw-bold text-muted">{scanResult.already_processed}</div>
                  <small>Already Done</small>
                </Col>
                <Col md={2} className="text-center">
                  <div className="fs-4 fw-bold text-success">{scanResult.imported_835}</div>
                  <small>835s Imported</small>
                </Col>
                <Col md={2} className="text-center">
                  <div className="fs-4 fw-bold text-primary">{scanResult.imported_excel}</div>
                  <small>Excels Imported</small>
                </Col>
                <Col md={2} className="text-center">
                  <div className="fs-4 fw-bold text-info">{scanResult.claims_found}</div>
                  <small>Claims Found</small>
                </Col>
                <Col md={2} className="text-center">
                  <div className="fs-4 fw-bold text-danger">{scanResult.errors}</div>
                  <small>Errors</small>
                </Col>
              </Row>
            </Alert>

            {scanResult.details?.length > 0 && (
              <details>
                <summary className="small text-muted mb-2">File-by-file details ({scanResult.details.length} files)</summary>
                <Table size="sm" striped className="small mt-2">
                  <thead>
                    <tr><th>File</th><th>Type</th><th>Status</th><th>Details</th></tr>
                  </thead>
                  <tbody>
                    {scanResult.details.map((d, i) => (
                      <tr key={i}>
                        <td className="text-truncate" style={{ maxWidth: 250 }}>{d.file}</td>
                        <td><Badge bg="secondary">{d.type || "?"}</Badge></td>
                        <td>
                          <Badge bg={d.status === "ok" ? "success" : d.status === "skipped" ? "warning" : "danger"}>
                            {d.status}
                          </Badge>
                        </td>
                        <td className="small text-muted">
                          {d.claims_found != null && `${d.claims_found} claims`}
                          {d.imported != null && `${d.imported} rows`}
                          {d.error && d.error}
                          {d.reason && d.reason}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            <Button variant="primary" onClick={() => { setStep("idle"); setScanResult(null); setPreview(null); }}>
              Scan Again
            </Button>
          </>
        )}
      </Card.Body>
    </Card>
  );
}

const cockpitStyles = `
  .revenue-cockpit {
    display: grid;
    gap: 0.5rem;
  }
  .cockpit-kpis {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 0.5rem;
  }
  .cockpit-kpi {
    background: #fff;
    border: 1px solid #d8dee5;
    border-left: 4px solid #6c757d;
    min-height: 48px;
    padding: 0.4rem 0.65rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .cockpit-kpi.ready { border-left-color: #0f766e; }
  .cockpit-kpi.review { border-left-color: #9a5b00; }
  .cockpit-kpi.blocked { border-left-color: #b42318; }
  .cockpit-kpi.posted { border-left-color: #4169a8; }
  .cockpit-kpi span {
    color: #667280;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
  }
  .cockpit-kpi strong {
    font-size: 1.35rem;
    line-height: 1;
  }
  .cockpit-grid {
    display: grid;
    grid-template-columns: minmax(420px, 43%) minmax(340px, 34%) minmax(260px, 23%);
    gap: 0.5rem;
    align-items: stretch;
  }
  .cockpit-panel {
    background: #fff;
    border: 1px solid #d8dee5;
    min-height: 430px;
    display: flex;
    flex-direction: column;
  }
  .cockpit-panel-header {
    min-height: 38px;
    border-bottom: 1px solid #e8edf1;
    padding: 0.45rem 0.65rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .cockpit-panel-header h3 {
    font-size: 0.95rem;
    font-weight: 700;
    margin: 0;
  }
  .cockpit-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
  }
  .cockpit-table th,
  .cockpit-table td {
    border-bottom: 1px solid #e8edf1;
    padding: 0.48rem 0.5rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: middle;
  }
  .cockpit-table th {
    color: #667280;
    background: #fbfcfd;
    font-size: 0.7rem;
    text-transform: uppercase;
  }
  .cockpit-table tr {
    cursor: pointer;
  }
  .cockpit-table tr.active td {
    background: #edf5ff;
  }
  .source-pill {
    border: 1px solid #ccd4dc;
    border-radius: 3px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 58px;
    height: 23px;
    font-size: 0.72rem;
    font-weight: 700;
    background: #fff;
  }
  .evidence-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.5rem;
    padding: 0.65rem;
  }
  .evidence-field {
    border: 1px solid #e8edf1;
    padding: 0.45rem 0.55rem;
    min-height: 50px;
  }
  .evidence-field span,
  .verification-row span:first-child,
  .action-group h4 {
    color: #667280;
    display: block;
    font-size: 0.68rem;
    font-weight: 700;
    margin-bottom: 0.2rem;
    text-transform: uppercase;
  }
  .verification-list {
    border-top: 1px solid #e8edf1;
    border-bottom: 1px solid #e8edf1;
  }
  .verification-row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 0.5rem;
    padding: 0.52rem 0.65rem;
    border-bottom: 1px solid #eef2f5;
  }
  .verification-row:last-child {
    border-bottom: 0;
  }
  .cockpit-events {
    padding: 0.65rem;
    color: #667280;
    font-size: 0.82rem;
  }
  .cockpit-events div {
    display: grid;
    grid-template-columns: 54px 1fr;
    gap: 0.5rem;
    margin-bottom: 0.35rem;
  }
  .action-rail {
    padding: 0.65rem;
    display: grid;
    gap: 0.55rem;
    align-content: start;
  }
  .action-group {
    border: 1px solid #e8edf1;
    padding: 0.55rem;
    display: grid;
    gap: 0.4rem;
  }
  .action-group h4 {
    margin: 0;
  }
  .compact-stat {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    border-bottom: 1px solid #eef2f5;
    padding-bottom: 0.25rem;
    color: #667280;
    font-size: 0.82rem;
  }
  .compact-stat b {
    color: #1f2933;
  }
  @media (max-width: 1200px) {
    .cockpit-kpis {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .cockpit-grid {
      grid-template-columns: 1fr;
    }
    .cockpit-panel {
      min-height: 260px;
    }
  }
`;

function statusVariant(status) {
  if (status === "ready") return "success";
  if (status === "review") return "warning";
  if (status === "blocked") return "danger";
  if (status === "posted") return "primary";
  return "secondary";
}

function formatEvidenceValue(field) {
  if (field.label === "Size" && typeof field.value === "number") {
    return formatSize(field.value);
  }
  return String(field.value ?? "--");
}

function RevenueIntakeCockpit() {
  const [portalStatus, setPortalStatus] = useState(null);
  const [checklists, setChecklists] = useState([]);
  const [scannerStatus, setScannerStatus] = useState(null);
  const [scanPreview, setScanPreview] = useState(null);
  const [scanResult, setScanResult] = useState(null);
  const [promotion, setPromotion] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(null);
  const [error, setError] = useState(null);

  const loadCockpit = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [portalRes, checklistRes, scannerRes, previewRes] = await Promise.allSettled([
      api.get("/import/portal/status"),
      api.get("/import/portal/checklists"),
      api.get("/import/scansnap/status"),
      api.get("/import/scan-eobs/preview"),
    ]);

    if (portalRes.status === "fulfilled") setPortalStatus(portalRes.value.data);
    else setPortalStatus({ available: false, error: portalRes.reason?.response?.data?.detail || portalRes.reason?.message });

    if (checklistRes.status === "fulfilled") setChecklists(checklistRes.value.data.items || []);
    else setChecklists([]);

    if (scannerRes.status === "fulfilled") setScannerStatus(scannerRes.value.data);
    else setScannerStatus({ available: false, error: scannerRes.reason?.response?.data?.detail || scannerRes.reason?.message });

    if (previewRes.status === "fulfilled") setScanPreview(previewRes.value.data);
    else setError(previewRes.reason?.response?.data?.detail || previewRes.reason?.message);

    setLoading(false);
  }, []);

  useEffect(() => {
    loadCockpit();
  }, [loadCockpit]);

  const model = useMemo(
    () => buildCockpitModel({ portalStatus, scannerStatus, scanPreview, scanResult }),
    [portalStatus, scannerStatus, scanPreview, scanResult]
  );

  useEffect(() => {
    if (model.items.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !model.items.some((item) => item.id === selectedId)) {
      setSelectedId(model.selectedId);
    }
  }, [model.items, model.selectedId, selectedId]);

  const selectedItem = model.items.find((item) => item.id === selectedId) || model.items[0];

  const promote = async (dryRun) => {
    setWorking(dryRun ? "preview-promote" : "promote");
    setError(null);
    try {
      const res = await api.post(`/import/portal/promote?dry_run=${dryRun ? "true" : "false"}`, {});
      setPromotion(res.data);
      await loadCockpit();
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setWorking(null);
    }
  };

  const scanImportFolder = async () => {
    setWorking("scan-import");
    setError(null);
    try {
      const res = await api.post("/import/scan-eobs", {}, { timeout: 600000 });
      setScanResult(res.data);
      await loadCockpit();
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setWorking(null);
    }
  };

  const previewArchive = async () => {
    setWorking("preview-archive");
    setError(null);
    try {
      const res = await api.get("/import/scan-eobs/preview");
      setScanPreview(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setWorking(null);
    }
  };

  const openPortalUrl = (url) => {
    window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="revenue-cockpit">
      <style>{cockpitStyles}</style>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)} className="py-2 mb-0">{error}</Alert>}

      <section className="cockpit-kpis">
        <div className="cockpit-kpi ready"><span>Ready</span><strong>{model.metrics.ready}</strong></div>
        <div className="cockpit-kpi review"><span>Review</span><strong>{model.metrics.review}</strong></div>
        <div className="cockpit-kpi blocked"><span>Blocked</span><strong>{model.metrics.blocked}</strong></div>
        <div className="cockpit-kpi posted"><span>Processed</span><strong>{model.metrics.posted}</strong></div>
        <div className="cockpit-kpi"><span>Scan Queue</span><strong>{model.metrics.scannerQueue}</strong></div>
      </section>

      <section className="cockpit-grid">
        <div className="cockpit-panel">
          <div className="cockpit-panel-header">
            <h3>Work Queue</h3>
            <div className="d-flex gap-1">
              <Button size="sm" variant="outline-secondary" onClick={loadCockpit} disabled={loading}>
                {loading ? <Spinner size="sm" /> : "Refresh"}
              </Button>
            </div>
          </div>
          <div className="table-responsive">
            <table className="cockpit-table">
              <thead>
                <tr>
                  <th style={{ width: 82 }}>Source</th>
                  <th>Work item</th>
                  <th style={{ width: 92 }}>Amount</th>
                  <th style={{ width: 94 }}>Gate</th>
                  <th style={{ width: 118 }}>Next</th>
                </tr>
              </thead>
              <tbody>
                {model.items.map((item) => (
                  <tr
                    key={item.id}
                    className={item.id === selectedItem?.id ? "active" : ""}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <td><span className="source-pill">{item.source}</span></td>
                    <td title={item.title}>{item.title}</td>
                    <td>{item.amount}</td>
                    <td><Badge bg={statusVariant(item.status)}>{item.gate}</Badge></td>
                    <td>{item.nextAction}</td>
                  </tr>
                ))}
                {model.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="text-muted">No intake work loaded yet. Refresh source status to start.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="cockpit-panel">
          <div className="cockpit-panel-header">
            <h3>Evidence</h3>
            {selectedItem && <Badge bg={statusVariant(selectedItem.status)}>{selectedItem.status}</Badge>}
          </div>
          {selectedItem ? (
            <>
              <div className="evidence-grid">
                <div className="evidence-field"><span>Source</span><strong>{selectedItem.source}</strong></div>
                <div className="evidence-field"><span>Stage</span><strong>{selectedItem.stage}</strong></div>
                <div className="evidence-field"><span>Work Item</span><strong>{selectedItem.title}</strong></div>
                <div className="evidence-field"><span>Next Action</span><strong>{selectedItem.nextAction}</strong></div>
              </div>

              <div className="verification-list">
                {selectedItem.evidence.map((field) => (
                  <div className="verification-row" key={`${field.label}-${field.value}`}>
                    <div>
                      <span>{field.label}</span>
                      <strong>{formatEvidenceValue(field)}</strong>
                    </div>
                    <Badge bg={statusVariant(field.state)}>{field.state}</Badge>
                  </div>
                ))}
              </div>

              <div className="cockpit-events">
                {(selectedItem.events.length > 0 ? selectedItem.events : [selectedItem.reason]).filter(Boolean).map((event, index) => (
                  <div key={`${event}-${index}`}>
                    <span>{index === 0 ? "Now" : `-${index}`}</span>
                    <strong>{event}</strong>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="p-3 text-muted">No work item selected.</div>
          )}
        </div>

        <div className="cockpit-panel">
          <div className="cockpit-panel-header">
            <h3>Actions</h3>
            {working && <Spinner size="sm" />}
          </div>
          <div className="action-rail">
            <section className="action-group">
              <h4>Selected Work</h4>
              <Button size="sm" variant="primary" onClick={scanImportFolder} disabled={working === "scan-import"}>
                {working === "scan-import" ? "Importing..." : "Scan Import Folder"}
              </Button>
              <Button size="sm" variant="outline-primary" onClick={previewArchive} disabled={working === "preview-archive"}>
                {working === "preview-archive" ? "Previewing..." : "Preview Archive"}
              </Button>
              <Button size="sm" variant="outline-secondary" onClick={() => promote(true)} disabled={working === "preview-promote" || !portalStatus?.available}>
                Preview Promote
              </Button>
              <Button size="sm" variant="success" onClick={() => promote(false)} disabled={working === "promote" || !portalStatus?.available}>
                Promote Portal Files
              </Button>
            </section>

            <section className="action-group">
              <h4>Scanner</h4>
              <div className="compact-stat"><b>Watcher</b><span>{scannerStatus?.watcher_active ? "online" : scannerStatus?.available ? "offline" : "unavailable"}</span></div>
              <div className="compact-stat"><b>Unclassified</b><span>{scannerStatus?.unclassified_count ?? "--"}</span></div>
              <div className="compact-stat"><b>OCR today</b><span>{scannerStatus?.ocr_today_count ?? "--"}</span></div>
            </section>

            <section className="action-group">
              <h4>Portals</h4>
              {checklists.flatMap((payer) => payer.urls.map((entry) => ({ payer: payer.name, ...entry }))).slice(0, 5).map((entry) => (
                <Button key={`${entry.payer}-${entry.url}`} size="sm" variant="outline-secondary" onClick={() => openPortalUrl(entry.url)}>
                  {entry.label}
                </Button>
              ))}
              {checklists.length === 0 && <span className="text-muted small">No payer checklist loaded.</span>}
            </section>

            {(promotion || scanResult) && (
              <section className="action-group">
                <h4>Latest Run</h4>
                {promotion && (
                  <>
                    <div className="compact-stat"><b>Planned</b><span>{promotion.planned}</span></div>
                    <div className="compact-stat"><b>Copied</b><span>{promotion.copied}</span></div>
                    <div className="compact-stat"><b>Duplicates</b><span>{promotion.duplicates}</span></div>
                  </>
                )}
                {scanResult && (
                  <>
                    <div className="compact-stat"><b>Files</b><span>{scanResult.total_files_found}</span></div>
                    <div className="compact-stat"><b>835s</b><span>{scanResult.imported_835}</span></div>
                    <div className="compact-stat"><b>Errors</b><span>{scanResult.errors}</span></div>
                  </>
                )}
              </section>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function Import() {
  return (
    <>
      <h2 className="mb-3">Revenue Intake</h2>

      <Tabs defaultActiveKey="cockpit" className="mb-3">
        <Tab eventKey="cockpit" title="Revenue Cockpit">
          <div className="mt-3">
            <RevenueIntakeCockpit />
          </div>
        </Tab>

        <Tab eventKey="source-tools" title="Source Tools">
          <Row className="mt-3">
            <Col md={8}>
              <PortalDownloads />
              <EOBScanner />
            </Col>
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>How Folder Scan Works</Card.Title>
                  <ol className="small">
                    <li>Place EOB files in <code>data/eobs/</code> folder (subfolders OK)</li>
                    <li>Click &quot;Preview&quot; to see what&apos;s new</li>
                    <li>Click &quot;Scan &amp; Import&quot; to process</li>
                    <li>Already-imported files are skipped automatically</li>
                    <li>Run again anytime to catch new files</li>
                  </ol>
                  <Alert variant="info" className="small mb-0">
                    Supports: .835, .edi (X12 ERA), .txt (auto-detected), .xlsx, .xls (smart column matching)
                  </Alert>
                </Card.Body>
              </Card>
              <ScanSnapStatus />
            </Col>
          </Row>
        </Tab>

        <Tab eventKey="flexible" title="Smart Import (Any Excel)">
          <Row className="mt-3">
            <Col md={8}>
              <FlexibleUploader />
            </Col>
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>How Smart Import Works</Card.Title>
                  <ol className="small">
                    <li>Drop any .xlsx/.xls file</li>
                    <li>System scans all sheets and detects headers</li>
                    <li>Columns are fuzzy-matched to billing fields</li>
                    <li>Preview the mapping before importing</li>
                    <li>Unrecognized columns are stored as extra data (nothing lost)</li>
                    <li>Duplicates are automatically skipped</li>
                  </ol>
                  <Alert variant="info" className="small mb-0">
                    Supports files up to 200MB. Large files may take a few minutes.
                  </Alert>
                </Card.Body>
              </Card>
            </Col>
          </Row>
        </Tab>

        <Tab eventKey="structured" title="OCMRI Excel (Structured)">
          <Row className="mt-3">
            <Col md={8}>
              <FileUploader
                endpoint="/import/excel"
                label='Upload OCMRI Excel File (.xlsx) &mdash; reads "Current" sheet'
              />
            </Col>
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>Structured Import Info</Card.Title>
                  <ul className="small">
                    <li>Reads the &quot;Current&quot; sheet only</li>
                    <li>Expects exact 22-column OCMRI format</li>
                    <li>Converts Excel serial dates</li>
                    <li>Deduplicates on patient+date+scan+modality</li>
                    <li>Normalizes SELFPAY variants</li>
                    <li>Detects PSMA PET scans</li>
                  </ul>
                </Card.Body>
              </Card>
            </Col>
          </Row>
        </Tab>

        <Tab eventKey="era" title="835 ERA Import">
          <Row className="mt-3">
            <Col md={8}>
              <FileUploader
                endpoint="/import/835"
                label="Upload 835 ERA File (.835, .edi, .txt)"
              />
            </Col>
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>835 Parser Info</Card.Title>
                  <ul className="small">
                    <li>Parses X12 835 format</li>
                    <li>Extracts BPR payment info</li>
                    <li>Extracts TRN check/EFT numbers</li>
                    <li>Parses CLP claims with status</li>
                    <li>Reads CAS adjustment codes</li>
                    <li>Captures SVC CPT codes</li>
                    <li>Links patient names via NM1</li>
                  </ul>
                </Card.Body>
              </Card>
            </Col>
          </Row>
        </Tab>

        <Tab eventKey="history" title="Import History">
          <div className="mt-3">
            <ImportHistory />
          </div>
        </Tab>
      </Tabs>
    </>
  );
}

export default Import;
