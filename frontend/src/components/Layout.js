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
              {/* TODO: Step 8-9 - Add nav links */}
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
