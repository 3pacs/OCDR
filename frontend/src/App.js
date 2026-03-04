import React from "react";
import { Routes, Route } from "react-router-dom";
import { ToastContainer } from "react-toastify";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";

function App() {
  return (
    <>
      <ToastContainer position="top-right" autoClose={3000} />
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          {/* TODO: Step 8-9 - Add routes */}
          {/* <Route path="crosswalk" element={<CrosswalkManager />} /> */}
          {/* <Route path="studies" element={<Studies />} /> */}
          {/* <Route path="payments" element={<Payments />} /> */}
          {/* <Route path="eob-import" element={<EOBImport />} /> */}
          {/* <Route path="reconciliation" element={<Reconciliation />} /> */}
          {/* <Route path="reports" element={<Reports />} /> */}
          {/* <Route path="admin" element={<Admin />} /> */}
        </Route>
      </Routes>
    </>
  );
}

export default App;
