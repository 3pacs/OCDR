import React, { useState } from "react";
import { Modal, Form, Button, Spinner, Alert, Table, Badge } from "react-bootstrap";
import { toast } from "react-toastify";
import { formatMoney } from "../utils/format";
import api from "../services/api";

/**
 * ManualLinkModal — allows user to search for a billing record and link
 * an unmatched ERA claim to it.
 *
 * Props:
 *   show: boolean
 *   onHide: function
 *   claim: object (the unmatched ERA claim line)
 *   onLinked: function (callback after successful link)
 */
export default function ManualLinkModal({ show, onHide, claim, onLinked }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [linking, setLinking] = useState(false);
  const [error, setError] = useState(null);
  const [notes, setNotes] = useState("");

  const handleSearch = async () => {
    if (query.length < 2) return;
    setSearching(true);
    setError(null);
    try {
      const res = await api.get("/matching/billing-search", {
        params: { q: query, limit: 20 },
      });
      setResults(res.data.results || []);
    } catch (err) {
      setError("Search failed");
    } finally {
      setSearching(false);
    }
  };

  const handleLink = async (billingRecordId) => {
    setLinking(true);
    setError(null);
    try {
      await api.post("/matching/correct-match", {
        era_claim_line_id: claim.id,
        billing_record_id: billingRecordId,
        notes: notes || `Manual link from unmatched claims UI`,
      });
      toast.success("Claim linked successfully");
      onLinked?.();
      onHide();
    } catch (err) {
      setError(err.response?.data?.detail || "Linking failed");
    } finally {
      setLinking(false);
    }
  };

  const handleClose = () => {
    setQuery("");
    setResults([]);
    setError(null);
    setNotes("");
    onHide();
  };

  return (
    <Modal show={show} onHide={handleClose} size="lg" scrollable>
      <Modal.Header closeButton>
        <Modal.Title>Link Claim to Billing Record</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {claim && (
          <Alert variant="info" className="small">
            <strong>ERA Claim:</strong> {claim.patient_name || "Unknown"} |
            Date: {claim.service_date || "—"} |
            Payer: {claim.payer_name || "—"} |
            Claim ID: {claim.claim_id || "—"} |
            Paid: {formatMoney(claim.paid_amount)}
          </Alert>
        )}

        <Form.Group className="mb-3">
          <Form.Label className="small fw-bold">Search billing records by patient name, chart ID, or date</Form.Label>
          <div className="d-flex gap-2">
            <Form.Control
              size="sm"
              placeholder="e.g., SMITH or 9125 or 2025-01-15"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              autoFocus
            />
            <Button size="sm" variant="primary" onClick={handleSearch} disabled={searching || query.length < 2}>
              {searching ? <Spinner size="sm" /> : "Search"}
            </Button>
          </div>
        </Form.Group>

        {error && <Alert variant="danger" className="small">{error}</Alert>}

        {results.length > 0 && (
          <>
            <p className="text-muted small">{results.length} billing records found. Click "Link" to connect this claim.</p>
            <Table size="sm" striped hover responsive className="small">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Date</th>
                  <th>Carrier</th>
                  <th>Modality</th>
                  <th className="text-end">Total</th>
                  <th>Chart ID</th>
                  <th>Topaz ID</th>
                  <th>ERA Linked?</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.patient_name}</strong></td>
                    <td>{r.service_date}</td>
                    <td>{r.insurance_carrier}</td>
                    <td>{r.modality}</td>
                    <td className="text-end">{formatMoney(r.total_payment)}</td>
                    <td>{r.patient_id || "—"}</td>
                    <td>{r.topaz_id || "—"}</td>
                    <td>
                      {r.era_claim_id
                        ? <Badge bg="success">Yes</Badge>
                        : <Badge bg="secondary">No</Badge>
                      }
                    </td>
                    <td>
                      <Button
                        size="sm"
                        variant="outline-primary"
                        onClick={() => handleLink(r.id)}
                        disabled={linking}
                      >
                        {linking ? <Spinner size="sm" /> : "Link"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </>
        )}

        <Form.Group className="mt-3">
          <Form.Label className="small">Notes (optional)</Form.Label>
          <Form.Control
            as="textarea"
            rows={2}
            size="sm"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Reason for manual link..."
          />
        </Form.Group>
      </Modal.Body>
    </Modal>
  );
}
