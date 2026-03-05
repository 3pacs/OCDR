import React, { useState, useCallback } from "react";
import { Card, Row, Col, Button, Alert, Spinner, Tab, Tabs } from "react-bootstrap";
import { useDropzone } from "react-dropzone";
import api from "../services/api";

function FileUploader({ accept, endpoint, label, onResult }) {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const onDrop = useCallback(async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    const formData = new FormData();
    formData.append("file", file);

    setUploading(true);
    setError(null);
    setResult(null);

    try {
      const res = await api.post(endpoint, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(res.data);
      if (onResult) onResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setUploading(false);
    }
  }, [endpoint, onResult]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
  });

  return (
    <Card className="border-0 shadow-sm">
      <Card.Body>
        <Card.Title>{label}</Card.Title>
        <div
          {...getRootProps()}
          style={{
            border: "2px dashed #ccc",
            borderRadius: 8,
            padding: 40,
            textAlign: "center",
            cursor: "pointer",
            backgroundColor: isDragActive ? "#e8f4fd" : "#fafafa",
          }}
        >
          <input {...getInputProps()} />
          {uploading ? (
            <Spinner animation="border" />
          ) : isDragActive ? (
            <p className="mb-0">Drop file here...</p>
          ) : (
            <p className="mb-0">Drag & drop a file here, or click to select</p>
          )}
        </div>

        {result && (
          <Alert variant="success" className="mt-3">
            <strong>Import complete!</strong>
            <pre className="mb-0 mt-2" style={{ fontSize: "0.85rem" }}>
              {JSON.stringify(result, null, 2)}
            </pre>
          </Alert>
        )}

        {error && (
          <Alert variant="danger" className="mt-3">{error}</Alert>
        )}
      </Card.Body>
    </Card>
  );
}

function Import() {
  return (
    <>
      <h2 className="mb-4">Data Import</h2>

      <Tabs defaultActiveKey="excel" className="mb-4">
        <Tab eventKey="excel" title="Excel Import (F-01)">
          <Row className="mt-3">
            <Col md={8}>
              <FileUploader
                endpoint="/import/excel"
                label="Upload OCMRI Excel File (.xlsx)"
                accept={{ "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"] }}
              />
            </Col>
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>Import Info</Card.Title>
                  <ul className="small">
                    <li>Reads the &quot;Current&quot; sheet</li>
                    <li>Maps all 22 columns per spec</li>
                    <li>Converts Excel serial dates</li>
                    <li>Deduplicates on patient+date+scan+modality</li>
                    <li>Normalizes SELFPAY variants</li>
                    <li>Detects PSMA PET scans</li>
                    <li>Batch inserts 500 rows at a time</li>
                  </ul>
                </Card.Body>
              </Card>
            </Col>
          </Row>
        </Tab>

        <Tab eventKey="era" title="835 ERA Import (F-02)">
          <Row className="mt-3">
            <Col md={8}>
              <FileUploader
                endpoint="/import/835"
                label="Upload 835 ERA File (.835, .edi, .txt)"
                accept={{ "text/plain": [".835", ".edi", ".txt"] }}
              />
            </Col>
            <Col md={4}>
              <Card className="border-0 shadow-sm">
                <Card.Body>
                  <Card.Title>835 Parser Info</Card.Title>
                  <ul className="small">
                    <li>Parses X12 835 format</li>
                    <li>Extracts BPR payment info</li>
                    <li>Extracts TRN check/EFT numbers</li>
                    <li>Parses CLP claims with status</li>
                    <li>Reads CAS adjustment codes</li>
                    <li>Captures SVC CPT codes</li>
                    <li>Links patient names via NM1</li>
                  </ul>
                </Card.Body>
              </Card>
            </Col>
          </Row>
        </Tab>
      </Tabs>
    </>
  );
}

export default Import;
