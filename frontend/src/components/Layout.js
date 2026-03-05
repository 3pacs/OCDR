import React from "react";
import { Outlet, NavLink } from "react-router-dom";
import { Container, Nav, Navbar } from "react-bootstrap";

function Layout() {
  return (
    <>
      <Navbar bg="dark" variant="dark" expand="lg" className="mb-3">
        <Container fluid>
          <Navbar.Brand href="/">OCMRI Billing</Navbar.Brand>
          <Navbar.Toggle aria-controls="main-nav" />
          <Navbar.Collapse id="main-nav">
            <Nav className="me-auto">
              <Nav.Link as={NavLink} to="/">Dashboard</Nav.Link>
              <Nav.Link as={NavLink} to="/import">Import Data</Nav.Link>
              <Nav.Link as={NavLink} to="/matching">Matching</Nav.Link>
              <Nav.Link as={NavLink} to="/underpayments">Underpayments</Nav.Link>
              <Nav.Link as={NavLink} to="/filing-deadlines">Filing Deadlines</Nav.Link>
              <Nav.Link as={NavLink} to="/era-payments">ERA Payments</Nav.Link>
            </Nav>
          </Navbar.Collapse>
        </Container>
      </Navbar>
      <Container fluid className="px-4">
        <Outlet />
      </Container>
    </>
  );
}

export default Layout;
