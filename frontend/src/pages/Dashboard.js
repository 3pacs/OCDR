import React from "react";
import { Card, Col, Row } from "react-bootstrap";

function Dashboard() {
  return (
    <>
      <h2 className="mb-4">Dashboard</h2>
      <Row className="g-3">
        <Col md={3}>
          <Card>
            <Card.Body>
              <Card.Title className="text-muted small">Crosswalk Progress</Card.Title>
              <Card.Text className="fs-3">--% mapped</Card.Text>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card>
            <Card.Body>
              <Card.Title className="text-muted small">Pending Rule Reviews</Card.Title>
              <Card.Text className="fs-3">--</Card.Text>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card>
            <Card.Body>
              <Card.Title className="text-muted small">Unmatched Records</Card.Title>
              <Card.Text className="fs-3">--</Card.Text>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card>
            <Card.Body>
              <Card.Title className="text-muted small">Underpayment Flags</Card.Title>
              <Card.Text className="fs-3">--</Card.Text>
            </Card.Body>
          </Card>
        </Col>
      </Row>
      <p className="text-muted mt-4">
        Dashboard data will populate after database schema setup and data ingestion (Steps 2-4).
      </p>
    </>
  );
}

export default Dashboard;
