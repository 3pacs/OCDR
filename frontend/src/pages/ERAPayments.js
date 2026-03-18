import React, { useState, useEffect } from "react";
import { Card, Spinner, Alert, Row, Col, Form, Button } from "react-bootstrap";
import api from "../services/api";
import { formatMoney } from "../utils/format";
import SortableTable from "../components/SortableTable";

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

  const columns = [
    { key: "filename", label: "File", className: "text-truncate", filterable: true, filterPlaceholder: "Filename..." },
    { key: "payer_name", label: "Payer", filterable: true, filterPlaceholder: "Payer..." },
    { key: "check_eft_number", label: "Check/EFT #" },
    { key: "payment_method", label: "Method" },
    { key: "payment_date", label: "Date" },
    { key: "payment_amount", label: "Amount", className: "text-end", render: (v) => formatMoney(v) },
    {
      key: "parsed_at", label: "Parsed At",
      render: (v) => v ? new Date(v).toLocaleString() : "--",
    },
  ];

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
            <SortableTable columns={columns} data={payments} rowKey="id" />
          )}

          <div className="d-flex justify-content-between mt-3">
            <Button size="sm" variant="outline-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <span className="text-muted small">Page {page} &mdash; {total} total</span>
            <Button size="sm" variant="outline-secondary" disabled={payments.length < 50} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </Card.Body>
      </Card>
    </>
  );
}

export default ERAPayments;
