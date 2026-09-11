import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it } from "vitest";

import { ApiError, NetworkError } from "../api/errors";
import type { OfflinePackage, SyncReceipt } from "../api/offline";
import { AgniOfflineDatabase, offlineDb, useOfflineDatabase } from "./database";
import { addLocalEvidence, listOperations, queueFailedVisitOperation, queueReportOperation, savePackage } from "./queue";
import { syncAll, type SyncDeps } from "./sync";

const PRINCIPAL = { id: "o1", display_name: "Priya Nair", kind: "STAFF" as const, workspaces: ["officer" as const], active_workspace: "officer" as const, scopes: [], capabilities: [], authz_epoch: 1, session_expires_at: null, feature_gates: { service_mode: "DEMO" as const, demo_controls: true, staff_oidc: true } };

const INSPECTION = {
  inspection_id: "66666666-6666-4666-8666-666666666666",
  application_id: "a1",
  public_reference: "AS-2026-1001",
  application_status: "INSPECTION_PENDING",
  application_version: 5,
  attempt_number: 1,
  purpose: "INITIAL",
  parent_inspection_id: null,
  status: "IN_PROGRESS" as const,
  checklist_ref: "demo-checklist-v1#2",
  premises: { display_name: "Mehta Family Restaurant", locality: "Karol Bagh", category_key: "Restaurant", ward_key: "W-01" },
  owner_queue: "central-scrutiny",
  scheduled_start: null,
  scheduled_end: null,
  appointment_timezone: "Asia/Kolkata",
  started_at: null,
  finished_at: null,
  check_in: null,
  failed_reason_code: null,
  failed_notes: null,
  cancel_reason: null,
  current_assignment: { assignment_id: "as1", number: 1, state: "ACTIVE" as const, officer_id: "o1", officer_name: "Priya Nair", reason: "x", booking_start: null, booking_end: null, version: 2 },
  version: 3,
  updated_at: "2026-09-14T04:32:00Z",
};

function pkg(expiresAt = "2099-01-01T00:00:00Z"): OfflinePackage {
  return {
    package_id: "p1",
    issued_at: "2026-09-14T04:00:00Z",
    expires_at: expiresAt,
    schema_version: "1.0",
    supported_schema_versions: ["1.0"],
    principal_id: "o1",
    authz_epoch: 1,
    inspection: INSPECTION,
    checklist_items: [{ code: "C01", title: "Means of escape", mandatory: true, evidence_required: true, na_permitted: false }],
    versions: { application_version: 5, inspection_version: 3, assignment_version: 2, checklist_version: "demo-checklist-v1#2" },
    case: { application_id: "a1", public_reference: "AS-2026-1001", status: "INSPECTION_PENDING", premises_display_name: "Mehta Family Restaurant", locality: "Karol Bagh", category_key: "Restaurant", owner_queue: "central-scrutiny" },
    failed_visit_reasons: ["SITE_INACCESSIBLE"],
    operations: ["SUBMIT_INSPECTION_REPORT", "RECORD_FAILED_VISIT"],
    limits: { max_file_bytes: 10485760, allowed_media_types: ["application/pdf"] },
    notice: "snapshot",
  };
}

function receipt(operationId: string): SyncReceipt {
  return { operation_id: operationId, operation_type: "SUBMIT_INSPECTION_REPORT", state: "ACCEPTED", accepted_entity_kind: "REPORT", accepted_entity_id: "r1", accepted_at: "2026-09-14T06:20:00Z", returned_application_version: 6, returned_inspection_version: 4, command_id: "c1", sha256: "x", replayed: false };
}

function deps(overrides: Partial<SyncDeps> = {}): SyncDeps & { posted: unknown[] } {
  const posted: unknown[] = [];
  return {
    posted,
    fetchMe: () => Promise.resolve(PRINCIPAL),
    fetchInspection: () => Promise.resolve({ inspection: INSPECTION, etag: '"inspection:x:v3"' }),
    uploadBlob: (_inspectionId, _code, file) => Promise.resolve({ document_version_id: `doc-${file.name}`, application_id: "a1", requirement_code: "inspection-c01", original_name: file.name, media_type: file.type, size_bytes: file.size, sha256: "h", scan_state: "CLEAN" as const, scan_detail: "", scanned_at: null, uploaded_at: "2026-09-14T06:00:00Z", version: 1 }),
    fetchDocument: (id) => Promise.resolve({ document_version_id: id, application_id: "a1", requirement_code: "inspection-c01", original_name: "f", media_type: "application/pdf", size_bytes: 1, sha256: "h", scan_state: "CLEAN" as const, scan_detail: "", scanned_at: null, uploaded_at: "", version: 1 }),
    postOperation: (manifest) => {
      posted.push(manifest);
      return Promise.resolve({ receipt: receipt(manifest.operation_id), etag: '"inspection:x:v4"' });
    },
    fetchReceipt: () => Promise.reject(new ApiError(404, { code: "RESOURCE_NOT_FOUND" })),
    now: () => new Date("2026-09-14T06:15:00Z"),
    ...overrides,
  };
}

let counter = 0;

beforeEach(() => {
  counter += 1;
  useOfflineDatabase(new AgniOfflineDatabase(`agni-test-${counter}`));
});

describe("offline sync engine (FR-12)", () => {
  it("uploads local evidence, freezes one manifest and stores the receipt before marking accepted", async () => {
    const stored = await savePackage(pkg(), '"inspection:x:v3"', "o1");
    const blob = await addLocalEvidence({ inspection_id: INSPECTION.inspection_id, item_code: "C01", principal_id: "o1", file: new Blob(["%PDF-1.7 photo"], { type: "application/pdf" }), name: "photo.pdf", media_type: "application/pdf" });
    const op = await queueReportOperation({
      principal_id: "o1",
      package: stored,
      observations: [{ item_code: "C01", result: "PASS", note: "", blob_ids: [blob.blob_id], document_version_ids: [] }],
      summary: "Captured offline on site.",
      captured_at: "2026-09-14T05:00:00Z",
    });
    expect(op.state).toBe("WAITING_FOR_UPLOAD");
    const d = deps();
    const report = await syncAll("o1", d);
    expect(report.session).toBe("ONLINE");
    expect(report.outcomes).toEqual([expect.objectContaining({ operation_id: op.operation_id, outcome: "ACCEPTED" })]);
    const manifest = d.posted[0] as { operation_id: string; observations: { document_version_ids: string[] }[]; base_inspection_version: number; assignment_version: number };
    expect(manifest.operation_id).toBe(op.operation_id);
    expect(manifest.observations[0].document_version_ids).toEqual(["doc-photo.pdf"]);
    expect(manifest.base_inspection_version).toBe(3);
    const [after] = await listOperations("o1");
    expect(after.state).toBe("ACCEPTED");
    expect(after.manifest_sha256).toBeTruthy();
    expect(await offlineDb().receipts.get(op.operation_id)).toMatchObject({ receipt: { accepted_entity_id: "r1" } });
    // A second sync sends nothing: the identity is already accepted.
    const again = await syncAll("o1", d);
    expect(again.outcomes).toEqual([]);
    expect(d.posted).toHaveLength(1);
  });

  it("replays the same frozen manifest after a lost response and never mints a second id", async () => {
    const stored = await savePackage(pkg(), '"inspection:x:v3"', "o1");
    const op = await queueFailedVisitOperation({ principal_id: "o1", package: stored, reason_code: "SITE_INACCESSIBLE", reason: "Premises locked; caretaker absent", captured_at: "2026-09-14T04:45:00Z" });
    let calls = 0;
    const d = deps({
      postOperation: (manifest) => {
        calls += 1;
        if (calls === 1) return Promise.reject(new NetworkError(new Error("timeout")));
        return Promise.resolve({ receipt: { ...receipt(manifest.operation_id), operation_type: "RECORD_FAILED_VISIT", accepted_entity_kind: "VISIT_OUTCOME", accepted_entity_id: INSPECTION.inspection_id, replayed: true }, etag: "" });
      },
    });
    const first = await syncAll("o1", d);
    expect(first.outcomes[0]).toMatchObject({ outcome: "RETRY_LATER" });
    let [pending] = await listOperations("o1");
    expect(pending.state).toBe("READY_TO_SUBMIT");
    expect(pending.attempts).toBe(1);
    expect(pending.manifest?.operation_id).toBe(op.operation_id);
    const second = await syncAll("o1", d);
    expect(second.outcomes[0]).toMatchObject({ outcome: "ACCEPTED" });
    [pending] = await listOperations("o1");
    expect(pending.state).toBe("ACCEPTED");
    expect(calls).toBe(2);
  });

  it("locks the local submission when the assignment changed or the package expired, without posting", async () => {
    const stored = await savePackage(pkg(), '"inspection:x:v3"', "o1");
    await queueFailedVisitOperation({ principal_id: "o1", package: stored, reason_code: "SITE_INACCESSIBLE", reason: "Premises locked; caretaker absent", captured_at: "2026-09-14T04:45:00Z" });
    const d = deps({ fetchInspection: () => Promise.resolve({ inspection: { ...INSPECTION, current_assignment: { ...INSPECTION.current_assignment, version: 3, officer_id: "o2", officer_name: "Suresh" } }, etag: "" }) });
    const report = await syncAll("o1", d);
    expect(report.outcomes[0]).toMatchObject({ outcome: "CONFLICT", code: "ASSIGNMENT_CHANGED" });
    expect(d.posted).toHaveLength(0);
    const [op] = await listOperations("o1");
    expect(op.state).toBe("CONFLICT");
    expect(await offlineDb().conflicts.get(op.operation_id)).toMatchObject({ problem: { code: "ASSIGNMENT_CHANGED" }, resolution: null });
    // Expired package: same lock, local work kept.
    useOfflineDatabase(new AgniOfflineDatabase(`agni-test-expired-${counter}`));
    const expired = await savePackage(pkg("2026-09-14T05:00:00Z"), '"inspection:x:v3"', "o1");
    await queueFailedVisitOperation({ principal_id: "o1", package: expired, reason_code: "SITE_INACCESSIBLE", reason: "Premises locked; caretaker absent", captured_at: "2026-09-14T04:45:00Z" });
    const d2 = deps();
    const report2 = await syncAll("o1", d2);
    expect(report2.outcomes[0]).toMatchObject({ outcome: "CONFLICT", code: "OFFLINE_PACKAGE_EXPIRED" });
    expect(d2.posted).toHaveLength(0);
    expect((await listOperations("o1"))[0].manifest).not.toBeNull();
  });

  it("sends nothing without a live session for the same principal", async () => {
    const stored = await savePackage(pkg(), '"inspection:x:v3"', "o1");
    await queueFailedVisitOperation({ principal_id: "o1", package: stored, reason_code: "SITE_INACCESSIBLE", reason: "Premises locked; caretaker absent", captured_at: "2026-09-14T04:45:00Z" });
    const signIn = deps({ fetchMe: () => Promise.reject(new ApiError(401, { code: "AUTHENTICATION_REQUIRED" })) });
    expect((await syncAll("o1", signIn)).session).toBe("SIGN_IN_NEEDED");
    const other = deps({ fetchMe: () => Promise.resolve({ ...PRINCIPAL, id: "o2" }) });
    expect((await syncAll("o1", other)).session).toBe("WRONG_PRINCIPAL");
    const offline = deps({ fetchMe: () => Promise.reject(new NetworkError(new Error("down"))) });
    expect((await syncAll("o1", offline)).session).toBe("OFFLINE");
    expect(signIn.posted.length + other.posted.length + offline.posted.length).toBe(0);
  });

  it("records a structured server conflict and stops retrying that operation", async () => {
    const stored = await savePackage(pkg(), '"inspection:x:v3"', "o1");
    await queueFailedVisitOperation({ principal_id: "o1", package: stored, reason_code: "SITE_INACCESSIBLE", reason: "Premises locked; caretaker absent", captured_at: "2026-09-14T04:45:00Z" });
    const d = deps({ postOperation: () => Promise.reject(new ApiError(409, { code: "INVALID_TRANSITION", detail: "This attempt already has an accepted report", server: { has_accepted_report: true } } as never)) });
    const report = await syncAll("o1", d);
    expect(report.outcomes[0]).toMatchObject({ outcome: "CONFLICT", code: "INVALID_TRANSITION" });
    const again = await syncAll("o1", d);
    expect(again.outcomes).toEqual([]);
    const [op] = await listOperations("o1");
    expect(op.state).toBe("CONFLICT");
    expect(op.manifest).not.toBeNull(); // local data retained
  });
});
