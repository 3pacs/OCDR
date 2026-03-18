import React, { useState, useEffect } from "react";
import { Modal, Spinner, Badge, Table, Row, Col, Card, Alert } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { formatMoney } from "../utils/format";
import api from "../services/api";

const STATUS_COLORS = {
  PAID: "success", UNPAID: "danger", UNDERPAID: "warning",
  DENIED: "danger", NO_CHARGE: "secondary",
};
const STATUS_LABELS = {
  PAID: "Paid", UNPAID: "Unpaid", UNDERPAID: "Underpaid",
  DENIED: "Denied", NO_CHARGE: "No Charge",
};

/**
 * PatientDrilldown — modal that shows full patient history.
 * Can be opened from any page by passing a patient name or billing record ID.
 *
 * Props:
 *   show: boolean
 *   onHide: function
 *   patientName: string (search by name)
 *   billingRecordId: number (search by specific record, then show that patient)
 */
export default function PatientDrilldown({ show, onHide, patientName, billingRecordId }) {
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!show) return;
    if (!patientName && !billingRecordId) return;

    setLoading(true);
    setError(null);
    setDetail(null);

    const fetchDetail = async () => {
      try {
        let name = patientName;
        if (!name && billingRecordId) {
          const brRes = await api.get(`/analytics/patients/by-record/${billingRecordId}`);
          name = brRes.data.patient_name;
        }
        if (!name) {
          setError("No patient identifier provided");
          return;
        }
        const res = await api.get(`/analytics/patients/${encodeURIComponent(name)}/detail`);
        setDetail(res.data);
      } catch (err) {
        setError(err.response?.data?.detail || "Could not load patient details");
      } finally {
        setLoading(false);
      }
    };
    fetchDetail();
  }, [show, patientName, billingRecordId]);

  const summary = detail?.summary;
  const visits = detail?.visits || [];
  const eraMatches = detail?.era_matches || [];

  const goToFullPage = () => {
    onHide();
    navigate("/patients");
  };

  return (
    <Modal show={show} onHide={onHide} size="xl" scrollable>
      <Modal.Header closeButton>
        <Modal.Title>
          {summary ? summary.patient_name : "Patient History"}
          {summary?.patient_id && <small className="text-muted ms-2">Chart #{summary.patient_id}</small>}
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {loading && <div className="text-center py-4"><Spinner animation="border" /> Loading...</div>}
        {error && <Alert variant="danger">{error}</Alert>}

        {summary && (
          <>
            {/* KPI row */}
            <Row className="g-2 mb-3">
              <Col>
                <Card className="border-0 bg-light text-center p-2">
                  <div className="text-muted small">Visits</div>
                  <div className="fs-5 fw-bold">{summary.total_visits}</div>
                </Card>
              </Col>
              <Col>
                <Card className="border-0 bg-light text-center p-2">
                  <div className="text-muted small">Total Paid</div>
                  <div className="fs-5 fw-bold text-success">{formatMoney(summary.total_paid)}</div>
                </Card>
              </Col>
              <Col>
                <Card className="border-0 bg-light text-center p-2">
                  <div className="text-muted small">Expected</div>
                  <div className="fs-5 fw-bold">{formatMoney(summary.total_expected)}</div>
                </Card>
              </Col>
              <Col>
                <Card className="border-0 bg-light text-center p-2">
                  <div className="text-muted small">Collection</div>
                  <div className={`fs-5 fw-bold ${summary.collection_rate >= 80 ? "text-success" : "text-danger"}`}>
                    {summary.collection_rate}%
                  </div>
                </Card>
              </Col>
              <Col>
                <Card className="border-0 bg-light text-center p-2">
                  <div className="text-muted small">Unpaid</div>
                  <div className={`fs-5 fw-bold ${summary.total_unpaid > 0 ? "text-danger" : "text-success"}`}>
                    {summary.total_unpaid}
                  </div>
                </Card>
              </Col>
            </Row>

            <div className="text-muted small mb-2">
              {summary.topaz_id && <>Topaz: <strong>{summary.topaz_id}</strong> | </>}
              Insurance: <strong>{summary.carriers?.join(", ") || "—"}</strong>
              {summary.birth_date && <> | DOB: <strong>{summary.birth_date}</strong></>}
              {" | "}Range: {summary.first_visit} — {summary.last_visit}
            </div>

            {/* Visit table */}
            <Table striped hover responsive size="sm" className="small">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Modality</th>
                  <th>Scan</th>
                  <th>Doctor</th>
                  <th>Insurance</th>
                  <th className="text-end">Primary</th>
                  <th className="text-end">Secondary</th>
                  <th className="text-end">Total</th>
                  <th>Status</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {visits.map((v, i) => (
                  <tr key={i} className={v.status === "DENIED" || v.status === "UNPAID" ? "table-danger" : v.status === "UNDERPAID" ? "table-warning" : ""}>
                    <td>{v.service_date}</td>
                    <td>{v.modality}</td>
                    <td>
                      {v.scan_type}
                      {v.gado_used && <Badge bg="info" className="ms-1">Gado</Badge>}
                    </td>
                    <td>{v.referring_doctor}</td>
                    <td>{v.insurance_carrier}</td>
                    <td className="text-end">{formatMoney(v.primary_payment)}</td>
                    <td className="text-end">{formatMoney(v.secondary_payment)}</td>
                    <td className="text-end fw-bold">{formatMoney(v.total_payment)}</td>
                    <td>
                      <Badge bg={STATUS_COLORS[v.status] || "secondary"}>
                        {STATUS_LABELS[v.status] || v.status}
                      </Badge>
                    </td>
                    <td className="small">
                      {v.reason || "—"}
                      {v.denial_reason_code && <Badge bg="dark" className="ms-1">{v.denial_reason_code}</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>

            {/* ERA matches section */}
            {eraMatches.length > 0 && (
              <>
                <h6 className="mt-3">ERA Claim Matches ({eraMatches.length})</h6>
                <Table striped responsive size="sm" className="small">
                  <thead>
                    <tr>
                      <th>Claim ID</th>
                      <th>Payer</th>
                      <th>Date</th>
                      <th className="text-end">Billed</th>
                      <th className="text-end">Paid</th>
                      <th>Confidence</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {eraMatches.map((e, i) => (
                      <tr key={i}>
                        <td>{e.claim_id}</td>
                        <td>{e.payer_name}</td>
                        <td>{e.service_date}</td>
                        <td className="text-end">{formatMoney(e.billed_amount)}</td>
                        <td className="text-end">{formatMoney(e.paid_amount)}</td>
                        <td><Badge bg={e.confidence >= 0.95 ? "success" : e.confidence >= 0.85 ? "primary" : "warning"}>{(e.confidence * 100).toFixed(0)}%</Badge></td>
                        <td>{e.claim_status}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </>
            )}
          </>
        )}
      </Modal.Body>
      <Modal.Footer>
        <small className="text-muted me-auto" style={{ cursor: "pointer" }} onClick={goToFullPage}>
          Open full patient page &rarr;
        </small>
      </Modal.Footer>
    </Modal>
  );
}

/**
 * PatientLink — inline clickable patient name that opens the drilldown.
 *
 * Usage: <PatientLink name="DOE, JOHN" /> or <PatientLink name={row.patient_name} />
 */
export function PatientLink({ name, billingRecordId, children }) {
  const [show, setShow] = useState(false);

  if (!name && !billingRecordId) return <>{children || "--"}</>;

  return (
    <>
      <span
        role="button"
        tabIndex={0}
        className="text-primary"
        style={{ cursor: "pointer", textDecoration: "underline dotted" }}
        onClick={(e) => { e.stopPropagation(); setShow(true); }}
        onKeyDown={(e) => e.key === "Enter" && setShow(true)}
      >
        {children || name || "View Patient"}
      </span>
      <PatientDrilldown
        show={show}
        onHide={() => setShow(false)}
        patientName={name}
        billingRecordId={billingRecordId}
      />
    </>
  );
}
