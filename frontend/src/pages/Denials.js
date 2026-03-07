import React, { useState, useEffect, useCallback } from "react";
import {
  Card, Table, Spinner, Alert, Row, Col, Form, Badge, Button,
  Modal, ButtonGroup,
} from "react-bootstrap";
import { toast } from "react-toastify";
import api from "../services/api";

function Denials() {
  const [summary, setSummary] = useState(null);
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [carrier, setCarrier] = useState("");
  const [modality, setModality] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [viewMode, setViewMode] = useState("all"); // "all" or "queue"
  const [selected, setSelected] = useState(new Set());

  // Modal state
  const [showAppeal, setShowAppeal] = useState(null);
  const [showResolve, setShowResolve] = useState(null);
  const [appealNotes, setAppealNotes] = useState("");
  const [resolution, setResolution] = useState("RESOLVED");
  const [resolveAmount, setResolveAmount] = useState("");

  const loadSummary = useCallback(() => {
    api.get("/denials/summary").then((r) => setSummary(r.data)).catch(() => {});
  }, []);

  const loadClaims = useCallback(() => {
    setLoading(true);
    if (viewMode === "queue") {
      api.get("/denials/queue", { params: { limit: 50 } })
        .then((r) => {
          setClaims(r.data.queue || []);
          setTotal(r.data.total || 0);
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    } else {
      const params = { page, per_page: 50 };
      if (carrier) params.carrier = carrier;
      if (modality) params.modality = modality;
      if (statusFilter) params.status = statusFilter;
      api.get("/denials", { params })
        .then((r) => {
          setClaims(r.data.denials || []);
          setTotal(r.data.total || 0);
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [viewMode, carrier, modality, statusFilter, page]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadClaims(); }, [loadClaims]);

  const formatMoney = (v) => {
    if (v == null) return "--";
    const prefix = v < 0 ? "-$" : "$";
    return prefix + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2 });
  };

  const statusBadge = (s) => {
    const map = {
      DENIED: "danger",
      APPEALED: "warning",
      RESOLVED: "success",
      WRITTEN_OFF: "secondary",
    };
    return <Badge bg={map[s] || "info"}>{s || "DENIED"}</Badge>;
  };

  const handleAppeal = async (id) => {
    await api.post(`/denials/${id}/appeal`, { notes: appealNotes });
    toast.success("Claim marked as appealed");
    setShowAppeal(null);
    setAppealNotes("");
    loadClaims();
    loadSummary();
  };

  const handleResolve = async (id) => {
    await api.post(`/denials/${id}/resolve`, {
      resolution,
      amount: resolveAmount ? parseFloat(resolveAmount) : null,
    });
    toast.success(`Claim ${resolution.toLowerCase()}`);
    setShowResolve(null);
    setResolveAmount("");
    loadClaims();
    loadSummary();
  };

  const handleBulkAppeal = async () => {
    if (selected.size === 0) return;
    await api.post("/denials/bulk-appeal", { ids: Array.from(selected) });
    toast.success(`${selected.size} claims marked as appealed`);
    setSelected(new Set());
    loadClaims();
    loadSummary();
  };

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === claims.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(claims.map((c) => c.id)));
    }
  };

  return (
    <>
      <h2 className="mb-4">Denial Tracking & Appeal Queue (F-04)</h2>

      {summary && (
        <Row className="g-3 mb-4">
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Total Denied</div>
                <div className="fs-3 fw-bold text-danger">{summary.total_denied?.toLocaleString()}</div>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Pending</div>
                <div className="fs-3 fw-bold text-warning">{summary.pending?.toLocaleString()}</div>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Appealed</div>
                <div className="fs-3 fw-bold text-info">{summary.appealed?.toLocaleString()}</div>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="border-0 shadow-sm text-center">
              <Card.Body>
                <div className="text-muted small">Resolved</div>
                <div className="fs-3 fw-bold text-success">{summary.resolved?.toLocaleString()}</div>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}

      {summary?.by_carrier?.length > 0 && (
        <Card className="border-0 shadow-sm mb-4">
          <Card.Body>
            <h6>Denials by Carrier</h6>
            <div className="d-flex flex-wrap gap-2">
              {summary.by_carrier.map((c) => (
                <Badge key={c.carrier} bg="outline-danger" className="border border-danger text-danger px-3 py-2">
                  {c.carrier}: {c.count}
                </Badge>
              ))}
            </div>
          </Card.Body>
        </Card>
      )}

      <Card className="border-0 shadow-sm">
        <Card.Body>
          <Row className="mb-3 align-items-center">
            <Col md={2}>
              <ButtonGroup size="sm">
                <Button
                  variant={viewMode === "all" ? "primary" : "outline-primary"}
                  onClick={() => { setViewMode("all"); setPage(1); }}
                >All Denials</Button>
                <Button
                  variant={viewMode === "queue" ? "primary" : "outline-primary"}
                  onClick={() => { setViewMode("queue"); setPage(1); }}
                >Priority Queue</Button>
              </ButtonGroup>
            </Col>
            {viewMode === "all" && (
              <>
                <Col md={3}>
                  <Form.Control
                    size="sm"
                    placeholder="Filter by carrier..."
                    value={carrier}
                    onChange={(e) => { setCarrier(e.target.value.toUpperCase()); setPage(1); }}
                  />
                </Col>
                <Col md={2}>
                  <Form.Select size="sm" value={modality} onChange={(e) => { setModality(e.target.value); setPage(1); }}>
                    <option value="">All Modalities</option>
                    <option value="CT">CT</option>
                    <option value="HMRI">HMRI</option>
                    <option value="PET">PET</option>
                    <option value="BONE">BONE</option>
                    <option value="OPEN">OPEN</option>
                    <option value="DX">DX</option>
                  </Form.Select>
                </Col>
                <Col md={2}>
                  <Form.Select size="sm" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
                    <option value="">All Statuses</option>
                    <option value="DENIED">Denied</option>
                    <option value="APPEALED">Appealed</option>
                    <option value="RESOLVED">Resolved</option>
                    <option value="WRITTEN_OFF">Written Off</option>
                  </Form.Select>
                </Col>
              </>
            )}
            <Col md="auto" className="ms-auto">
              {selected.size > 0 && (
                <Button size="sm" variant="warning" onClick={handleBulkAppeal}>
                  Bulk Appeal ({selected.size})
                </Button>
              )}
            </Col>
          </Row>

          {loading ? (
            <div className="text-center py-4"><Spinner animation="border" /></div>
          ) : claims.length === 0 ? (
            <Alert variant="info">No denied claims found.</Alert>
          ) : (
            <Table striped hover responsive size="sm">
              <thead>
                <tr>
                  <th><Form.Check type="checkbox" onChange={toggleAll} checked={selected.size === claims.length && claims.length > 0} /></th>
                  <th>Patient</th>
                  <th>Date</th>
                  <th>Carrier</th>
                  <th>Modality</th>
                  <th className="text-end">Billed</th>
                  <th className="text-end">Paid</th>
                  <th>Reason</th>
                  <th>Status</th>
                  {viewMode === "queue" && <th className="text-end">Score</th>}
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {claims.map((c) => (
                  <tr key={c.id}>
                    <td><Form.Check type="checkbox" checked={selected.has(c.id)} onChange={() => toggleSelect(c.id)} /></td>
                    <td>{c.patient_name}</td>
                    <td>{c.service_date}</td>
                    <td>{c.insurance_carrier}</td>
                    <td>{c.modality}</td>
                    <td className="text-end">{formatMoney(c.billed_amount)}</td>
                    <td className="text-end">{formatMoney(c.total_payment)}</td>
                    <td>
                      {c.cas_reason_code && (
                        <Badge bg="dark" className="me-1">{c.cas_group_code}-{c.cas_reason_code}</Badge>
                      )}
                      {c.denial_reason_code && !c.cas_reason_code && (
                        <Badge bg="dark">{c.denial_reason_code}</Badge>
                      )}
                    </td>
                    <td>{statusBadge(c.denial_status)}</td>
                    {viewMode === "queue" && (
                      <td className="text-end fw-bold">{c.recoverability_score?.toLocaleString()}</td>
                    )}
                    <td>
                      <ButtonGroup size="sm">
                        {(c.denial_status === "DENIED" || !c.denial_status) && (
                          <Button variant="outline-warning" size="sm" onClick={() => setShowAppeal(c.id)}>Appeal</Button>
                        )}
                        {c.denial_status !== "RESOLVED" && c.denial_status !== "WRITTEN_OFF" && (
                          <Button variant="outline-success" size="sm" onClick={() => setShowResolve(c.id)}>Resolve</Button>
                        )}
                      </ButtonGroup>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}

          {viewMode === "all" && (
            <div className="d-flex justify-content-between mt-3">
              <Button size="sm" variant="outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <span className="text-muted small">Page {page} &middot; {total} total</span>
              <Button size="sm" variant="outline-secondary" disabled={claims.length < 50} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          )}
        </Card.Body>
      </Card>

      {/* Appeal Modal */}
      <Modal show={showAppeal !== null} onHide={() => setShowAppeal(null)}>
        <Modal.Header closeButton>
          <Modal.Title>File Appeal</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form.Group>
            <Form.Label>Appeal Notes</Form.Label>
            <Form.Control
              as="textarea"
              rows={3}
              value={appealNotes}
              onChange={(e) => setAppealNotes(e.target.value)}
              placeholder="Reason for appeal, supporting documentation..."
            />
          </Form.Group>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowAppeal(null)}>Cancel</Button>
          <Button variant="warning" onClick={() => handleAppeal(showAppeal)}>File Appeal</Button>
        </Modal.Footer>
      </Modal>

      {/* Resolve Modal */}
      <Modal show={showResolve !== null} onHide={() => setShowResolve(null)}>
        <Modal.Header closeButton>
          <Modal.Title>Resolve Denial</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form.Group className="mb-3">
            <Form.Label>Resolution</Form.Label>
            <Form.Select value={resolution} onChange={(e) => setResolution(e.target.value)}>
              <option value="RESOLVED">Resolved (Paid)</option>
              <option value="WRITTEN_OFF">Written Off</option>
            </Form.Select>
          </Form.Group>
          {resolution === "RESOLVED" && (
            <Form.Group>
              <Form.Label>Amount Received</Form.Label>
              <Form.Control
                type="number"
                step="0.01"
                value={resolveAmount}
                onChange={(e) => setResolveAmount(e.target.value)}
                placeholder="0.00"
              />
            </Form.Group>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowResolve(null)}>Cancel</Button>
          <Button variant="success" onClick={() => handleResolve(showResolve)}>Confirm</Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}

export default Denials;
