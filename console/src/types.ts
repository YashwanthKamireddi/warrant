/** Shapes returned by the Warrant engine. These mirror the Python models exactly;
 *  the console never re-derives a verdict, it only renders one. */

export type Verdict = "allow" | "block" | "escalate";
export type CheckStatus = "pass" | "warn" | "fail";

export interface Check {
  rule: string;
  status: CheckStatus;
  detail: string;
  observed: number | string | null;
  limit: number | string | null;
  /** Binding checks can block. Advisory ones can only escalate. */
  binding: boolean;
}

export interface LineItem {
  sku: string;
  name: string;
  category: string;
  qty: number;
  unit_paise: number;
  line_paise: number;
}

export interface Signature {
  key_id: string;
  algorithm: string;
  value: string;
}

export interface Cart {
  id: string;
  digest: string;
  merchant: string;
  total_paise: number;
  signature: Signature | null;
  line_items: LineItem[];
}

export interface RailResult {
  ok: boolean;
  settled: boolean;
  ref: {
    kind: string;
    order_id: string | null;
    payment_id: string | null;
    status: string | null;
  };
  amount_paise: number;
  error_code: string | null;
  error_source: string | null;
  error_step: string | null;
  error_reason: string | null;
  raw: Record<string, unknown>;
}

export interface Outcome {
  cart: Cart;
  verdict: Verdict;
  model_used: boolean;
  reasons: string[];
  checks: Check[];
  receipt: { id: string; digest: string; body: Record<string, unknown> } | null;
  rail: RailResult | null;
  ledger_seqs: number[];
  label: string | null;
  /** Wall time for the whole authorisation, including the rail call. */
  elapsed_us?: number;
  rail_kind?: string;
}

export interface Scope {
  merchants: string[];
  categories: string[];
  max_total_paise: number;
  max_per_txn_paise: number;
  max_txns: number;
  step_up_over_paise: number | null;
  not_before: number;
  expires_at: number;
  spent_paise: number;
  txns_used: number;
  revoked: boolean;
  rail_block_paise: number | null;
  rail_block_used_paise: number;
  rail_kind: string;
}

export interface PendingIntent {
  approval_prompt: string;
  ambiguities: string[];
  source: "live" | "transcript" | "fallback";
  narrowed_by_envelope: boolean;
  proposed_max_total_paise: number;
  scope: Omit<
    Scope,
    "spent_paise" | "txns_used" | "revoked" | "rail_block_paise" | "rail_block_used_paise" | "rail_kind"
  >;
}

export interface StartResponse {
  session_id: string;
  utterance: string;
  rail: "simulated" | "razorpay";
  pending: PendingIntent;
  envelope: Record<string, unknown>;
}

export interface IntentEnvelope {
  id: string;
  digest: string;
  body: Record<string, unknown>;
  signature: Signature | null;
}

export interface LedgerEntry {
  seq: number;
  kind: string;
  recorded_at: number;
  prev_hash: string;
  hash: string;
  payload: Record<string, any>;
}

export interface ChainStatus {
  intact: boolean;
  length: number;
  head: string;
  break: { seq: number; reason: string; expected: string; found: string } | null;
}

export interface Product {
  sku: string;
  name: string;
  category: string;
  unit_paise: number;
  merchant: string;
  note: string;
}

export interface ScriptedStep {
  label: string;
  expect: Verdict;
  teaches: string;
  merchant: string;
  lines: { sku: string; qty: number }[];
  /** 1-based index of an earlier step whose nonce this one re-presents. A
   *  replay must be refused, so demonstrating it needs the same nonce back. */
  replay_of: number | null;
}

export interface RailOption {
  id: "simulated" | "razorpay";
  label: string;
  note: string;
  available: boolean;
}

export interface Meta {
  capability: {
    credentials_configured: boolean;
    transcript_available: boolean;
    transcript_provenance: string;
  };
  capability_note: string;
  rails: RailOption[];
  catalog: Product[];
  default_utterance: string;
  scripted_steps: ScriptedStep[];
}

export interface EvidencePack {
  payment_id: string | null;
  amount_paise: number;
  session_id: string;
  explanation_letter: string;
  customer_communication: string;
  access_activity_log: Record<string, unknown>;
  proof_of_service: string;
  signatures_verified: boolean;
  chain_intact: boolean;
  verification_note: string;
}
