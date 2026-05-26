import { buildCockpitModel, getInitialSelectedId } from "./importCockpit";

test("builds cockpit metrics and queue items from portal, scanner, and preview state", () => {
  const model = buildCockpitModel({
    portalStatus: {
      available: true,
      supported_count: 3,
      staged_count: 3,
      files: [
        { name: "oa-1.835", extension: ".835", supported: true, temporary: false, size: 1000 },
        { name: "ignore.tmp", extension: ".tmp", supported: false, temporary: true, size: 100 },
      ],
    },
    scannerStatus: {
      available: true,
      watcher_active: true,
      unclassified_count: 7,
      ocr_today_count: 43,
    },
    scanPreview: {
      total_files: 8,
      new_count: 2,
      already_processed_count: 6,
      new_files: [
        { path: "portal/2026-05-26/oa-1.835", extension: ".835", size_bytes: 1000 },
        { path: "scan/eob.pdf", extension: ".pdf", size_bytes: 2000 },
      ],
    },
  });

  expect(model.metrics.ready).toBe(5);
  expect(model.metrics.review).toBe(1);
  expect(model.metrics.blocked).toBe(0);
  expect(model.metrics.posted).toBe(6);
  expect(model.metrics.scannerQueue).toBe(7);
  expect(model.items.map((item) => item.id)).toEqual([
    "portal-staged",
    "scanner-queue",
    "scan-preview",
    "portal-file-oa-1.835",
  ]);
  expect(getInitialSelectedId(model.items)).toBe("portal-staged");
});

test("marks unavailable sources as blocked without inventing patient data", () => {
  const model = buildCockpitModel({
    portalStatus: { available: false, error: "missing staging folder", files: [] },
    scannerStatus: { available: false, error: "ssh failed" },
    scanPreview: null,
  });

  expect(model.metrics.blocked).toBe(2);
  expect(model.items).toHaveLength(2);
  expect(model.items.every((item) => item.status === "blocked")).toBe(true);
  expect(model.items.some((item) => item.patient)).toBe(false);
});
