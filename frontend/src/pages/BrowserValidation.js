import React, { useState, useEffect, useCallback } from "react";
import {
  Container, Row, Col, Card, Button, Badge, Table, Form,
  Alert, Spinner, Tabs, Tab, ProgressBar, Modal,
} from "react-bootstrap";
import { toast } from "react-toastify";
import { FaGlobe, FaCheckCircle, FaTimesCircle, FaPlay, FaCog, FaExternalLinkAlt } from "react-icons/fa";
import api from "../services/api";

function BrowserValidation() {
  const [status, setStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(null); // Which validator is running
  const [results, setResults] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");

  // Config
  const [headless, setHeadless] = useState(true);
  const [limit, setLimit] = useState(20);
  const [carrier, setCarrier] = useState("");
  const [portalUrl, setPortalUrl] = useState("");
  const [showConfig, setShowConfig] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const [statusRes, summaryRes] = await Promise.all([
        api.get("/browser/status"),
        api.get("/browser/validation-summary"),
      ]);
      setStatus(statusRes.data);
      setSummary(summaryRes.data);
    } catch (err) {
      toast.error("Failed to load browser validation status");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const runValidation = async (type) => {
    setRunning(type);
    setResults(null);
    try {
      const params = new URLSearchParams();
      params.append("limit", limit);
      params.append("headless", headless);
      if (carrier) params.append("carrier", carrier);
      if (portalUrl) params.append("portal_url", portalUrl);

      const res = await api.post(`/browser/validate/${type}?${params.toString()}`, null, {
        timeout: 300000, // 5 min timeout for browser ops
      });
      setResults(res.data);
      setActiveTab("results");
      if (res.data.status === "completed") {
        toast.success(
          `Validation complete: ${res.data.matched}/${res.data.total_checked} matched`
        );
      } else {
        toast.warning(`Validation finished with status: ${res.data.status}`);
      }
    } catch (err) {
      toast.error(`Validation failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setRunning(null);
    }
  };

  const launchBrowser = async (type) => {
    try {
      const params = new URLSearchParams();
      if (portalUrl) params.append("portal_url", portalUrl);
      params.append("portal_type", type);

      const res = await api.post(`/browser/launch?${params.toString()}`);
      toast.info(res.data.message);
    } catch (err) {
      toast.error(`Launch failed: ${err.response?.data?.detail || err.message}`);
    }
  };

  if (loading) {
    return (
      <Container className="text-center py-5">
        <Spinner animation="border" /> Loading...
      </Container>
    );
  }

  return (
    <Container fluid>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h2><FaGlobe className="me-2" />Browser Data Validation</h2>
        <Button variant="outline-secondary" size="sm" onClick={() => setShowConfig(!showConfig)}>
          <FaCog className="me-1" /> Config
        </Button>
      </div>

      {!status?.browser_use_installed && (
        <Alert variant="warning">
          <strong>browser-use not installed.</strong> Run{" "}
          <code>pip install browser-use</code> in the backend container to enable browser validation.
        </Alert>
      )}

      {showConfig && (
        <Card className="mb-3">
          <Card.Body>
            <Row>
              <Col md={3}>
                <Form.Group>
                  <Form.Label>Records to check</Form.Label>
                  <Form.Control
                    type="number" value={limit} min={1} max={100}
                    onChange={(e) => setLimit(parseInt(e.target.value) || 20)}
                  />
                </Form.Group>
              </Col>
              <Col md={3}>
                <Form.Group>
                  <Form.Label>Filter by carrier</Form.Label>
                  <Form.Control
                    placeholder="e.g., BCBS"
                    value={carrier}
                    onChange={(e) => setCarrier(e.target.value)}
                  />
                </Form.Group>
              </Col>
              <Col md={3}>
                <Form.Group>
                  <Form.Label>Custom portal URL</Form.Label>
                  <Form.Control
                    placeholder="Override default URL"
                    value={portalUrl}
                    onChange={(e) => setPortalUrl(e.target.value)}
                  />
                </Form.Group>
              </Col>
              <Col md={3}>
                <Form.Group>
                  <Form.Label>Browser mode</Form.Label>
                  <Form.Check
                    type="switch" label={headless ? "Headless (fast)" : "Visible (debug)"}
                    checked={headless}
                    onChange={(e) => setHeadless(e.target.checked)}
                  />
                </Form.Group>
              </Col>
            </Row>
          </Card.Body>
        </Card>
      )}

      <Tabs activeKey={activeTab} onSelect={setActiveTab} className="mb-3">
        <Tab eventKey="overview" title="Overview">
          {/* Validator Cards */}
          <Row className="mb-4">
            <Col md={4}>
              <ValidatorCard
                name="Payer Portal"
                type="payer"
                icon="💳"
                description="Validate claim status and payment amounts against Office Ally"
                configured={status?.validators?.payer?.configured}
                recordCount={summary?.ready_for_payer_validation || 0}
                running={running === "payer"}
                onRun={() => runValidation("payer")}
                onLaunch={() => launchBrowser("payer")}
              />
            </Col>
            <Col md={4}>
              <ValidatorCard
                name="PACS System"
                type="pacs"
                icon="🏥"
                description="Validate patient demographics and studies against Purview/Candelis"
                configured={status?.validators?.pacs?.configured}
                recordCount={summary?.ready_for_pacs_validation || 0}
                running={running === "pacs"}
                onRun={() => runValidation("pacs")}
                onLaunch={() => launchBrowser("pacs")}
              />
            </Col>
            <Col md={4}>
              <ValidatorCard
                name="Bank Portal"
                type="bank"
                icon="🏦"
                description="Validate deposits and check/EFT numbers against bank records"
                configured={status?.validators?.bank?.configured}
                recordCount={summary?.ready_for_bank_validation || 0}
                running={running === "bank"}
                onRun={() => runValidation("bank")}
                onLaunch={() => launchBrowser("bank")}
              />
            </Col>
          </Row>

          {/* Summary Stats */}
          {summary && (
            <Card>
              <Card.Header>Database Summary</Card.Header>
              <Card.Body>
                <Row>
                  <Col md={3}>
                    <div className="text-center">
                      <h3>{summary.billing_records?.toLocaleString()}</h3>
                      <small className="text-muted">Billing Records</small>
                    </div>
                  </Col>
                  <Col md={3}>
                    <div className="text-center">
                      <h3>{summary.era_matched?.toLocaleString()}</h3>
                      <small className="text-muted">ERA-Matched Claims</small>
                    </div>
                  </Col>
                  <Col md={3}>
                    <div className="text-center">
                      <h3>{summary.era_with_check_eft?.toLocaleString()}</h3>
                      <small className="text-muted">ERA with Check/EFT</small>
                    </div>
                  </Col>
                  <Col md={3}>
                    <div className="text-center">
                      <h3>{summary.denied_claims?.toLocaleString()}</h3>
                      <small className="text-muted">Denied Claims</small>
                    </div>
                  </Col>
                </Row>
              </Card.Body>
            </Card>
          )}

          {/* Setup Instructions */}
          <Card className="mt-3">
            <Card.Header>Setup Instructions</Card.Header>
            <Card.Body>
              <h6>1. Set portal credentials as environment variables:</h6>
              <pre className="bg-light p-2 rounded" style={{ fontSize: "0.85em" }}>
{`# Office Ally
OFFICE_ALLY_USER=your_username
OFFICE_ALLY_PASS=your_password
PAYER_PORTAL_URL=https://pm.officeally.com/pm/login.aspx

# Purview / Candelis
PURVIEW_USER=your_username
PURVIEW_PASS=your_password
PACS_PORTAL_URL=https://your-purview-url/login

# Bank Portal
BANK_PORTAL_USER=your_username
BANK_PORTAL_PASS=your_password
BANK_PORTAL_URL=https://your-bank-url/login`}
              </pre>
              <h6>2. For portals with CAPTCHA/2FA:</h6>
              <p>Click "Open Browser" to launch a visible browser. Log in manually, then run validation with "Visible" browser mode.</p>
              <h6>3. Run validation:</h6>
              <p>Click "Run Validation" on any card. Results show field-by-field comparison with match/mismatch highlighting.</p>
            </Card.Body>
          </Card>
        </Tab>

        <Tab eventKey="results" title={`Results${results ? ` (${results.total_checked || 0})` : ""}`}>
          {results ? <ValidationResults data={results} /> : (
            <Alert variant="info">No validation results yet. Run a validator from the Overview tab.</Alert>
          )}
        </Tab>
      </Tabs>
    </Container>
  );
}

function ValidatorCard({ name, type, icon, description, configured, recordCount, running, onRun, onLaunch }) {
  return (
    <Card className={`h-100 ${running ? "border-primary" : ""}`}>
      <Card.Body>
        <div className="d-flex justify-content-between align-items-start">
          <h5>{icon} {name}</h5>
          {configured ? (
            <Badge bg="success">Configured</Badge>
          ) : (
            <Badge bg="warning">Not Configured</Badge>
          )}
        </div>
        <p className="text-muted small">{description}</p>
        <p className="mb-2">
          <strong>{recordCount.toLocaleString()}</strong> records ready to validate
        </p>
        {running ? (
          <div className="text-center py-2">
            <Spinner animation="border" size="sm" className="me-2" />
            Validating... (this may take a few minutes)
          </div>
        ) : (
          <div className="d-flex gap-2">
            <Button
              variant="primary" size="sm"
              onClick={onRun} disabled={!configured || recordCount === 0}
            >
              <FaPlay className="me-1" /> Run Validation
            </Button>
            <Button variant="outline-secondary" size="sm" onClick={onLaunch}>
              <FaExternalLinkAlt className="me-1" /> Open Browser
            </Button>
          </div>
        )}
      </Card.Body>
    </Card>
  );
}

function ValidationResults({ data }) {
  const { validator, status, total_checked, matched, mismatched, match_rate, errors, mismatches, results, screenshots } = data;

  return (
    <>
      {/* Summary Bar */}
      <Card className="mb-3">
        <Card.Body>
          <Row className="align-items-center">
            <Col md={2}>
              <Badge bg={status === "completed" ? "success" : status === "error" ? "danger" : "warning"} className="fs-6">
                {status.toUpperCase()}
              </Badge>
            </Col>
            <Col md={2}>
              <div className="text-center">
                <strong>{total_checked}</strong><br />
                <small>Checked</small>
              </div>
            </Col>
            <Col md={2}>
              <div className="text-center text-success">
                <strong>{matched}</strong><br />
                <small>Matched</small>
              </div>
            </Col>
            <Col md={2}>
              <div className="text-center text-danger">
                <strong>{mismatched}</strong><br />
                <small>Mismatched</small>
              </div>
            </Col>
            <Col md={4}>
              <ProgressBar>
                <ProgressBar variant="success" now={total_checked ? (matched / total_checked) * 100 : 0} label={match_rate} />
                <ProgressBar variant="danger" now={total_checked ? (mismatched / total_checked) * 100 : 0} />
              </ProgressBar>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {/* Errors */}
      {errors && errors.length > 0 && (
        <Alert variant="danger">
          <strong>Errors:</strong>
          <ul className="mb-0 mt-1">
            {errors.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </Alert>
      )}

      {/* Mismatches First */}
      {mismatches && mismatches.length > 0 && (
        <Card className="mb-3 border-danger">
          <Card.Header className="bg-danger text-white">
            Mismatches ({mismatches.length})
          </Card.Header>
          <Card.Body className="p-0">
            <Table striped hover size="sm" responsive className="mb-0">
              <thead>
                <tr>
                  <th>Record</th>
                  <th>Field</th>
                  <th>DB Value</th>
                  <th>Portal Value</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {mismatches.map((r, i) => (
                  <tr key={i}>
                    <td><code>{r.record_id}</code></td>
                    <td>{r.field}</td>
                    <td>{r.db_value || "—"}</td>
                    <td className="text-danger fw-bold">{r.portal_value || "—"}</td>
                    <td><small>{r.notes}</small></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card.Body>
        </Card>
      )}

      {/* All Results */}
      {results && results.length > 0 && (
        <Card>
          <Card.Header>All Results ({results.length})</Card.Header>
          <Card.Body className="p-0">
            <Table striped hover size="sm" responsive className="mb-0">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Record</th>
                  <th>Field</th>
                  <th>DB Value</th>
                  <th>Portal Value</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} className={r.match ? "" : "table-danger"}>
                    <td>
                      {r.match ? (
                        <FaCheckCircle className="text-success" />
                      ) : (
                        <FaTimesCircle className="text-danger" />
                      )}
                    </td>
                    <td><code>{r.record_id}</code></td>
                    <td>{r.field}</td>
                    <td>{r.db_value || "—"}</td>
                    <td>{r.portal_value || "—"}</td>
                    <td><small>{r.notes}</small></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card.Body>
        </Card>
      )}
    </>
  );
}

export default BrowserValidation;
