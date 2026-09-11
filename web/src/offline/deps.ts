/** Production wiring of the sync algorithm to the real API client. */

import { fetchDocument, uploadFile } from "../api/applications";
import { request } from "../api/client";
import type { Principal } from "../api/auth";
import type { InspectionDetail } from "../api/inspections";
import { fetchSyncReceipt, postSyncOperation } from "../api/offline";
import type { SyncDeps } from "./sync";

export const liveSyncDeps: SyncDeps = {
  fetchMe: async () => (await request<{ data: Principal }>("/me")).data.data,
  fetchInspection: async (inspectionId) => {
    const response = await request<{ data: InspectionDetail }>(`/inspections/${inspectionId}`);
    return { inspection: response.data.data, etag: response.etag ?? "" };
  },
  uploadBlob: (inspectionId, itemCode, file) => uploadFile("INSPECTION_EVIDENCE", inspectionId, `inspection-${itemCode.toLowerCase()}`, file),
  fetchDocument,
  postOperation: postSyncOperation,
  fetchReceipt: fetchSyncReceipt,
  now: () => new Date(),
};
