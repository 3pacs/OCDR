import React from "react";
import { Routes, Route } from "react-router-dom";
import { ToastContainer } from "react-toastify";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Import from "./pages/Import";
import Underpayments from "./pages/Underpayments";
import FilingDeadlines from "./pages/FilingDeadlines";
import ERAPayments from "./pages/ERAPayments";
import Matching from "./pages/Matching";
import Denials from "./pages/Denials";
import SecondaryFollowup from "./pages/SecondaryFollowup";
import Insights from "./pages/Insights";
import PayerMonitor from "./pages/PayerMonitor";
import Physicians from "./pages/Physicians";
import PSMADashboard from "./pages/PSMADashboard";
import GadoDashboard from "./pages/GadoDashboard";
import Duplicates from "./pages/Duplicates";
import DenialAnalytics from "./pages/DenialAnalytics";
import PatientLookup from "./pages/PatientLookup";

function App() {
  return (
    <>
      <ToastContainer position="top-right" autoClose={3000} />
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="patients" element={<PatientLookup />} />
          <Route path="import" element={<Import />} />
          <Route path="matching" element={<Matching />} />
          <Route path="denials" element={<Denials />} />
          <Route path="denial-analytics" element={<DenialAnalytics />} />
          <Route path="underpayments" element={<Underpayments />} />
          <Route path="filing-deadlines" element={<FilingDeadlines />} />
          <Route path="secondary-followup" element={<SecondaryFollowup />} />
          <Route path="duplicates" element={<Duplicates />} />
          <Route path="era-payments" element={<ERAPayments />} />
          <Route path="payer-monitor" element={<PayerMonitor />} />
          <Route path="physicians" element={<Physicians />} />
          <Route path="psma" element={<PSMADashboard />} />
          <Route path="gado" element={<GadoDashboard />} />
          <Route path="insights" element={<Insights />} />
        </Route>
      </Routes>
    </>
  );
}

export default App;
