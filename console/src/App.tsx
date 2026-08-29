import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import { relativeWindow, rupees } from "./format";
import { DecisionCard } from "./components/DecisionCard";
import { EvidenceView } from "./components/EvidenceView";
import { LedgerView } from "./components/LedgerView";
import { PermissionCard } from "./components/PermissionCard";
import { Storefront } from "./components/Storefront";
import { Empty, Hash, Meter } from "./components/primitives";
import type {
  ChainStatus,
  EvidencePack,
  LedgerEntry,
  Meta,
  Outcome,
  PendingIntent,
  Scope,
  Signature,
} from "./types";

type Tab = "trace" | "ledger" | "evidence";

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [utterance, setUtterance] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingIntent | null>(null);
  const [signature, setSignature] = useState<Signature | null>(null);
  const [justSigned, setJustSigned] = useState(false);
  const [scope, setScope] = useState<Scope | null>(null);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [chain, setChain] = useState<ChainStatus | null>(null);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [merchant, setMerchant] = useState("zomato");
  const [cosign, setCosign] = useState(false);
  const [tab, setTab] = useState<Tab>("trace");
  const [evidence, setEvidence] = useState<EvidencePack | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m);
        setUtterance(m.default_utterance);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const derive = () =>
    run(async () => {
      const started = await api.start(utterance);
      setSessionId(started.session_id);
      setPending(started.pending);
      setSignature(null);
      setScope(null);
      setOutcomes([]);
      setLedger([]);
      setChain(null);
      setEvidence(null);
      setEvidenceError(null);
      setQuantities({});
    });

  const approve = () =>
    run(async () => {
      if (!sessionId) return;
      const approved = await api.approve(sessionId);
      setSignature(approved.intent.signature);
      setScope(approved.scope);
      setLedger(approved.ledger);
      setChain(await api.chain(sessionId));
      setJustSigned(true);
      setTimeout(() => setJustSigned(false), 500);
    });

  const lines = useMemo(
    () =>
      Object.entries(quantities)
        .filter(([, qty]) => qty > 0)
        .map(([sku, qty]) => ({ sku, qty })),
    [quantities],
  );

  const cartTotal = useMemo(() => {
    if (!meta) return 0;
    return lines.reduce((sum, line) => {
      const product = meta.catalog.find((p) => p.sku === line.sku);
      return sum + (product ? product.unit_paise * line.qty : 0);
    }, 0);
  }, [lines, meta]);

  const authorize = () =>
    run(async () => {
      if (!sessionId || lines.length === 0) return;
      const result = await api.submitCart(sessionId, merchant, lines, cosign);
      setOutcomes((prev) => [...prev, result.outcome]);
      setScope(result.scope);
      setLedger(result.ledger);
      setChain(await api.chain(sessionId));
      setQuantities({});
      setCosign(false);
      setTab("trace");
      if (result.outcome.receipt) void refreshEvidence(sessionId);
    });

  const refreshEvidence = async (id: string) => {
    try {
      setEvidence(await api.evidence(id));
      setEvidenceError(null);
    } catch (e) {
      setEvidence(null);
      setEvidenceError(e instanceof Error ? e.message : String(e));
    }
  };

  /** Runs the scripted baskets one at a time and keeps whatever succeeded. A
   *  single failing step used to discard the entire run, which hid the failure
   *  behind an empty screen instead of showing it. */
  const runScripted = () =>
    run(async () => {
      if (!sessionId || !meta) return;
      const failures: string[] = [];
      for (const step of meta.scripted_steps) {
        try {
          const result = await api.submitCart(
            sessionId,
            step.merchant,
            step.lines,
            false,
            step.replay_of,
          );
          setOutcomes((prev) => [...prev, { ...result.outcome, label: step.teaches }]);
          setScope(result.scope);
          setLedger(result.ledger);
        } catch (e) {
          failures.push(`${step.label}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      setChain(await api.chain(sessionId));
      setTab("trace");
      void refreshEvidence(sessionId);
      if (failures.length > 0) throw new Error(failures.join(" · "));
    });

  const tamper = () =>
    run(async () => {
      if (!sessionId) return;
      const result = await api.tamper(sessionId);
      setChain(result.chain);
      setTab("ledger");
      if (evidence) void refreshEvidence(sessionId);
    });

  const revoke = () =>
    run(async () => {
      if (!sessionId) return;
      const result = await api.revoke(sessionId);
      setScope(result.scope);
      setLedger(result.ledger);
      setChain(await api.chain(sessionId));
    });

  const approved = signature !== null;
  const merchants = useMemo(
    () => (meta ? [...new Set(meta.catalog.map((p) => p.merchant))] : []),
    [meta],
  );

  return (
    <div className="shell">
      <header className="topbar">
        <span className="mark">
          <strong>WARRANT</strong>
          <span>no agent spends without one</span>
        </span>

        {scope && (
          <div className="budget">
            <div className="budget-row">
              <span>
                spent <b>{rupees(scope.spent_paise, { compact: true })}</b> of{" "}
                {rupees(scope.max_total_paise, { compact: true })}
              </span>
              <span>
                {scope.txns_used}/{scope.max_txns} orders ·{" "}
                {relativeWindow(scope.not_before, scope.expires_at)} window
              </span>
            </div>
            <Meter used={scope.spent_paise} total={scope.max_total_paise} />
          </div>
        )}

        <span className="topbar-spacer" />

        {/* Reports the path the last interpretation actually took. Credentials
         *  being configured is not the same as a live call succeeding -- an
         *  expired token constructs a client fine and fails at call time -- so
         *  before anything has run this says only what is available. */}
        {meta && (
          <span
            className={`chip ${pending ? (pending.source === "live" ? "live" : "replay") : ""}`}
            title={meta.capability_note}
          >
            <span className="dot" />
            {pending
              ? {
                  live: "interpreted live",
                  transcript: "interpretation replayed",
                  fallback: "no model · deterministic",
                }[pending.source]
              : meta.capability.credentials_configured
                ? "credentials available"
                : "no credentials"}
          </span>
        )}
        {scope?.revoked && (
          <span className="chip" style={{ color: "var(--block)", borderColor: "var(--block)" }}>
            <span className="dot" style={{ background: "var(--block)" }} />
            revoked
          </span>
        )}
        <button
          className="iconbtn"
          onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        >
          {theme === "dark" ? "light" : "dark"}
        </button>
      </header>

      <div className="body">
        <aside className="rail">
          <div className="rail-top">
          <section className="section">
            <span className="section-label">
              <span>1 · the person says something</span>
            </span>
            {approved ? (
              <p className="utterance">“{utterance}”</p>
            ) : (
              <textarea
                className="utterance-input"
                value={utterance}
                onChange={(e) => setUtterance(e.target.value)}
                spellCheck={false}
                aria-label="Instruction given to the agent"
              />
            )}
            {!approved && (
              <button className="primary" onClick={derive} disabled={busy || !utterance.trim()}>
                Derive the permission
              </button>
            )}
          </section>

          {pending && (
            <section className="section">
              <span className="section-label">
                <span>2 · {approved ? "the permission they signed" : "approve to sign"}</span>
              </span>
              <PermissionCard
                pending={pending}
                scope={scope}
                signature={signature}
                justSigned={justSigned}
              />
              {!approved && (
                <button className="primary" onClick={approve} disabled={busy}>
                  Approve and sign with the subject's key
                </button>
              )}
            </section>
          )}

          {error && <p className="error" style={{ margin: "0 16px 14px" }}>{error}</p>}
          </div>

          {approved && meta && (
            <section className="section rail-basket">
              <span className="section-label">
                <span>3 · the agent builds a basket</span>
                <select
                  value={merchant}
                  onChange={(e) => setMerchant(e.target.value)}
                  className="copy"
                  style={{ background: "transparent" }}
                  aria-label="Merchant"
                >
                  {merchants.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </span>

              <Storefront
                catalog={meta.catalog}
                quantities={quantities}
                merchant={merchant}
                disabled={busy}
                onChange={(sku, qty) => setQuantities((q) => ({ ...q, [sku]: qty }))}
              />

              <div className="cart-total">
                <span className="label">
                  {lines.length === 0
                    ? "nothing selected"
                    : `${lines.length} line${lines.length > 1 ? "s" : ""}`}
                </span>
                <span className="amount">{rupees(cartTotal)}</span>
              </div>

              {scope?.step_up_over_paise != null && cartTotal > scope.step_up_over_paise && (
                <label className="cosign">
                  <input
                    type="checkbox"
                    checked={cosign}
                    onChange={(e) => setCosign(e.target.checked)}
                  />
                  Subject co-signs this basket (required over{" "}
                  {rupees(scope.step_up_over_paise, { compact: true })})
                </label>
              )}

              <div className="rail-actions">
                <button
                  className="primary"
                  onClick={authorize}
                  disabled={busy || lines.length === 0}
                >
                  Authorise this basket
                </button>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="secondary" onClick={runScripted} disabled={busy}>
                    Run the five scripted baskets
                  </button>
                  <button
                    className="secondary danger"
                    onClick={revoke}
                    disabled={busy || scope?.revoked}
                  >
                    Revoke
                  </button>
                </div>
              </div>
            </section>
          )}
        </aside>

        <main className="main">
          <nav className="tabs" role="tablist">
            {(
              [
                ["trace", "Decisions", outcomes.length],
                ["ledger", "Ledger", ledger.length],
                ["evidence", "Dispute evidence", null],
              ] as const
            ).map(([key, label, count]) => (
              <button
                key={key}
                className="tab"
                role="tab"
                aria-selected={tab === key}
                onClick={() => {
                  setTab(key);
                  if (key === "evidence" && sessionId && !evidence) void refreshEvidence(sessionId);
                }}
              >
                {label}
                {count !== null && count > 0 && <span className="count">{count}</span>}
              </button>
            ))}
          </nav>

          <div className="pane" role="tabpanel">
            {tab === "trace" &&
              (outcomes.length === 0 ? (
                <Empty title="No baskets authorised yet">
                  Every basket the agent proposes is checked against the signed permission before
                  any money moves. The verdict, the rule that produced it and the numbers behind it
                  all appear here.
                </Empty>
              ) : (
                <div className="decisions">
                  {outcomes.map((outcome, i) => (
                    <DecisionCard key={`${outcome.cart.id}-${i}`} outcome={outcome} index={i} />
                  ))}
                </div>
              ))}

            {tab === "ledger" && <LedgerView entries={ledger} chain={chain} />}
            {tab === "evidence" && <EvidenceView pack={evidence} error={evidenceError} />}
          </div>
        </main>
      </div>

      <footer className="statusbar">
        {chain ? (
          <>
            <span className={`state ${chain.intact ? "ok" : "bad"}`}>
              <span className="dot" />
              {chain.intact ? "chain intact" : `chain broken at ${chain.break?.seq}`}
            </span>
            <span>
              {chain.length} {chain.length === 1 ? "entry" : "entries"}
            </span>
            <span>
              head <Hash value={chain.head} chars={12} />
            </span>
          </>
        ) : (
          <span>no ledger yet</span>
        )}
        <span className="spacer" />
        {sessionId && <span>{sessionId}</span>}
        <button
          className="iconbtn"
          onClick={tamper}
          disabled={busy || !chain || chain.length === 0}
          title="Edit a settled entry directly in SQLite, the way an insider would"
        >
          Tamper with the ledger
        </button>
      </footer>
    </div>
  );
}
