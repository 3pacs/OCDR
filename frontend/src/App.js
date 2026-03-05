import React from "react";
import { Routes, Route } from "react-router-dom";
import { ToastContainer } from "react-toastify";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Import from "./pages/Import";
import Underpayments from "./pages/Underpayments";
import FilingDeadlines from "./pages/FilingDeadlines";
import ERAPayments from "./pages/ERAPayments";

function App() {
  return (
    <>
      <ToastContainer position="top-right" autoClose={3000} />
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="import" element={<Import />} />
          <Route path="underpayments" element={<Underpayments />} />
          <Route path="filing-deadlines" element={<FilingDeadlines />} />
          <Route path="era-payments" element={<ERAPayments />} />
        </Route>
      </Routes>
    </>
  );
}

export default App;
