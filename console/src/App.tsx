import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import { categoryWords, rupees } from "./format";
import { ChainDiagram } from "./components/ChainDiagram";
import { EvidenceView } from "./components/EvidenceView";
import { Feed } from "./components/Feed";
import { Landing } from "./components/Landing";
import { LedgerView } from "./components/LedgerView";
import { StandardsView } from "./components/StandardsView";
import { ShieldMark } from "./components/icons";
import { Gauge } from "./components/primitives";
import type {
  ChainStatus,
  EvidencePack,
  FeedItem,
  LedgerEntry,
  Meta,
  Outcome,
  PendingIntent,
  Scope,
  Signature,
  VerifiedPayment,
} from "./types";

/** The console.
 *
 * One screen. What you permitted at the top, everything that has happened
 * since in the middle, where the money stands at the bottom, and the proof in
 * a drawer for anyone who wants it.
 *
 * This replaced a four-act walkthrough with a Next button. That version
 * explained the idea and demonstrated the product badly: the agent's work and
 * your own sat on different screens, the record was a step you had to reach,
 * and the real Razorpay order -- the most credible thing here -- was three
 * clicks and a disclosure widget away from anything. Nobody who opened it
 * could say what the software did.
 */
export function App() {
  // The landing page is the default. #workspace goes straight in, which is also
  // how the browser gates reach the console without clicking through.
  const [entered, setEntered] = useState(
    () => window.location.hash === "#workspace",
  );

  useEffect(() => {
    const follow = () => setEntered(window.location.hash === "#workspace");
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);

  /** Escape closes the drawer, because every drawer on the web does. */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setProofOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const [meta, setMeta] = useState<Meta | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingIntent | null>(null);
  const [signature, setSignature] = useState<Signature | null>(null);
  const [scope, setScope] = useState<Scope | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [chain, setChain] = useState<ChainStatus | null>(null);
  const [razorpayReady, setRazorpayReady] = useState(false);

  /** Everything proposed so far, in order, whoever proposed it. */
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentStarted, setAgentStarted] = useState(false);
  /** Set when a person answered "no" to the escalation, so it stops asking. */
  const [declined, setDeclined] = useState(false);

  /** Orders already created for a cart, so pressing pay twice does not create
   *  two of them. */
  const [realOrders, setRealOrders] = useState<
    Record<string, { order_id: string | null; payment_link: string | null; amount_paise: number }>
  >({});
  /** Payments Razorpay signed, confirmed server-side against the key secret. */
  const [paid, setPaid] = useState<Record<string, VerifiedPayment>>({});
  const [payError, setPayError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidencePack | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [proofOpen, setProofOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [booting, setBooting] = useState(false);

  /** Whose shop this is, read from the permission rather than hard-coded. */
  const merchant = useMemo(() => {
    if (scope?.merchants?.length) return scope.merchants[0]!;
    return meta?.catalog[0]?.merchant ?? "";
  }, [scope, meta]);

  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m);
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

  const refreshEvidence = useCallback(async (id: string) => {
    try {
      setEvidence(await api.evidence(id));
      setEvidenceError(null);
    } catch (e) {
      setEvidence(null);
      setEvidenceError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const push = (outcome: Outcome, extra: Partial<FeedItem> = {}) =>
    setFeed((prev) => [
      ...prev,
      { id: `${outcome.cart.id}-${prev.length}`, outcome, ...extra },
    ]);

  // ------------------------------------------------------------- bootstrap
  /** A visitor lands on something real, not an empty form: the permission is
   *  derived and signed on arrival, and the agent starts shopping against it. */
  useEffect(() => {
    if (!entered || !meta || sessionId || booting) return;
    setBooting(true);
    void (async () => {
      try {
        // Deliberately the simulator, and the chip says so.
        //
        // A real Razorpay payment cannot be completed server to server -- the
        // customer authorises on their own device, which is exactly the
        // property that makes the rail trustworthy. Defaulting to it therefore
        // leaves every debit at settled=false forever: no receipt, no evidence
        // pack, and an AP2 export missing its PaymentMandate. The audit trail
        // is the thing being demonstrated, so it has to complete. The real rail
        // is one click away on any allowed decision.
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

  /** Let the model shop. It is never told the limits — only, if refused, the
   *  reason. Watching it work that out is the demonstration, so it runs on
   *  arrival rather than waiting behind a button. */
  const runAgent = useCallback(
    () =>
      run(async () => {
        if (!sessionId) return;
        setAgentRunning(true);
        try {
          const result = await api.agentRun(sessionId, merchant);
          setFeed((prev) => [
            ...prev,
            ...result.attempts.map((a, i) => ({
              id: `${a.outcome.cart.id}-${prev.length + i}`,
              agent: a.agent,
              outcome: a.outcome,
            })),
          ]);
          setScope(result.scope);
          setLedger(result.ledger_added);
          setChain(await api.chain(sessionId));
          if (result.attempts.some((a) => a.outcome.receipt)) {
            void refreshEvidence(sessionId);
          }
        } finally {
          setAgentRunning(false);
        }
      }),
    [run, sessionId, merchant, refreshEvidence],
  );

  /** `?agent=manual` opens the console without spending a model call.
   *
   *  The layout and overlap gates open the page at eleven viewports each. With
   *  the agent running on arrival that is eleven live runs per gate, which is
   *  slow, rate-limits a free key, and tests nothing either gate is for -- they
   *  measure boxes. The gates that are actually about the agent still open it
   *  the way a visitor does. */
  const autoAgent = useMemo(
    () => new URLSearchParams(window.location.search).get("agent") !== "manual",
    [],
  );

  useEffect(() => {
    if (!autoAgent) return;
    if (!entered || !signature || agentStarted || agentRunning || busy) return;
    setAgentStarted(true);
    void runAgent();
  }, [autoAgent, entered, signature, agentStarted, agentRunning, busy, runAgent]);

  /** The escalation waiting on a person, if there is one. Only ever the last
   *  entry: an escalation the agent already worked around is history. */
  const askAbout = useMemo(() => {
    if (agentRunning || declined) return null;
    const last = feed[feed.length - 1];
    return last && last.outcome.verdict === "escalate" ? last : null;
  }, [feed, agentRunning, declined]);

  /** Approve the basket Warrant escalated, as the person who set the limit.
   *
   *  A real Ed25519 co-signature by the subject's key over the cart body, and
   *  the same gate re-runs against it. `step_up.cosignature` goes from fail to
   *  pass because a signature now exists that did not before — there is no
   *  branch that waves it through, and a basket that also fails on category or
   *  budget stays refused with the signature attached. */
  const approveEscalation = (item: FeedItem) =>
    run(async () => {
      if (!sessionId) return;
      const picks = item.outcome.cart.line_items.map((l) => ({
        sku: l.sku,
        qty: l.qty,
      }));
      const result = await api.submitCart(sessionId, merchant, picks, true);
      push(result.outcome, { note: "You approved it, and signed it with your key." });
      setScope(result.scope);
      setLedger((prev) => [...prev, ...result.ledger_added]);
      setChain(await api.chain(sessionId));
      if (result.outcome.receipt) void refreshEvidence(sessionId);
    });

  /** The cheapest thing this merchant sells that the permission does not cover.
   *  Asked of the catalogue rather than named: the products are a real
   *  storefront's, so a hard-coded sku is a promise about somebody else's
   *  inventory. Never one of the adversarial fixtures Warrant appends — seeding
   *  this with our own planted item would make the sharpest moment in the
   *  console look invented. */
  const outOfScope = useMemo(() => {
    if (!meta || !scope) return null;
    const permitted = new Set(scope.categories);
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

  /** Buy something the permission never covered, and price the refusal.
   *
   *  The counterfactual is a real evaluation by the same gate against a copy of
   *  the state, so asking what it would have cost consumes no budget, nonce or
   *  attempt. */
  const probeOutOfScope = () =>
    run(async () => {
      if (!sessionId || !outOfScope) return;
      const picks = [{ sku: outOfScope.sku, qty: 1 }];
      const [result, comparison] = await Promise.all([
        api.submitCart(sessionId, merchant, picks, false),
        api.compare(sessionId, merchant, picks).catch(() => null),
      ]);
      push(result.outcome, {
        note: `Something you never asked for: ${outOfScope.name}.`,
        ...(comparison ? { counterfactual: comparison } : {}),
      });
      setScope(result.scope);
      setLedger((prev) => [...prev, ...result.ledger_added]);
      setChain(await api.chain(sessionId));
    });

  /** The five baskets that each teach a different verdict — replay, expiry, a
   *  planted product name, a merchant swap, a ceiling breach. Real evaluations,
   *  kept because a record with one refusal in it does not show what a record
   *  is for. */
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
          push(result.outcome, { note: step.teaches });
          setScope(result.scope);
          setLedger((prev) => [...prev, ...result.ledger_added]);
        } catch (e) {
          failures.push(`${step.label}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      setChain(await api.chain(sessionId));
      void refreshEvidence(sessionId);
      if (failures.length > 0) throw new Error(failures.join(" · "));
    });

  /** Pay for an allowed cart on Razorpay, in Razorpay's own payment sheet.
   *
   *  The server creates a real test-mode order, Checkout opens over the page,
   *  and whatever it hands back goes straight to the server to be checked
   *  against the key secret. A browser saying it paid is not evidence; an HMAC
   *  only the server can recompute is. Until that check returns, nothing here
   *  claims the payment happened.
   */
  const payOnRazorpay = (item: FeedItem) =>
    run(async () => {
      if (!sessionId || !meta?.razorpay_key_id) return;

      // Reuse the order this cart already has. Closing Razorpay and pressing
      // the button again used to mint a second order for the same basket, so a
      // reviewer who dismissed the sheet once left two orders on the account
      // for one purchase -- and a test account gets thirty a day.
      const placed =
        realOrders[item.id] ?? (await api.placeOnRazorpay(sessionId, -1));
      setRealOrders((prev) => ({ ...prev, [item.id]: placed }));
      if (!placed.order_id || !window.Razorpay) return;

      const checkout = new window.Razorpay({
        key: meta.razorpay_key_id,
        order_id: placed.order_id,
        amount: placed.amount_paise,
        currency: "INR",
        name: merchant,
        description: item.outcome.cart.line_items
          .map((l) => `${l.name} ×${l.qty}`)
          .join(", "),
        // Razorpay's sheet takes a literal colour, so read it from the token
        // rather than writing the hex twice and letting them drift.
        theme: {
          color:
            getComputedStyle(document.documentElement)
              .getPropertyValue("--brand")
              .trim() || undefined,
        },
        // Netbanking, and a contact already filled in.
        //
        // Razorpay's own /v1/methods for this account reports upi: false, so
        // the sheet never offered it -- and the generic test card numbers come
        // back "international cards not supported", because a test account is
        // an Indian account and those cards are not. Netbanking is enabled
        // here on forty banks and its test flow ends on a page with a Success
        // button, so it is the path that actually completes. The contact step
        // is prefilled because being asked for a phone number is not part of
        // what this is demonstrating.
        // Razorpay collects a mobile number itself no matter what is passed
        // for `contact`, so that field is not set: config that does nothing is
        // worse than no config, because the next person believes it. The email
        // does take, and the method opens the sheet on netbanking.
        prefill: { method: "netbanking", email: "test@razorpay.com" },
        modal: {
          ondismiss: () =>
            setPayError(
              "You closed Razorpay before paying. The order is still open — the " +
                "button reopens it.",
            ),
        },
        handler: (response) => {
          setPayError(null);
          void run(async () => {
            const proof = await api.verifyRazorpay(sessionId, response);
            setPaid((prev) => ({ ...prev, [item.id]: proof }));
          });
        },
      });

      // Razorpay declining a payment is a real answer from a real API, and the
      // console says what it said rather than falling silent.
      checkout.on("payment.failed", (failure) => {
        const why = failure.error?.description || failure.error?.reason;
        setPayError(
          why
            ? `Razorpay declined it: ${why}. On this test account, pay by ` +
              "Netbanking — pick any bank and press Success on the page it opens."
            : "Razorpay declined the payment. Pay by Netbanking: pick any bank, " +
              "then Success.",
        );
      });

      checkout.open();
    });

  const tamper = () =>
    run(async () => {
      if (!sessionId) return;
      const result = await api.tamper(sessionId);
      setChain(result.chain);
      setProofOpen(true);
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

  /** Revoking and breaking the chain are both permanent, which is the point of
   *  them. A demonstration you can brick and cannot un-brick is one people
   *  press once, so this hands back a fresh permission. */
  const restart = () =>
    run(async () => {
      setSessionId(null);
      setPending(null);
      setSignature(null);
      setScope(null);
      setLedger([]);
      setChain(null);
      setFeed([]);
      setAgentStarted(false);
      setDeclined(false);
      setRealOrders({});
      setPaid({});
      setPayError(null);
      setEvidence(null);
      setEvidenceError(null);
      setProofOpen(false);
    });

  const approved = signature !== null;
  const revoked = scope?.revoked === true;
  const chainBroken = chain?.break != null;
  const refusals = feed.filter((f) => f.outcome.verdict === "block").length;
  const escalations = feed.filter((f) => f.outcome.verdict === "escalate").length;
  const settledItem = [...feed].reverse().find((f) => f.outcome.rail?.settled) ?? null;

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
        {revoked && (
          <span className="pill stop">
            <span className="dot" />
            Permission revoked
          </span>
        )}
        {/* "Simulated rail" is a word from inside the engine. What a reader
            needs to know is that no real money is at stake, which is a
            different sentence and the one that reassures rather than puzzles. */}
        <span className="pill" title="Razorpay test mode. No real money can move.">
          <span className="dot" />
          Test mode — no real money
        </span>
        <button
          className={`btn btn-sm${proofOpen ? " on" : ""}`}
          onClick={() => setProofOpen((v) => !v)}
          aria-expanded={proofOpen}
        >
          {proofOpen ? "Hide the record" : "See the record"}
        </button>
      </header>

      {error && (
        <div className="stage-error" role="alert">
          {error}
        </div>
      )}

      {(revoked || chainBroken) && (
        <div className="spent-banner" role="status">
          <span>
            {revoked && chainBroken
              ? "This permission is revoked and this record is broken."
              : revoked
                ? "This permission is revoked, so every basket from here is refused."
                : "This record is broken, so every entry after the edit is orphaned."}{" "}
            Both are permanent, which is the point of them.
          </span>
          <button className="btn btn-sm" onClick={restart} disabled={busy}>
            {busy ? "Starting…" : "Start again with a fresh permission"}
          </button>
        </div>
      )}

      <main className="work">
        {/* ------------------------------------------------- the permission */}
        <section className="perm" aria-label="What you permitted">
          <div className="perm-said">
            <span className="perm-label">You said, once</span>
            <p className="perm-quote">
              {pending ? `“${meta?.default_utterance ?? ""}”` : "…"}
            </p>
          </div>
          <div className="perm-bounds">
            <span className="perm-label">
              {approved ? "So your agent may spend" : "Deriving the bounds…"}
            </span>
            {scope && (
              <ul className="bounds">
                <li>
                  up to <b className="num">{rupees(scope.max_total_paise)}</b> in total
                </li>
                <li>
                  at <b>{merchant}</b>, nowhere else
                </li>
                <li>
                  on <b>{categoryWords(scope.categories)}</b> only
                </li>
                <li>
                  across <b>{scope.max_txns}</b> orders
                </li>
                {scope.step_up_over_paise !== null && (
                  <li>
                    and anything over <b className="num">{rupees(scope.step_up_over_paise)}</b>{" "}
                    has to come back to you
                  </li>
                )}
              </ul>
            )}
            {signature && (
              <p className="perm-sig">
                Signed by your own key · <span className="mono">{signature.key_id}</span>.
                Nothing in this system can widen it.
              </p>
            )}
          </div>
        </section>

        {/* -------------------------------------------------------- the feed */}
        <section className="live" aria-label="What has happened">
          {approved && (
            <div className="live-do">
              {outOfScope && (
                <button
                  className="btn btn-primary"
                  onClick={probeOutOfScope}
                  disabled={busy || agentRunning}
                >
                  Try to buy something you never asked for
                </button>
              )}
              <button className="btn" onClick={runAgent} disabled={busy || agentRunning}>
                Let the agent shop again
              </button>
              <button className="btn" onClick={runScripted} disabled={busy || agentRunning}>
                Put five harder baskets through it
              </button>
            </div>
          )}

          <Feed
            items={feed}
            running={agentRunning || booting}
            busy={busy}
            askAbout={askAbout}
            onApprove={approveEscalation}
            onDecline={() => setDeclined(true)}
            onPay={razorpayReady && meta?.razorpay_key_id ? payOnRazorpay : undefined}
            payments={paid}
            payError={payError}
          />

          {declined && (
            <p className="live-note">
              You said no, so the basket was never submitted and no money moved.
              Warrant asking is already in the record — a dispute usually turns on
              what was stopped.
            </p>
          )}
        </section>
      </main>

      {/* ------------------------------------------------ where the money is */}
      <footer className="money">
        {scope && (
          <>
            <Gauge label="Spent" used={scope.spent_paise} total={scope.max_total_paise} />
            <Gauge
              label="Orders"
              used={scope.txns_used}
              total={scope.max_txns}
              unit="count"
            />
            <span className="money-refused">
              <b>{refusals}</b> {refusals === 1 ? "basket" : "baskets"} refused
            </span>
            {escalations > 0 && (
              <span className="money-asked">
                <b>{escalations}</b> sent back for your approval
              </span>
            )}
          </>
        )}
        <span className="grow" />
        {settledItem && paid[settledItem.id] && (
          <span className="money-order">
            Paid on Razorpay{" "}
            <span className="mono">{paid[settledItem.id]!.payment_id}</span>
          </span>
        )}
      </footer>

      {/* ------------------------------------------------------- the drawer */}
      {proofOpen && (
        <>
          {/* Dimming what is behind it is what makes a panel read as a layer
              rather than as a column that appeared. Clicking it closes. */}
          <div
            className="proof-scrim"
            onClick={() => setProofOpen(false)}
            aria-hidden
          />
          <aside className="proof" role="dialog" aria-label="The proof" aria-modal>
            <header className="proof-head">
              <div>
                <h2>The proof</h2>
                <p className="proof-sub">
                  Every decision above, in order, with what a merchant would send a
                  bank if you disputed one.
                </p>
              </div>
              <button className="btn btn-sm" onClick={() => setProofOpen(false)}>
                Close
              </button>
            </header>

            <LedgerView entries={ledger} chain={chain} />

            <div className="proof-do">
              <button className="btn" onClick={tamper} disabled={busy || !sessionId}>
                Try to rewrite the ledger
              </button>
              <button className="btn" onClick={revoke} disabled={busy || !approved}>
                Revoke the permission
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
          </aside>
        </>
      )}
    </div>
  );
}
