import { useEffect, useState } from "react";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowUpRight,
  Check,
  FileCheck2,
} from "lucide-react";
import {
  Avatar,
  Brand,
  Json,
  Tag,
  clock,
  list,
  person,
  stamp,
  type Data,
} from "./living";
export default function RecordedAgreement() {
  const [proof, setProof] = useState<Data | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    fetch("/recorded-agreement.json", { signal: c.signal, credentials: "omit" })
      .then((r) => {
        if (!r.ok) throw new Error("The recorded snapshot is unavailable.");
        return r.json();
      })
      .then(setProof)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, []);
  const content = proof?.content,
    p = list(content?.proposals).find(
      (p) => p.proposal_id === content?.current_proposal_id,
    ),
    effects: Data[] = list(content?.observed_calendar_effects).flatMap((o) =>
      list(o.events).map((e) => ({ ...e, owner_id: o.owner_id })),
    );
  return (
    <div className="cg-app">
      <a className="cg-skip" href="#main">
        Skip to historical record
      </a>
      <header className="cg-header">
        <a href="/" aria-label="Common Ground home">
          <Brand />
        </a>
        <div className="cg-header-end">
          <Tag>Historical v1 record</Tag>
        </div>
      </header>
      <main className="cg-main" id="main">
        <div className="cg-context">
          <a href="/">
            <ArrowLeft size={14} />
            Back to Common Ground
          </a>
          <span>Read-only · no credentials required</span>
        </div>
        <section className="cg-page-head">
          <div>
            <p className="cg-eyebrow">A RECORDED, AUTHORED FICTIONAL RUN</p>
            <h1>A plan, and the record behind it.</h1>
            <p>
              A historical local development snapshot. These expired v1
              decisions authorize no new v2 work.
            </p>
          </div>
        </section>
        {error ? (
          <div className="cg-notice warning" role="alert">
            <div>
              <strong>{error}</strong>
              <p>
                The recording is a saved file and does not need a service
                session.
              </p>
              <button
                className="cg-text"
                onClick={() => window.location.reload()}
              >
                Try loading the recording again
              </button>
            </div>
          </div>
        ) : !content ? (
          <div className="cg-empty" role="status" aria-live="polite">
            <p>Loading the original recorded snapshot…</p>
          </div>
        ) : (
          <div className="cg-layout">
            <div className="cg-main-column">
              <section className="cg-paper">
                <div className="cg-sheet-top">
                  <p className="cg-eyebrow">THE RECORDED ARRANGEMENT</p>
                  <Tag>Snapshot {stamp(content.generated_at)}</Tag>
                </div>
                <h2>{content.scenario?.title}</h2>
                <p className="cg-caption">
                  {content.scenario?.date} · {content.scenario?.timezone} ·
                  historical state: {content.current_state}
                </p>
                <ul className="cg-review-list" style={{ marginTop: 25 }}>
                  {list(p?.assignments).map((a) => {
                    const t = list(p?.tasks).find(
                      (t) => t.task_id === a.task_id,
                    );
                    return (
                      <li key={a.task_id}>
                        <Avatar id={a.owner_id} />
                        <div>
                          <strong>{t?.label || a.task_id}</strong>
                          <span>
                            {person(a.owner_id)} · {clock(a.start)}–
                            {clock(a.end)} · {t?.location}
                          </span>
                        </div>
                        <Tag>Historical commitment</Tag>
                      </li>
                    );
                  })}
                </ul>
                <div className="cg-notice">
                  <FileCheck2 size={20} />
                  <p>
                    The snapshot records{" "}
                    {effects.filter((e) => e.status === "VERIFIED").length}{" "}
                    verified calendar observations across{" "}
                    {list(content.observed_calendar_effects).length} owner
                    services. This confirms app-created entries were read back
                    at export time; it does not establish arrival or handoff
                    completion.
                  </p>
                </div>
                <a
                  className="cg-button secondary"
                  href="/recorded-agreement.json"
                  download
                >
                  <ArrowDownToLine size={15} />
                  Download original sanitized snapshot
                </a>
                <Json
                  value={proof}
                  label="Inspect the full original evidence, receipts and limitations"
                />
              </section>
              <section className="cg-paper">
                <p className="cg-eyebrow">HISTORICAL CALENDAR OBSERVATIONS</p>
                <h2>What was actually observed.</h2>
                {effects.map((e, i) => (
                  <div className="cg-receipt" key={e.action_id || i}>
                    <Check size={17} />
                    <div>
                      <strong>
                        {person(e.owner_id)} · {e.status}
                      </strong>
                      <p>{e.event_id}</p>
                      <small>{stamp(e.verified_at)}</small>
                    </div>
                  </div>
                ))}
              </section>
            </div>
            <aside className="cg-aside">
              <section className="cg-circle">
                <p className="cg-eyebrow">SCOPE OF THIS RECORD</p>
                <h2>
                  Evidence with
                  <br />
                  clear edges.
                </h2>
                <p>
                  Fictional local data, separate persistent owner services,
                  authored fault fixtures, and retained actual provider-attempt
                  receipts. This is development evidence, with no human study,
                  deployed result or real Google account qualification claimed.
                </p>
                <p>
                  The interactive recorded workflow is still available with its
                  original launcher pairing.
                </p>
                <a className="cg-text" href="?legacy=1">
                  Open legacy workflow <ArrowUpRight size={14} />
                </a>
              </section>
              <section className="cg-small-card">
                <h3>Try an arrangement that can change.</h3>
                <p>
                  The new fictional care circle keeps stable commitments and
                  asks for fresh decisions around changed handoffs.
                </p>
                <a className="cg-text" href="/">
                  Try the living arrangement <ArrowUpRight size={14} />
                </a>
              </section>
            </aside>
          </div>
        )}
        <footer className="cg-footer">
          <Brand />
          <span>Historical evidence · original source snapshot preserved</span>
        </footer>
      </main>
    </div>
  );
}
