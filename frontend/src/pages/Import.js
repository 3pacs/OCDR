import React, { useState, useCallback, useEffect } from "react";
import { Card, Row, Col, Button, Alert, Spinner, Tab, Tabs, Table, Badge, Form, ProgressBar } from "react-bootstrap";
import { useDropzone } from "react-dropzone";
import api from "../services/api";

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

function Import() {
  return (
    <>
      <h2 className="mb-4">Data Import</h2>

      <Tabs defaultActiveKey="flexible" className="mb-4">
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
