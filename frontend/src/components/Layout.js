import React from "react";
import { Outlet, NavLink } from "react-router-dom";
import { Container, Nav, Navbar, NavDropdown } from "react-bootstrap";

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
              <Nav.Link as={NavLink} to="/patients">Patients</Nav.Link>
              <Nav.Link as={NavLink} to="/import">Import</Nav.Link>
              <Nav.Link as={NavLink} to="/matching">Matching</Nav.Link>
              <NavDropdown title="Revenue" id="revenue-dropdown">
                <NavDropdown.Item as={NavLink} to="/denials">Denial Queue</NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/denial-analytics">Denial Analytics</NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/underpayments">Underpayments</NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/filing-deadlines">Filing Deadlines</NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/secondary-followup">Secondary F/U</NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/duplicates">Duplicates</NavDropdown.Item>
              </NavDropdown>
              <NavDropdown title="Analytics" id="analytics-dropdown">
                <NavDropdown.Item as={NavLink} to="/payer-monitor">Payer Monitor</NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/physicians">Physicians</NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/psma">PSMA PET</NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/gado">Gado Contrast</NavDropdown.Item>
              </NavDropdown>
              <Nav.Link as={NavLink} to="/era-payments">ERA Payments</Nav.Link>
              <Nav.Link as={NavLink} to="/insights">Insights</Nav.Link>
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
