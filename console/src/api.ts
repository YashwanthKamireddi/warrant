import type {
  ChainStatus,
  EvidencePack,
  IntentEnvelope,
  LedgerEntry,
  Meta,
  Outcome,
  Scope,
  StartResponse,
} from "./types";

const BASE = "/api";

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { "content-type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError("Cannot reach the Warrant engine. Is `warrant serve` running?", 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail ?? `Request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  meta: () => request<Meta>("/meta"),

  start: (utterance: string) =>
    request<StartResponse>("/sessions", {
      method: "POST",
      body: JSON.stringify({ utterance }),
    }),

  approve: (sessionId: string) =>
    request<{
      approved: boolean;
      intent: IntentEnvelope;
      scope: Scope;
      subject_public_key: string;
      ledger: LedgerEntry[];
    }>(`/sessions/${sessionId}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved: true }),
    }),

  submitCart: (
    sessionId: string,
    merchant: string,
    lines: { sku: string; qty: number }[],
    cosign: boolean,
    replayOf: number | null = null,
  ) =>
    request<{ outcome: Outcome; scope: Scope; ledger: LedgerEntry[] }>(
      `/sessions/${sessionId}/carts`,
      {
        method: "POST",
        body: JSON.stringify({ merchant, lines, cosign, replay_of: replayOf }),
      },
    ),

  revoke: (sessionId: string) =>
    request<{ scope: Scope; ledger: LedgerEntry[] }>(`/sessions/${sessionId}/revoke`, {
      method: "POST",
    }),

  chain: (sessionId: string) => request<ChainStatus>(`/sessions/${sessionId}/chain`),

  tamper: (sessionId: string) =>
    request<{ tampered_seq: number; what: string; chain: ChainStatus }>(
      `/sessions/${sessionId}/tamper`,
      { method: "POST" },
    ),

  evidence: (sessionId: string) => request<EvidencePack>(`/sessions/${sessionId}/evidence`),
};

export { ApiError };
