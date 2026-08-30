import { useEffect, useState } from "react";
import { api } from "../api";
import { Doc } from "./icons";
import { Badge, Empty } from "./primitives";

interface Divergence {
  topic: string;
  note: string;
}

/** The chain in AP2's vocabulary.
 *
 * This exists because the fair criticism of the project is that Google's AP2
 * already defines a chained mandate model. The answer is that AP2 specifies what
 * the credential is, not who checks it — so the export is shown here next to the
 * three places the two models genuinely differ, rather than the divergences
 * being left for someone to find.
 */
export function StandardsView({ sessionId }: { sessionId: string | null }) {
  const [chain, setChain] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    api
      .ap2(sessionId)
      .then((c) => {
        setChain(c);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [sessionId]);

  if (error || !chain) {
    return (
      <Empty icon={<Doc />} title="No chain to export yet">
        Approve a permission and authorise a basket, and the same audit trail
        appears here in AP2's vocabulary inside a W3C Verifiable Credentials
        envelope.
      </Empty>
    );
  }

  const credentials = (chain.verifiableCredential ?? []) as Record<string, any>[];
  const divergences = (chain["warrant:divergences"] ?? []) as Divergence[];

  return (
    <>
      <div className="notice">
        <Badge kind="pass" />
        <span>
          <b>Shape-compatible, not certified interop.</b> AP2 standardises the
          credential. It does not standardise the check — which rules a merchant
          evaluates before settlement, what happens when a basket sits inside every
          stated bound and is still wrong, or how a refusal is recorded. That gap is
          the gate, the judge and the ledger in this repository.
        </span>
      </div>

      <div className="creds">
        {credentials.map((c) => (
          <div className="cred" key={c.id}>
            <span className="cred-kind">{c.type[1]}</span>
            <span className="cred-issuer">issued by {c.issuer}</span>
            <span className="cred-proof mono">
              {c.proof ? `${c.proof.type} · ${c.proof.verificationMethod}` : "unsigned"}
            </span>
          </div>
        ))}
      </div>

      <section className="doc">
        <div className="doc-head">
          <h4>warrant:divergences</h4>
          <small>carried inside the document, not left to be discovered</small>
        </div>
        <div className="divergences">
          {divergences.map((d) => (
            <div className="divergence" key={d.topic}>
              <b>{d.topic}</b>
              <p>{d.note}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="doc">
        <div className="doc-head">
          <h4>VerifiablePresentation</h4>
          <small>canonicalisation: {chain.verification?.canonicalization}</small>
        </div>
        <pre>{JSON.stringify(chain, null, 2)}</pre>
      </section>
    </>
  );
}
