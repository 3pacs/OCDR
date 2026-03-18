import React, { useState, useEffect, useCallback } from "react";
import {
  Card, Row, Col, Badge, Alert, Spinner, Button, Form,
  ProgressBar, Modal, Table, OverlayTrigger, Tooltip,
} from "react-bootstrap";
import api from "../services/api";

const FREQ_LABELS = {
  DAILY: { label: "Daily", color: "primary" },
  WEEKLY: { label: "Weekly", color: "info" },
  BIWEEKLY: { label: "Bi-Weekly", color: "warning" },
  MONTHLY: { label: "Monthly", color: "secondary" },
  ONE_TIME: { label: "One-Time", color: "dark" },
};

const CAT_ICONS = {
  DATA_IMPORT: "📥",
  POSTING: "📝",
  RECONCILIATION: "🔄",
  DENIALS: "⚠️",
  BANKING: "🏦",
  ANALYTICS: "📊",
  PAYROLL: "💰",
  BILLS: "📄",
  RESEARCH_BILLING: "🔬",
};

const PRIORITY_LABELS = {
  1: { label: "Urgent", color: "danger" },
  2: { label: "High", color: "warning" },
  3: { label: "Normal", color: "info" },
  4: { label: "Low", color: "secondary" },
  5: { label: "Optional", color: "light" },
};

function BusinessTasks() {
  const [todayData, setTodayData] = useState(null);
  const [templates, setTemplates] = useState(null);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [view, setView] = useState("today"); // today, templates, history
  const [showAddModal, setShowAddModal] = useState(false);

  const fetchToday = useCallback(async () => {
    try {
      const res = await api.get("/tasks/today");
      setTodayData(res.data);
    } catch (err) {
      setError("Failed to load today's tasks.");
    }
  }, []);

  const fetchTemplates = useCallback(async () => {
    try {
      const res = await api.get("/tasks/templates");
      setTemplates(res.data);
    } catch (err) {
      setError("Failed to load task templates.");
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await api.get("/tasks/history?days=14");
      setHistory(res.data);
    } catch (err) {
      setError("Failed to load task history.");
    }
  }, []);

  useEffect(() => {
    async function init() {
      setLoading(true);
      await Promise.all([fetchToday(), fetchTemplates()]);
      setLoading(false);
    }
    init();
  }, [fetchToday, fetchTemplates]);

  const toggleTask = async (instanceId, currentStatus) => {
    const newStatus = currentStatus === "COMPLETED" ? "PENDING" : "COMPLETED";
    try {
      await api.patch(`/tasks/instances/${instanceId}`, { status: newStatus });
      await fetchToday();
    } catch (err) {
      setError("Failed to update task.");
    }
  };

  const skipTask = async (instanceId) => {
    try {
      await api.patch(`/tasks/instances/${instanceId}`, { status: "SKIPPED" });
      await fetchToday();
    } catch (err) {
      setError("Failed to skip task.");
    }
  };

  const toggleTemplate = async (taskId, isActive) => {
    try {
      await api.patch(`/tasks/templates/${taskId}`, { is_active: !isActive });
      await fetchTemplates();
    } catch (err) {
      setError("Failed to update template.");
    }
  };

  if (loading) {
    return (
      <div className="text-center mt-5">
        <Spinner animation="border" />
        <div className="mt-2">Loading tasks...</div>
      </div>
    );
  }

  const summary = todayData?.summary || {};
  const pct = summary.total > 0
    ? Math.round(((summary.completed + summary.skipped) / summary.total) * 100)
    : 0;

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-4">
        <div>
          <h2 className="mb-1">Business Tasks</h2>
          <small className="text-muted">
            Daily checklist and recurring task management for practice operations.
          </small>
        </div>
        <div className="d-flex gap-2">
          <Button
            variant={view === "today" ? "primary" : "outline-secondary"}
            size="sm"
            onClick={() => setView("today")}
          >
            Today
          </Button>
          <Button
            variant={view === "templates" ? "primary" : "outline-secondary"}
            size="sm"
            onClick={() => { setView("templates"); fetchTemplates(); }}
          >
            Templates
          </Button>
          <Button
            variant={view === "history" ? "primary" : "outline-secondary"}
            size="sm"
            onClick={() => { setView("history"); fetchHistory(); }}
          >
            History
          </Button>
        </div>
      </div>

      {error && <Alert variant="warning" dismissible onClose={() => setError(null)}>{error}</Alert>}

      {/* Summary cards */}
      <Row className="g-3 mb-4">
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body className="text-center">
              <div className="text-muted small text-uppercase">Progress</div>
              <div className="fs-2 fw-bold">{pct}%</div>
              <ProgressBar
                now={pct}
                variant={pct === 100 ? "success" : pct > 50 ? "primary" : "warning"}
                className="mt-2"
              />
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body className="text-center">
              <div className="text-muted small text-uppercase">Pending</div>
              <div className="fs-2 fw-bold text-warning">{summary.pending || 0}</div>
              <small className="text-muted">tasks remaining</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body className="text-center">
              <div className="text-muted small text-uppercase">Completed</div>
              <div className="fs-2 fw-bold text-success">{summary.completed || 0}</div>
              <small className="text-muted">of {summary.total || 0} today</small>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="border-0 shadow-sm h-100">
            <Card.Body className="text-center">
              <div className="text-muted small text-uppercase">Time Left</div>
              <div className="fs-2 fw-bold">{summary.estimated_minutes_remaining || 0}m</div>
              <small className="text-muted">estimated remaining</small>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {/* TODAY VIEW */}
      {view === "today" && (
        <TodayView
          tasks={todayData?.tasks || []}
          onToggle={toggleTask}
          onSkip={skipTask}
        />
      )}

      {/* TEMPLATES VIEW */}
      {view === "templates" && (
        <TemplatesView
          templates={templates || []}
          onToggle={toggleTemplate}
          onAdd={() => setShowAddModal(true)}
        />
      )}

      {/* HISTORY VIEW */}
      {view === "history" && (
        <HistoryView history={history} />
      )}

      <AddTaskModal
        show={showAddModal}
        onHide={() => setShowAddModal(false)}
        onCreated={() => { fetchTemplates(); setShowAddModal(false); }}
      />
    </>
  );
}

function TodayView({ tasks, onToggle, onSkip }) {
  // Group by category
  const grouped = {};
  for (const t of tasks) {
    if (!grouped[t.category]) grouped[t.category] = [];
    grouped[t.category].push(t);
  }

  if (tasks.length === 0) {
    return (
      <Alert variant="info">
        No tasks scheduled for today. Check the Templates tab to configure recurring tasks.
      </Alert>
    );
  }

  return (
    <>
      {Object.entries(grouped).map(([cat, catTasks]) => (
        <Card key={cat} className="border-0 shadow-sm mb-3">
          <Card.Body>
            <Card.Title className="small text-uppercase text-muted mb-3">
              {CAT_ICONS[cat] || "📋"} {cat.replace(/_/g, " ")}
            </Card.Title>
            {catTasks.map((t) => (
              <div
                key={t.instance_id}
                className={`d-flex align-items-center p-2 mb-2 rounded ${
                  t.status === "COMPLETED"
                    ? "bg-light text-decoration-line-through text-muted"
                    : t.status === "SKIPPED"
                      ? "bg-light text-muted"
                      : ""
                }`}
              >
                <Form.Check
                  type="checkbox"
                  checked={t.status === "COMPLETED"}
                  onChange={() => onToggle(t.instance_id, t.status)}
                  className="me-3"
                />
                <div className="flex-grow-1">
                  <div className="fw-bold">{t.title}</div>
                  {t.description && (
                    <small className="text-muted">{t.description}</small>
                  )}
                </div>
                <div className="d-flex align-items-center gap-2">
                  {t.estimated_minutes && (
                    <Badge bg="light" text="dark" className="border">
                      {t.estimated_minutes}m
                    </Badge>
                  )}
                  <Badge bg={FREQ_LABELS[t.frequency]?.color || "secondary"}>
                    {FREQ_LABELS[t.frequency]?.label || t.frequency}
                  </Badge>
                  <Badge bg={PRIORITY_LABELS[t.priority]?.color || "info"}>
                    P{t.priority}
                  </Badge>
                  {t.status === "PENDING" && (
                    <OverlayTrigger overlay={<Tooltip>Skip for today</Tooltip>}>
                      <Button
                        variant="outline-secondary"
                        size="sm"
                        className="py-0 px-1"
                        onClick={() => onSkip(t.instance_id)}
                      >
                        skip
                      </Button>
                    </OverlayTrigger>
                  )}
                  {t.completed_at && (
                    <small className="text-success">
                      {new Date(t.completed_at).toLocaleTimeString()}
                    </small>
                  )}
                </div>
              </div>
            ))}
          </Card.Body>
        </Card>
      ))}
    </>
  );
}

function TemplatesView({ templates, onToggle, onAdd }) {
  const byFreq = {};
  for (const t of templates) {
    if (!byFreq[t.frequency]) byFreq[t.frequency] = [];
    byFreq[t.frequency].push(t);
  }

  const freqOrder = ["DAILY", "WEEKLY", "BIWEEKLY", "MONTHLY", "ONE_TIME"];

  return (
    <>
      <div className="d-flex justify-content-end mb-3">
        <Button variant="outline-primary" size="sm" onClick={onAdd}>
          + Add Task
        </Button>
      </div>

      {freqOrder.map((freq) => {
        const items = byFreq[freq];
        if (!items || items.length === 0) return null;
        return (
          <Card key={freq} className="border-0 shadow-sm mb-3">
            <Card.Body>
              <Card.Title className="mb-3">
                <Badge bg={FREQ_LABELS[freq]?.color || "secondary"} className="me-2">
                  {FREQ_LABELS[freq]?.label || freq}
                </Badge>
                <small className="text-muted">({items.length} tasks)</small>
              </Card.Title>
              <Table size="sm" className="mb-0">
                <thead>
                  <tr>
                    <th>Active</th>
                    <th>Title</th>
                    <th>Category</th>
                    <th>Priority</th>
                    <th>Est. Time</th>
                    <th>Schedule</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((t) => (
                    <tr key={t.id} className={!t.is_active ? "text-muted" : ""}>
                      <td>
                        <Form.Check
                          type="switch"
                          checked={t.is_active}
                          onChange={() => onToggle(t.id, t.is_active)}
                        />
                      </td>
                      <td>
                        <div className="fw-bold">{t.title}</div>
                        {t.description && (
                          <small className="text-muted">{t.description}</small>
                        )}
                      </td>
                      <td>
                        <Badge bg="light" text="dark" className="border">
                          {CAT_ICONS[t.category] || "📋"} {t.category.replace(/_/g, " ")}
                        </Badge>
                      </td>
                      <td>
                        <Badge bg={PRIORITY_LABELS[t.priority]?.color || "info"}>
                          {PRIORITY_LABELS[t.priority]?.label || `P${t.priority}`}
                        </Badge>
                      </td>
                      <td>{t.estimated_minutes ? `${t.estimated_minutes}m` : "—"}</td>
                      <td>
                        {t.frequency === "WEEKLY" && t.schedule_day != null
                          ? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][t.schedule_day]
                          : t.frequency === "MONTHLY" && t.schedule_day
                            ? `Day ${t.schedule_day}`
                            : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card.Body>
          </Card>
        );
      })}
    </>
  );
}

function HistoryView({ history }) {
  if (!history) {
    return (
      <div className="text-center mt-4">
        <Spinner animation="border" size="sm" />
        <span className="ms-2">Loading history...</span>
      </div>
    );
  }

  const days = history.days || [];
  if (days.length === 0) {
    return <Alert variant="info">No task history yet.</Alert>;
  }

  return (
    <>
      {days.map((day) => (
        <Card key={day.date} className="border-0 shadow-sm mb-3">
          <Card.Body>
            <div className="d-flex justify-content-between align-items-center mb-2">
              <Card.Title className="mb-0">{day.date}</Card.Title>
              <Badge bg={day.completed === day.total ? "success" : "warning"}>
                {day.completed}/{day.total} completed
              </Badge>
            </div>
            <ProgressBar
              now={day.total > 0 ? (day.completed / day.total) * 100 : 0}
              variant={day.completed === day.total ? "success" : "primary"}
              className="mb-2"
              style={{ height: 6 }}
            />
            <div className="d-flex flex-wrap gap-2">
              {day.tasks.map((t) => (
                <Badge
                  key={t.instance_id}
                  bg={t.status === "COMPLETED" ? "success" : t.status === "SKIPPED" ? "secondary" : "warning"}
                  className="fw-normal"
                >
                  {t.status === "COMPLETED" ? "✓" : t.status === "SKIPPED" ? "—" : "○"} {t.title}
                </Badge>
              ))}
            </div>
          </Card.Body>
        </Card>
      ))}
    </>
  );
}

function AddTaskModal({ show, onHide, onCreated }) {
  const [form, setForm] = useState({
    title: "",
    description: "",
    category: "DATA_IMPORT",
    frequency: "DAILY",
    schedule_day: "",
    priority: 3,
    estimated_minutes: "",
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        ...form,
        schedule_day: form.schedule_day ? parseInt(form.schedule_day) : null,
        estimated_minutes: form.estimated_minutes ? parseInt(form.estimated_minutes) : null,
      };
      await api.post("/tasks/templates", payload);
      onCreated();
      setForm({
        title: "", description: "", category: "DATA_IMPORT",
        frequency: "DAILY", schedule_day: "", priority: 3, estimated_minutes: "",
      });
    } catch (err) {
      alert("Failed to create task: " + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal show={show} onHide={onHide}>
      <Modal.Header closeButton>
        <Modal.Title>Add Recurring Task</Modal.Title>
      </Modal.Header>
      <Form onSubmit={handleSubmit}>
        <Modal.Body>
          <Form.Group className="mb-3">
            <Form.Label>Title</Form.Label>
            <Form.Control
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </Form.Group>
          <Form.Group className="mb-3">
            <Form.Label>Description</Form.Label>
            <Form.Control
              as="textarea"
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Form.Group>
          <Row>
            <Col>
              <Form.Group className="mb-3">
                <Form.Label>Category</Form.Label>
                <Form.Select
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                >
                  {Object.keys(CAT_ICONS).map((c) => (
                    <option key={c} value={c}>{CAT_ICONS[c]} {c.replace(/_/g, " ")}</option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>
            <Col>
              <Form.Group className="mb-3">
                <Form.Label>Frequency</Form.Label>
                <Form.Select
                  value={form.frequency}
                  onChange={(e) => setForm({ ...form, frequency: e.target.value })}
                >
                  {Object.entries(FREQ_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>{v.label}</option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>
          </Row>
          <Row>
            <Col>
              <Form.Group className="mb-3">
                <Form.Label>Priority (1=Urgent, 5=Optional)</Form.Label>
                <Form.Select
                  value={form.priority}
                  onChange={(e) => setForm({ ...form, priority: parseInt(e.target.value) })}
                >
                  {[1, 2, 3, 4, 5].map((p) => (
                    <option key={p} value={p}>{p} — {PRIORITY_LABELS[p].label}</option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>
            <Col>
              <Form.Group className="mb-3">
                <Form.Label>Est. Minutes</Form.Label>
                <Form.Control
                  type="number"
                  value={form.estimated_minutes}
                  onChange={(e) => setForm({ ...form, estimated_minutes: e.target.value })}
                />
              </Form.Group>
            </Col>
            <Col>
              <Form.Group className="mb-3">
                <Form.Label>Schedule Day</Form.Label>
                <Form.Control
                  type="number"
                  placeholder="0-6 or 1-28"
                  value={form.schedule_day}
                  onChange={(e) => setForm({ ...form, schedule_day: e.target.value })}
                />
                <Form.Text>Weekly: 0=Mon..6=Sun. Monthly: day of month.</Form.Text>
              </Form.Group>
            </Col>
          </Row>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={onHide}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={saving}>
            {saving ? <Spinner size="sm" /> : "Create Task"}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
}

export default BusinessTasks;
