const MAX_PORTAL_FILE_ROWS = 6;

function countSupportedFiles(files = []) {
  return files.filter((file) => file.supported && !file.temporary).length;
}

function supportedPortalFiles(files = []) {
  return files
    .filter((file) => file.supported && !file.temporary)
    .slice(0, MAX_PORTAL_FILE_ROWS);
}

function safeCount(value) {
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function makeBlockedItem(id, source, title, reason) {
  return {
    id,
    source,
    title,
    amount: "Blocked",
    status: "blocked",
    gate: "source",
    stage: "Connect source",
    nextAction: "Fix source",
    reason,
    evidence: [
      { label: "Source status", value: "Unavailable", state: "blocked" },
      { label: "Next check", value: reason || "Connection required", state: "blocked" },
    ],
    events: reason ? [reason] : [],
  };
}

function buildPortalRows(portalStatus) {
  if (!portalStatus) return [];
  if (!portalStatus.available) {
    return [
      makeBlockedItem(
        "portal-blocked",
        "Portal",
        "Portal download staging",
        portalStatus.error || "Portal staging is unavailable"
      ),
    ];
  }

  const files = supportedPortalFiles(portalStatus.files);
  const stagedCount = safeCount(portalStatus.staged_count || portalStatus.supported_count || files.length);
  const rows = [];

  if (stagedCount > 0) {
    rows.push({
      id: "portal-staged",
      source: "Portal",
      title: `${stagedCount} staged portal download${stagedCount === 1 ? "" : "s"}`,
      amount: "Pending",
      status: "ready",
      gate: "staged",
      stage: "Payment source intake",
      nextAction: "Preview promote",
      reason: "Portal files are ready to move into the active EOB import lane.",
      evidence: [
        { label: "Staged files", value: stagedCount, state: "ready" },
        { label: "Supported files", value: safeCount(portalStatus.supported_count || files.length), state: "ready" },
        { label: "Duplicate check", value: "SHA on promote", state: "review" },
      ],
      events: ["Portal staging checked", "Ready for dry-run promote"],
    });
  }

  files.forEach((file) => {
    rows.push({
      id: `portal-file-${file.name}`,
      source: "Portal",
      title: file.name,
      amount: file.extension || "file",
      status: "ready",
      gate: "file",
      stage: "Downloaded remit",
      nextAction: "Promote",
      reason: "Downloaded source file is supported and not temporary.",
      evidence: [
        { label: "Type", value: file.extension || "unknown", state: "ready" },
        { label: "Size", value: file.size || 0, state: "ready" },
      ],
      events: ["Supported portal file detected"],
    });
  });

  return rows;
}

function buildScannerRows(scannerStatus) {
  if (!scannerStatus) return [];
  if (!scannerStatus.available) {
    return [
      makeBlockedItem(
        "scanner-blocked",
        "ScanSnap",
        "ScanSnap queue",
        scannerStatus.error || "Scanner status is unavailable"
      ),
    ];
  }

  const queued = safeCount(scannerStatus.unclassified_count);
  if (queued === 0) return [];

  return [
    {
      id: "scanner-queue",
      source: "ScanSnap",
      title: `${queued} scanned file${queued === 1 ? "" : "s"} awaiting OCR classification`,
      amount: "Pending",
      status: scannerStatus.watcher_active ? "review" : "blocked",
      gate: scannerStatus.watcher_active ? "ocr" : "watcher",
      stage: "Patient/payment document intake",
      nextAction: scannerStatus.watcher_active ? "Review OCR" : "Start watcher",
      reason: scannerStatus.watcher_active
        ? "OCR work exists, but human review is needed before treating it as reliable source data."
        : "ScanSnap watcher is not active.",
      evidence: [
        { label: "Watcher", value: scannerStatus.watcher_active ? "online" : "offline", state: scannerStatus.watcher_active ? "ready" : "blocked" },
        { label: "Queued", value: queued, state: "review" },
        { label: "OCR today", value: safeCount(scannerStatus.ocr_today_count), state: "ready" },
      ],
      events: ["ScanSnap status checked"],
    },
  ];
}

function buildScanPreviewRows(scanPreview) {
  if (!scanPreview) return [];
  const newCount = safeCount(scanPreview.new_count);
  if (newCount === 0) {
    return [
      {
        id: "scan-preview-clear",
        source: "Archive",
        title: "EOB archive scan is clear",
        amount: "0 new",
        status: "posted",
        gate: "dedupe",
        stage: "Import lane",
        nextAction: "No action",
        reason: "All scanned files are already processed.",
        evidence: [
          { label: "Total files", value: safeCount(scanPreview.total_files), state: "posted" },
          { label: "Already processed", value: safeCount(scanPreview.already_processed_count), state: "posted" },
        ],
        events: ["Archive preview completed"],
      },
    ];
  }

  return [
    {
      id: "scan-preview",
      source: "Archive",
      title: `${newCount} new EOB file${newCount === 1 ? "" : "s"} in import folder`,
      amount: "Pending",
      status: "ready",
      gate: "dedupe",
      stage: "Active EOB import lane",
      nextAction: "Scan import",
      reason: "Preview found new files that can be imported into the matching pipeline.",
      evidence: [
        { label: "New files", value: newCount, state: "ready" },
        { label: "Already processed", value: safeCount(scanPreview.already_processed_count), state: "posted" },
        { label: "Total files", value: safeCount(scanPreview.total_files), state: "ready" },
      ],
      events: (scanPreview.new_files || []).slice(0, 3).map((file) => `New: ${file.path}`),
    },
  ];
}

function metricStatusCounts(items) {
  return items.reduce(
    (metrics, item) => {
      if (item.status === "ready") metrics.ready += item.id.startsWith("portal-file-") ? 0 : 1;
      if (item.status === "review") metrics.review += 1;
      if (item.status === "blocked") metrics.blocked += 1;
      if (item.status === "posted") metrics.posted += 1;
      return metrics;
    },
    { ready: 0, review: 0, blocked: 0, posted: 0, scannerQueue: 0 }
  );
}

export function buildCockpitModel({ portalStatus, scannerStatus, scanPreview, scanResult } = {}) {
  const portalRows = buildPortalRows(portalStatus);
  const portalSummaryRows = portalRows.filter((item) => !item.id.startsWith("portal-file-"));
  const portalFileRows = portalRows.filter((item) => item.id.startsWith("portal-file-"));
  const items = [
    ...portalSummaryRows,
    ...buildScannerRows(scannerStatus),
    ...buildScanPreviewRows(scanPreview),
    ...portalFileRows,
  ];

  const metrics = metricStatusCounts(items);
  metrics.ready =
    (portalStatus?.available ? safeCount(portalStatus.staged_count || portalStatus.supported_count || countSupportedFiles(portalStatus.files)) : 0) +
    safeCount(scanPreview?.new_count);
  metrics.posted = safeCount(scanPreview?.already_processed_count) + safeCount(scanResult?.already_processed);
  metrics.scannerQueue = safeCount(scannerStatus?.unclassified_count);

  return {
    metrics,
    items,
    selectedId: getInitialSelectedId(items),
  };
}

export function getInitialSelectedId(items = []) {
  const actionable = items.find((item) => item.status === "ready" || item.status === "review");
  return actionable?.id || items[0]?.id || null;
}
