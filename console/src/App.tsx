import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import { rupees } from "./format";
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
import { Rows, ShieldMark } from "./components/icons";
import { Gauge } from "./components/primitives";
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




export function App() {
  // The landing page is the default. #workspace goes straight in, which is also
  // how the browser gates reach the console without clicking through.
  const [entered, setEntered] = useState(
    () => window.location.hash === "#workspace",
  );

  /** The hash was read once, at mount, so the browser's back button did
   *  nothing: leaving the workspace changed the URL and left the workspace on
   *  screen. Following the hash both ways makes back and forward work, and
   *  makes /#workspace a link somebody can actually send. */
  useEffect(() => {
    const follow = () => setEntered(window.location.hash === "#workspace");
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);

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

  const [rail] = useState<"simulated" | "razorpay">("simulated");
  const [razorpayReady, setRazorpayReady] = useState(false);
  /** Real order ids and rzp.io links, keyed by the decision they belong to. */
  const [realOrders, setRealOrders] = useState<
    Record<number, { order_id: string | null; payment_link: string | null }>
  >({});
  const [cosign, setCosign] = useState(false);
  const [step, setStep] = useState(1);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [attempts, setAttempts] = useState<AgentAttempt[]>([]);
  const [agentRunning, setAgentRunning] = useState(false);
  const [evidence, setEvidence] = useState<EvidencePack | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** Whose shop this is. It was the literal string "zomato", so pointing the
   *  console at a real storefront left the storefront rendering nothing at all:
   *  every product belonged to a merchant the filter had never heard of. */
  const merchant = useMemo(() => {
    if (scope?.merchants?.length) return scope.merchants[0]!;
    return meta?.catalog[0]?.merchant ?? "";
  }, [scope, meta]);


  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m);
        setUtterance(m.default_utterance);
        // The best rail this deployment can actually reach. Asking a visitor to
        // choose between "simulated" and "real" put the most credible thing in
        // the product -- a real Razorpay order id -- behind a decision most
        // people never made.
        setRazorpayReady(m.rails.some((r) => r.id === "razorpay" && r.available));
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
      setStep(3);
      if (result.outcome.receipt) void refreshEvidence(sessionId);
    });

  /** Runs the scripted baskets one at a time and keeps whatever succeeded. A
   *  single failing step used to discard the whole run, hiding the failure
   *  behind an empty screen instead of showing it. */
  const runScripted = (stay = false) =>
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
      if (!stay) setStep(3);
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
        setStep(3);
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

  /** Put an authorized cart on the real rail. The walkthrough runs on the
   *  simulator so the audit trail completes; this is what produces a real
   *  Razorpay order and a link a reviewer can open. */
  const placeOnRazorpay = (index: number) =>
    run(async () => {
      if (!sessionId) return;
      const placed = await api.placeOnRazorpay(sessionId, index);
      setRealOrders((prev) => ({ ...prev, [index]: placed }));
    });

  const tamper = () =>
    run(async () => {
      if (!sessionId) return;
      const result = await api.tamper(sessionId);
      setChain(result.chain);
      setStep(4);
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
  const needsCosign =
    scope?.step_up_over_paise != null && basketTotal > scope.step_up_over_paise;

  // ------------------------------------------------------------- bootstrap
  /** A visitor should land on something real, not an empty form. The permission
   *  is derived and signed on arrival so step 1 opens on a signed certificate
   *  and the counterfactual on step 3 has a scope to evaluate against. */
  const [booting, setBooting] = useState(false);

  /** The agent shops the moment you arrive at its act. It was a button, which
   *  made the one screen where a real model does real work look like an offer
   *  rather than the product. */
  const [agentStarted, setAgentStarted] = useState(false);
  useEffect(() => {
    if (step !== 2 || !approved || agentStarted || agentRunning || busy) return;
    setAgentStarted(true);
    void runAgent();
  }, [step, approved, agentStarted, agentRunning, busy, runAgent]);

  useEffect(() => {
    if (!entered || !meta || sessionId || booting) return;
    setBooting(true);
    void (async () => {
      try {
        // Deliberately the simulator, and the chip says so.
        //
        // A real Razorpay payment cannot be completed server to server -- the
        // customer authorises on their own device, which is exactly the property
        // that makes the rail trustworthy. Defaulting the walkthrough to it
        // therefore leaves every debit at settled=false forever: no receipt, no
        // evidence pack, and an AP2 export missing its PaymentMandate. The
        // audit trail is the thing being demonstrated, so it has to complete.
        //
        // The real rail is one click away on any allowed decision, and it
        // creates a real order and a real payment link. Nothing here pretends
        // to be Razorpay while running on the simulator.
        const started = await api.start(meta.default_utterance, "simulated");
        setSessionId(started.session_id);
        setPending(started.pending);
        const ok = await api.approve(started.session_id);
        setSignature(ok.intent.signature);
        setScope(ok.scope);
        setLedger(ok.ledger);
        setChain(await api.chain(started.session_id));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBooting(false);
      }
    })();
  }, [entered, meta, sessionId, booting]);

  /** The cheapest thing this merchant sells that the permission does not cover.
   *  Asked of the catalogue rather than named: the products are a real
   *  storefront's now, so a hard-coded sku is a promise about somebody else's
   *  inventory -- and it was `powerbank`, which that merchant does not stock. */
  const outOfScope = useMemo(() => {
    if (!meta || !scope) return null;
    const permitted = new Set(scope.categories);
    // A product the merchant actually sells, never one of the adversarial
    // fixtures Warrant appends. Seeding the counterfactual with our own planted
    // item makes the strongest screen in the console look invented, which is
    // the whole reason the catalogue is a real storefront's now.
    return (
      meta.catalog
        .filter(
          (p) =>
            p.merchant === merchant &&
            !permitted.has(p.category) &&
            !p.sku.startsWith("warrant-"),
        )
        .sort((a, b) => a.unit_paise - b.unit_paise)[0] ?? null
    );
  }, [meta, scope, merchant]);

  const seedBasket = (n: number) => {
    setStep(n);
    if (n === 3 && approved && outOfScope && Object.keys(quantities).length === 0) {
      setQuantities({ [outOfScope.sku]: 1 });
    }
  };

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

  const STEPS = [
    { n: 1, label: "The permission", who: "You are Priya" },
    { n: 2, label: "Her agent shops", who: "You are the agent" },
    { n: 3, label: "What it prevents", who: "You are the agent" },
    { n: 4, label: "The record", who: "You are the risk team" },
  ];
  const here = STEPS[step - 1] ?? STEPS[0]!;

  return (
    <div className="shell">
      {/* ---------------------------------------------------------- app bar */}
      <header className="appbar">
        <a className="brand" href="#" aria-label="Back to the overview">
          <span className="brand-mark">
            <ShieldMark />
          </span>
          <span className="brand-words">
            <b>Warrant</b>
            <span>No agent spends without one</span>
          </span>
        </a>
        <span className="grow" />
        {scope?.revoked && (
          <span className="pill stop">
            <span className="dot" />
            Revoked
          </span>
        )}
        {sessionId && (
          <span className={`pill ${rail === "razorpay" ? "ok" : ""}`}>
            <span className="dot" />
            {rail === "razorpay" ? "Razorpay test mode" : "Simulated rail"}
          </span>
        )}
      </header>

      {/* --------------------------------------------------------- stepper */}
      <nav className="steps" aria-label="Walkthrough">
        {STEPS.map((s) => (
          <button
            key={s.n}
            className={`stepbtn${step === s.n ? " on" : ""}${step > s.n ? " done" : ""}`}
            aria-current={step === s.n ? "step" : undefined}
            onClick={() => seedBasket(s.n)}
          >
            <span className="stepbtn-n">{s.n}</span>
            <span className="stepbtn-label">{s.label}</span>
          </button>
        ))}
      </nav>

      {error && (
        <div className="stage-error" role="alert">
          {error}
        </div>
      )}

      {/* ----------------------------------------------------------- stage */}
      <main className="stage">
        <p className="stage-who">{here!.who}</p>

        {step === 1 && (
          <section className="act">
            <h1 className="act-head">
              She said this once. Her key signed it. Nothing can be spent outside it.
            </h1>
            {pending ? (
              <>
                <blockquote className="said-big">{utterance}</blockquote>
                <Certificate
                  pending={pending}
                  scope={scope}
                  signature={signature}
                  justSigned={justSigned}
                />
              </>
            ) : (
              <p className="act-wait">Deriving the permission…</p>
            )}

            <details className="tryown">
              <summary>Use your own words</summary>
              <textarea
                className="field"
                value={utterance}
                onChange={(e) => setUtterance(e.target.value)}
                spellCheck={false}
                aria-label="Instruction given to the agent"
              />
              <button
                className="btn btn-primary"
                onClick={derive}
                disabled={busy || !utterance.trim()}
              >
                {busy ? "Deriving…" : "Derive a new permission"}
              </button>
              {pending && !approved && (
                <button className="btn btn-primary" onClick={approve} disabled={busy}>
                  Approve and sign with the subject&rsquo;s key
                </button>
              )}
            </details>
          </section>
        )}

        {step === 2 && (
          <section className="act">
            <h1 className="act-head">
              The agent is never told her limits. It finds them by being refused.
            </h1>
            <div className="act-do">
              <button
                className="btn btn-primary"
                onClick={runAgent}
                disabled={busy || !approved || agentRunning}
              >
                {agentRunning
                  ? "The agent is shopping…"
                  : attempts.length > 0
                    ? "Run it again"
                    : "Run the agent"}
              </button>
              {/* This screen promises that a model reads the instruction. Whether
                  one is actually reachable belongs next to the button that
                  claims it, not in a chip in the corner -- and a clone with no
                  key should find out before clicking, not after. */}
              {meta && (
                <span className="act-note" title={meta.capability_note}>
                  {meta.capability.credentials_configured
                    ? "A live model call."
                    : meta.capability.transcript_available
                      ? "No model configured, so this replays a captured response — " +
                        meta.capability.transcript_provenance
                      : "No model configured and no transcript, so the scope stays at " +
                        "the deterministic minimum."}
                </span>
              )}
            </div>
            <AgentRun attempts={attempts} running={agentRunning} />
          </section>
        )}

        {step === 3 && (
          <section className="act">
            <h1 className="act-head">
              Put something in the basket she never permitted.
            </h1>
            <Counterfactual
              comparison={comparison}
              empty="Add anything below to see what it costs with and without Warrant."
            />
            {meta && (
              <Storefront
                catalog={meta.catalog}
                quantities={quantities}
                merchant={merchant}
                permitted={scope?.categories}
                onChange={(sku, qty) =>
                  setQuantities((q) => ({ ...q, [sku]: qty }))
                }
                disabled={!approved || busy}
              />
            )}
            <div className="act-do">
              <button
                className="btn btn-primary"
                onClick={authorize}
                disabled={busy || !approved || lines.length === 0}
              >
                Authorise this basket
                <span className="btn-amount">{rupees(basketTotal)}</span>
              </button>
              {needsCosign && (
                <label className="cosign">
                  <input
                    type="checkbox"
                    checked={cosign}
                    onChange={(e) => setCosign(e.target.checked)}
                  />
                  Attach the second signature this amount requires
                </label>
              )}
            </div>
            {outcomes.length > 0 && (
              <div className="decisions">
                {outcomes.map((outcome, i) => (
                  <DecisionCard
                    key={`${outcome.cart.id}-${i}`}
                    outcome={outcome}
                    index={i}
                    realOrder={realOrders[i]}
                    onPlaceOnRazorpay={
                      razorpayReady && outcome.receipt ? () => placeOnRazorpay(i) : undefined
                    }
                    busy={busy}
                  />
                ))}
              </div>
            )}
          </section>
        )}

        {step === 4 && (
          <section className="act">
            <h1 className="act-head">
              Every decision, in order, and provable after the fact.
            </h1>
            {ledger.length < 3 && (
              <div className="act-do">
                <button
                  className="btn btn-primary"
                  onClick={() => runScripted(true)}
                  disabled={busy || !approved}
                >
                  {busy ? "Deciding…" : "Put five baskets through the gate"}
                </button>
                <span className="act-note">
                  Nothing has been decided yet, so there is nothing to prove. This
                  runs the five that teach each verdict and writes every one of
                  them — including the refusals — into the record below.
                </span>
              </div>
            )}
            <LedgerView entries={ledger} chain={chain} />
            <div className="act-do">
              <button className="btn" onClick={tamper} disabled={busy || !sessionId}>
                <Rows size={13} /> Try to rewrite the ledger
              </button>
              <button className="btn" onClick={revoke} disabled={busy || !approved}>
                Revoke the permission
              </button>
              <button className="btn" onClick={settle} disabled={busy || !sessionId}>
                Settle what the rail captured
              </button>
            </div>
            <details className="more">
              <summary>The dispute pack a merchant would file</summary>
              <EvidenceView pack={evidence} error={evidenceError} />
            </details>
            <details className="more">
              <summary>The same mandate as an AP2 / W3C credential</summary>
              <StandardsView sessionId={sessionId} />
            </details>
            <details className="more">
              <summary>How the three artefacts bind to each other</summary>
              <ChainDiagram />
            </details>
          </section>
        )}
      </main>

      {/* ------------------------------------------------------- stage nav */}
      <footer className="stagenav">
        <button className="btn" onClick={() => setStep(step - 1)} disabled={step === 1}>
          Back
        </button>
        {scope && (step === 2 || step === 3) && (
          <span className="budget">
            <Gauge label="Spent" used={scope.spent_paise} total={scope.max_total_paise} />
            <Gauge label="Orders" used={scope.txns_used} total={scope.max_txns} unit="count" />
          </span>
        )}
        <span className="grow" />
        {step === 4 ? (
          <a className="btn btn-primary" href="#">
            Back to the overview
          </a>
        ) : (
          <button className="btn btn-primary" onClick={() => seedBasket(step + 1)}>
            Next — {STEPS[step]!.label}
          </button>
        )}
      </footer>
    </div>
  );
}
