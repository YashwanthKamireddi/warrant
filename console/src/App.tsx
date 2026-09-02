import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import { relativeWindow, rupees } from "./format";
import { Certificate } from "./components/Certificate";
import { ChainDiagram } from "./components/ChainDiagram";
import { DecisionCard } from "./components/DecisionCard";
import { EvidenceView } from "./components/EvidenceView";
import { AgentRun } from "./components/AgentRun";
import { Counterfactual } from "./components/Counterfactual";
import { Landing } from "./components/Landing";
import { LedgerView } from "./components/LedgerView";
import { StandardsView } from "./components/StandardsView";
import { Storefront } from "./components/Storefront";
import { Basket, Rows, ShieldMark } from "./components/icons";
import { Badge, Empty, Gauge, Hash, Role } from "./components/primitives";
import type {
  AgentAttempt,
  ChainStatus,
  Comparison,
  EvidencePack,
  LedgerEntry,
  Meta,
  Outcome,
  PendingIntent,
  Scope,
  Signature,
} from "./types";

type Tab = "run" | "stakes" | "decisions" | "ledger" | "evidence" | "standards";

/** Every path an interpretation can take gets a label. A missing case rendered
 *  an empty chip, which is worse than a wrong one -- it looks like a bug. */
const SOURCE_LABEL: Record<string, string> = {
  pinned: "Scope pinned",
  live: "Interpreted live",
  transcript: "Interpretation replayed",
  fallback: "No model · deterministic",
};

const TABS: { key: Tab; label: string }[] = [
  { key: "run", label: "The agent shopping" },
  { key: "stakes", label: "What it prevents" },
  { key: "decisions", label: "Decisions" },
  { key: "ledger", label: "Ledger" },
  { key: "evidence", label: "Dispute evidence" },
  { key: "standards", label: "AP2 export" },
];

export function App() {
  // The landing page is the default. #workspace goes straight in, which is also
  // how the browser gates reach the console without clicking through.
  const [entered, setEntered] = useState(
    () => window.location.hash === "#workspace",
  );

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
  const [rail, setRail] = useState<"simulated" | "razorpay">("simulated");
  const [cosign, setCosign] = useState(false);
  const [tab, setTab] = useState<Tab>("run");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [attempts, setAttempts] = useState<AgentAttempt[]>([]);
  const [agentRunning, setAgentRunning] = useState(false);
  const [evidence, setEvidence] = useState<EvidencePack | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  const refreshEvidence = async (id: string) => {
    try {
      setEvidence(await api.evidence(id));
      setEvidenceError(null);
    } catch (e) {
      setEvidence(null);
      setEvidenceError(e instanceof Error ? e.message : String(e));
    }
  };

  const derive = () =>
    run(async () => {
      const started = await api.start(utterance, rail);
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
      setTimeout(() => setJustSigned(false), 520);
    });

  const lines = useMemo(
    () =>
      Object.entries(quantities)
        .filter(([, qty]) => qty > 0)
        .map(([sku, qty]) => ({ sku, qty })),
    [quantities],
  );

  const basketTotal = useMemo(() => {
    if (!meta) return 0;
    return lines.reduce((sum, line) => {
      const product = meta.catalog.find((p) => p.sku === line.sku);
      return sum + (product ? product.unit_paise * line.qty : 0);
    }, 0);
  }, [lines, meta]);

  /** Preview both outcomes for whatever is in the basket. Side-effect free --
   *  the engine evaluates against a copy of the state, so previewing never
   *  consumes budget, a nonce or an attempt. */
  useEffect(() => {
    if (!sessionId || signature === null || lines.length === 0) {
      setComparison(null);
      return;
    }
    let cancelled = false;
    api
      .compare(sessionId, merchant, lines)
      .then((c) => !cancelled && setComparison(c))
      .catch(() => !cancelled && setComparison(null));
    return () => {
      cancelled = true;
    };
  }, [sessionId, signature, merchant, lines]);

  const authorize = () =>
    run(async () => {
      if (!sessionId || lines.length === 0) return;
      const result = await api.submitCart(sessionId, merchant, lines, cosign);
      setOutcomes((prev) => [...prev, result.outcome]);
      setScope(result.scope);
      setLedger((prev) => [...prev, ...result.ledger_added]);
      setChain(await api.chain(sessionId));
      setQuantities({});
      setCosign(false);
      setTab("decisions");
      if (result.outcome.receipt) void refreshEvidence(sessionId);
    });

  /** Runs the scripted baskets one at a time and keeps whatever succeeded. A
   *  single failing step used to discard the whole run, hiding the failure
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
          setLedger((prev) => [...prev, ...result.ledger_added]);
        } catch (e) {
          failures.push(`${step.label}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      setChain(await api.chain(sessionId));
      setTab("decisions");
      void refreshEvidence(sessionId);
      if (failures.length > 0) throw new Error(failures.join(" · "));
    });

  /** Finishes debits the rail accepted but had not yet captured. On the Razorpay
   *  path this is the step that turns a paid link into a signed receipt. */
  const settle = () =>
    run(async () => {
      if (!sessionId) return;
      const result = await api.settle(sessionId);
      if (result.settled.length > 0) {
        setOutcomes((prev) => [...prev, ...result.settled]);
        setScope(result.scope);
        setLedger((prev) => [...prev, ...result.ledger_added]);
        setChain(await api.chain(sessionId));
        void refreshEvidence(sessionId);
        setTab("decisions");
      } else {
        throw new Error("Nothing has been captured yet. Pay the link, then check again.");
      }
    });

  /** Let the model shop. It is never told Priya's limits — only, if refused,
   *  the reason. Watching it work that out is the demonstration. */
  const runAgent = () =>
    run(async () => {
      if (!sessionId) return;
      setAttempts([]);
      setTab("run");
      setAgentRunning(true);
      try {
        const result = await api.agentRun(sessionId, merchant);
        setAttempts(result.attempts);
        setScope(result.scope);
        setLedger(result.ledger_added);
        setChain(await api.chain(sessionId));
        if (result.attempts.some((a) => a.outcome.receipt)) void refreshEvidence(sessionId);
      } finally {
        setAgentRunning(false);
      }
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
      setLedger((prev) => [...prev, ...result.ledger_added]);
      setChain(await api.chain(sessionId));
    });

  const approved = signature !== null;
  const merchants = useMemo(
    () => (meta ? [...new Set(meta.catalog.map((p) => p.merchant))] : []),
    [meta],
  );
  const needsCosign =
    scope?.step_up_over_paise != null && basketTotal > scope.step_up_over_paise;

  if (!entered) {
    return (
      <Landing
        onEnter={() => {
          window.location.hash = "workspace";
          setEntered(true);
        }}
      />
    );
  }

  return (
    <div className="shell">
      {/* ---------------------------------------------------------- app bar */}
      <header className="appbar">
        <div className="brand">
          <span className="brand-mark">
            <ShieldMark />
          </span>
          <span className="brand-words">
            <b>Warrant</b>
            <span>No agent spends without one</span>
          </span>
        </div>

        <span className="appbar-divider" />

        <span className="appbar-context">
          {sessionId ? (
            <>
              <span className="mono">{sessionId}</span>
              {scope?.revoked && <span className="pill stop"><span className="dot" />Revoked</span>}
            </>
          ) : (
            "No session"
          )}
        </span>

        <span className="grow" />

        {sessionId && (
          <span
            className={`pill ${rail === "razorpay" ? "ok" : ""}`}
            title={
              rail === "razorpay"
                ? "Creating real Orders and Payment Links in Razorpay test mode"
                : "Deterministic in-process rail. No network."
            }
          >
            <span className="dot" />
            {rail === "razorpay" ? "Razorpay test mode" : "Simulated rail"}
          </span>
        )}

        {/* Reports the path the last interpretation actually took. A credential
            being present is not the same as a live call succeeding. */}
        {meta && (
          <span
            className={`pill ${
              pending ? (pending.source === "live" ? "ok" : "hold") : ""
            }`}
            title={meta.capability_note}
          >
            <span className="dot" />
            {pending
              ? SOURCE_LABEL[pending.source] ?? pending.source
              : meta.capability.credentials_configured
                ? "Credentials available"
                : "No credentials"}
          </span>
        )}
      </header>

      {/* --------------------------------------------------- mandate strip */}
      <div className="mandatebar">
        {scope ? (
          <>
            <Gauge label="Spent" used={scope.spent_paise} total={scope.max_total_paise} />
            <Gauge
              label="Orders"
              used={scope.txns_used}
              total={scope.max_txns}
              unit="count"
            />
            {scope.rail_block_paise !== null && (
              <Gauge
                label="Reserve Pay block"
                used={scope.rail_block_used_paise}
                total={scope.rail_block_paise}
              />
            )}
            <span className="mandate-facts">
              <span>
                Window <b>{relativeWindow(scope.not_before, scope.expires_at)}</b>
              </span>
              <span>
                Merchants <b>{scope.merchants.join(", ")}</b>
              </span>
              <span>
                Categories <b>{scope.categories.join(", ")}</b>
              </span>
            </span>
          </>
        ) : (
          <span className="mandate-idle">
            No mandate in force. Nothing can be spent until a person signs one.
          </span>
        )}
      </div>

      {/* ------------------------------------------------------- workspace */}
      <div className="workspace">
        <aside className="rail">
          <div className="rail-scroll">
            <Role
              as="customer"
              name="Priya"
              hint={approved ? "her key has signed" : "granting permission"}
            />
            <section className="step">
              <div className="step-head">
                <span className={`step-index${approved ? " done" : ""}`}>1</span>
                <span className="step-title">Say what you want</span>
              </div>
              {approved ? (
                <p className="said">{utterance}</p>
              ) : (
                <>
                  <textarea
                    className="field"
                    value={utterance}
                    onChange={(e) => setUtterance(e.target.value)}
                    spellCheck={false}
                    aria-label="Instruction given to the agent"
                    placeholder="order chai and samosas for my team from zomato, keep it under 1000"
                  />
                  {meta && meta.rails.length > 1 && (
                    <div className="rail-choice" role="radiogroup" aria-label="Payment rail">
                      {meta.rails.map((option) => (
                        <button
                          key={option.id}
                          role="radio"
                          aria-checked={rail === option.id}
                          className={`rail-option${rail === option.id ? " on" : ""}`}
                          disabled={!option.available}
                          title={option.note}
                          onClick={() => setRail(option.id)}
                        >
                          <b>{option.label}</b>
                          <span>
                            {option.available
                              ? option.note
                              : "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET to enable"}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                  <button
                    className="btn btn-primary btn-block"
                    onClick={derive}
                    disabled={busy || !utterance.trim()}
                  >
                    {busy ? "Deriving…" : "Derive the permission"}
                  </button>
                </>
              )}
            </section>

            {pending && (
              <section className="step">
                <div className="step-head">
                  <span className={`step-index${approved ? " done" : ""}`}>2</span>
                  <span className="step-title">
                    {approved ? "The permission you signed" : "Approve it before signing"}
                  </span>
                </div>
                <Certificate
                  pending={pending}
                  scope={scope}
                  signature={signature}
                  justSigned={justSigned}
                />
                {!approved && (
                  <button
                    className="btn btn-primary btn-block"
                    onClick={approve}
                    disabled={busy}
                  >
                    {busy ? "Signing…" : "Approve and sign with the subject's key"}
                  </button>
                )}
              </section>
            )}

            {!pending && (
              <>
                <section className="step upcoming">
                  <div className="step-head">
                    <span className="step-index">2</span>
                    <span className="step-title">They approve a bounded permission</span>
                  </div>
                  <p className="step-hint">
                    The instruction becomes a scope with hard ceilings, shown back in plain English
                    and signed with their own key.
                  </p>
                </section>
                <section className="step upcoming">
                  <div className="step-head">
                    <span className="step-index">3</span>
                    <span className="step-title">Her agent builds a basket</span>
                  </div>
                  <p className="step-hint">
                    Every basket is checked against that permission before any money moves.
                  </p>
                </section>
              </>
            )}

            {error && (
              <div style={{ padding: "0 20px 16px" }}>
                <div className="notice stop">
                  <Badge kind="fail" />
                  <span>{error}</span>
                </div>
              </div>
            )}
          </div>

          {approved && meta && (
            <section className="rail-basket step">
              <Role
                as="agent"
                name="Priya's agent"
                hint="spending her permission"
              />
              <p className="agent-brief">
                <b>A model does the shopping.</b> It reads her instruction and this
                catalog, and it is never told her limits. You can also pick items
                yourself to try something specific.
              </p>
              <div className="step-head">
                <span className="step-index done">3</span>
                <span className="step-title">Build a basket</span>
                <span className="grow" />
                <select
                  className="select"
                  value={merchant}
                  onChange={(e) => setMerchant(e.target.value)}
                  aria-label="Merchant"
                >
                  {merchants.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>

              <Storefront
                catalog={meta.catalog}
                quantities={quantities}
                merchant={merchant}
                disabled={busy}
                onChange={(sku, qty) => setQuantities((q) => ({ ...q, [sku]: qty }))}
              />

              <div className="basket-total">
                <span>
                  {lines.length === 0
                    ? "Nothing selected"
                    : `${lines.length} line${lines.length > 1 ? "s" : ""}`}
                </span>
                <b>{rupees(basketTotal)}</b>
              </div>

              {needsCosign && scope?.step_up_over_paise != null && (
                <label className="cosign">
                  <input
                    type="checkbox"
                    checked={cosign}
                    onChange={(e) => setCosign(e.target.checked)}
                  />
                  <span>
                    Over {rupees(scope.step_up_over_paise, { compact: true })} the subject must
                    co-sign this exact basket. Tick to simulate them approving it.
                  </span>
                </label>
              )}

              <div className="rail-actions">
                <button
                  className="btn btn-primary btn-block"
                  onClick={runAgent}
                  disabled={busy}
                >
                  {agentRunning ? "The agent is shopping…" : "Let the agent shop"}
                </button>
                <button
                  className="btn btn-secondary btn-block"
                  onClick={authorize}
                  disabled={busy || lines.length === 0}
                >
                  {busy ? "Checking…" : "Or authorise this basket yourself"}
                </button>
                {rail === "razorpay" && (
                  <button className="btn btn-secondary" onClick={settle} disabled={busy}>
                    {busy ? "Checking…" : "Check the rail for settlement"}
                  </button>
                )}
                <div className="row">
                  <button className="btn btn-secondary" onClick={runScripted} disabled={busy}>
                    Run five scripted baskets
                  </button>
                  <button
                    className="btn btn-danger"
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
          <div className="main-role">
            <span className="role-glyph merchant" aria-hidden>
              RT
            </span>
            <span className="role-name">
              You are <b>the merchant's risk team</b>
            </span>
            <span className="role-hint">
              what the gate decided, and what you could show a bank
            </span>
          </div>

          <nav className="tabs" role="tablist">
            {TABS.map(({ key, label }) => {
              const count =
                key === "decisions" ? outcomes.length : key === "ledger" ? ledger.length : 0;
              return (
                <button
                  key={key}
                  className="tab"
                  role="tab"
                  aria-selected={tab === key}
                  onClick={() => {
                    setTab(key);
                    if (key === "evidence" && sessionId && !evidence)
                      void refreshEvidence(sessionId);
                  }}
                >
                  {label}
                  {count > 0 && <span className="count">{count}</span>}
                </button>
              );
            })}
          </nav>

          <div className="pane" role="tabpanel">
            <div className="pane-inner">
              {/* Before a permission exists there is nothing to watch, so the
                  first screen explains the architecture a viewer is about to
                  see rather than showing an empty transcript. */}
              {tab === "run" &&
                (approved ? (
                  <AgentRun attempts={attempts} running={agentRunning} />
                ) : (
                  <ChainDiagram />
                ))}

              {tab === "stakes" && (
                <Counterfactual
                  comparison={comparison}
                  empty={
                    approved
                      ? "Pick anything from the storefront and this shows what happens in both worlds — with a gate and without one. Try the Power Bank."
                      : "Approve a permission first, then add something to the basket."
                  }
                />
              )}

              {tab === "decisions" &&
                (outcomes.length === 0 ? (
                  <Empty icon={<Basket />} title="No baskets authorised yet">
                    Every basket the agent proposes is checked against the signed permission
                    before any money moves. The verdict, the rule that produced it, and the
                    numbers behind that rule all appear here.
                  </Empty>
                ) : (
                  outcomes.map((outcome, i) => (
                    <DecisionCard key={`${outcome.cart.id}-${i}`} outcome={outcome} index={i} />
                  ))
                ))}

              {tab === "ledger" && <LedgerView entries={ledger} chain={chain} />}
              {tab === "evidence" && <EvidenceView pack={evidence} error={evidenceError} />}
              {tab === "standards" && <StandardsView sessionId={sessionId} />}
            </div>
          </div>
        </main>
      </div>

      {/* ------------------------------------------------------ status bar */}
      <footer className="statusbar">
        {chain ? (
          <>
            <span className={`state ${chain.intact ? "ok" : "stop"}`}>
              <span className="dot" />
              {chain.intact ? "Chain intact" : `Chain broken at entry ${chain.break?.seq}`}
            </span>
            <span>
              {chain.length} {chain.length === 1 ? "entry" : "entries"}
            </span>
            <span>
              head <Hash value={chain.head} chars={14} />
            </span>
          </>
        ) : (
          <span>No ledger yet</span>
        )}
        <span className="grow" />
        <button
          className="btn btn-ghost btn-sm"
          onClick={tamper}
          disabled={busy || !chain || chain.length === 0}
          title="Edit a settled entry directly in SQLite, the way an insider would"
        >
          <Rows size={13} /> Tamper with the ledger
        </button>
      </footer>
    </div>
  );
}
