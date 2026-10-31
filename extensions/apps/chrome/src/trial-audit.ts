/** Append-only local research journal. No sportsbook credentials or cookies. */
import type { MarketChangeEvent, SignalSnapshot } from "@propstein/core";

export interface TrialAuditRecord {
  at: string;
  kind: string;
  signalKey?: string;
  event?: MarketChangeEvent;
  snapshot?: SignalSnapshot;
  reasonCodes: string[];
  displayed: boolean;
  mode: "synthetic-demo" | "read-only-trial";
}

export function auditRecord(
  kind: string,
  at: string,
  event?: MarketChangeEvent,
  snapshot?: SignalSnapshot,
): TrialAuditRecord {
  const reasonCodes = snapshot?.withdrawalReason
    ? [snapshot.withdrawalReason]
    : snapshot ? [snapshot.state] : [kind];
  return {
    at, kind,
    ...(event?.signalKey || snapshot?.signalKey ? { signalKey: event?.signalKey ?? snapshot?.signalKey } : {}),
    ...(event ? { event } : {}),
    ...(snapshot ? { snapshot } : {}),
    reasonCodes,
    displayed: snapshot !== undefined && !snapshot.withdrawn,
    mode: snapshot?.observed.source === "demobook" || event?.market?.source === "demobook"
      ? "synthetic-demo" : "read-only-trial",
  };
}

const DB_NAME = "propstein-live-sniper-trial";
const STORE = "records";

function openJournal(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { autoIncrement: true });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function journalReady(): Promise<void> {
  const db = await openJournal();
  db.close();
}

export async function appendAudit(record: TrialAuditRecord): Promise<void> {
  const db = await openJournal();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).add(record);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error ?? new Error("audit transaction aborted"));
    });
  } finally {
    db.close();
  }
}

export async function exportAudit(): Promise<TrialAuditRecord[]> {
  const db = await openJournal();
  try {
    return await new Promise((resolve, reject) => {
      const records: TrialAuditRecord[] = [];
      const tx = db.transaction(STORE, "readonly");
      const request = tx.objectStore(STORE).openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (cursor) { records.push(cursor.value as TrialAuditRecord); cursor.continue(); }
      };
      tx.oncomplete = () => resolve(records);
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
