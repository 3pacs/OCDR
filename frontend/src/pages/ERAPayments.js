import React, { useState, useEffect } from "react";
import { Card, Table, Spinner, Alert, Row, Col, Form } from "react-bootstrap";
import api from "../services/api";

function ERAPayments() {
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [payer, setPayer] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    setLoading(true);
    const params = { page, per_page: 50 };
    if (payer) params.payer = payer;

    api.get("/era/payments", { params })
      .then((r) => {
        setPayments(r.data.items || []);
        setTotal(r.data.total || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [payer, page]);

  const formatMoney = (v) => {
    if (v == null) return "--";
    return "$" + v.toLocaleString(undefined, { minimumFractionDigits: 2 });
  };

  return (
    <>
      <h2 className="mb-4">ERA Payments (F-02)</h2>

      <Card className="border-0 shadow-sm">
        <Card.Body>
          <Row className="mb-3">
            <Col md={4}>
              <Form.Control
                placeholder="Filter by payer name..."
                value={payer}
                onChange={(e) => { setPayer(e.target.value); setPage(1); }}
              />
            </Col>
            <Col md={4}>
              <span className="text-muted small">Total: {total} payments</span>
            </Col>
          </Row>

          {loading ? (
            <div className="text-center py-4"><Spinner animation="border" /></div>
          ) : payments.length === 0 ? (
            <Alert variant="info">No ERA payments found. Import 835 files first.</Alert>
          ) : (
            <Table striped hover responsive size="sm">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Payer</th>
                  <th>Check/EFT #</th>
                  <th>Method</th>
                  <th>Date</th>
                  <th className="text-end">Amount</th>
                  <th>Parsed At</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((p) => (
                  <tr key={p.id}>
                    <td className="text-truncate" style={{ maxWidth: 200 }}>{p.filename}</td>
                    <td>{p.payer_name ?? "--"}</td>
                    <td>{p.check_eft_number ?? "--"}</td>
                    <td>{p.payment_method ?? "--"}</td>
                    <td>{p.payment_date ?? "--"}</td>
                    <td className="text-end">{formatMoney(p.payment_amount)}</td>
                    <td>{p.parsed_at ? new Date(p.parsed_at).toLocaleString() : "--"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}

          <div className="d-flex justify-content-between mt-3">
            <button className="btn btn-sm btn-outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="text-muted small">Page {page} &mdash; {total} total</span>
            <button className="btn btn-sm btn-outline-secondary" disabled={payments.length < 50} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </Card.Body>
      </Card>
    </>
  );
}

export default ERAPayments;
