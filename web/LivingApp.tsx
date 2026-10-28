import { useState, type FormEvent } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  Check,
  ChevronRight,
  Clock3,
  FileCheck2,
  HeartHandshake,
  Leaf,
  ListChecks,
  LockKeyhole,
  MapPin,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Sprout,
  UsersRound,
  X,
} from "lucide-react";
import {
  Avatar,
  Brand,
  ErrorBanner,
  Json,
  OwnerLink,
  PairForm,
  Tag,
  Wait,
  clock,
  list,
  ownerId,
  payload,
  person,
  readable,
  stamp,
  useLiving,
  type Data,
  type LivingService,
  type Provider,
  minutes,
} from "./living";
const copy: Record<string, string> = {
  INITIAL: "A little coordination. A lot of care.",
  COLLECTING: "Let’s hear what works for each person.",
  NEEDS_HELP: "One piece needs a helping hand.",
  AWAITING_CONSENT: "A way forward, for everyone to review.",
  READY: "The next arrangement is ready to apply.",
  ACTIVE: "There’s a plan around the person.",
  RECOVERING: "Let’s check what happened.",
  HISTORICAL: "This is the last observed arrangement.",
  REVIEW_GOAL: "First, let’s make sure the details are right.",
};
export default function LivingApp() {
  const service = useLiving("broker"),
    { state: s, busy, stale } = service;
  const [tab, setTab] = useState("arrangement"),
    [newGoal, setNewGoal] = useState(false),
    [samplePolicy, setSamplePolicy] = useState(false),
    [provider, setProvider] = useState<Provider>("local");
  const owners = list(s?.owners),
    goal = s?.goal,
    pending = s?.pending,
    agreement = s?.agreement;
  async function start() {
    if (!service.paired && !(await service.pair(true))) return;
    await service.act(
      "Preparing the fictional starting arrangement",
      "/api/v2/sample",
      { enable_policy: samplePolicy },
    );
  }
  const planning = ["RUNNING", "PLANNING", "PENDING"].includes(
    s?.planning?.status,
  );
  const hasWork = !!goal;
  return (
    <div className="cg-app">
      <a className="cg-skip" href="#main">
        Skip to arrangement
      </a>
      <header className="cg-header">
        <a href="/" aria-label="Common Ground home">
          <Brand />
        </a>
        <nav aria-label="Main navigation">
          <button
            className={tab === "arrangement" ? "selected" : ""}
            onClick={() => setTab("arrangement")}
          >
            <HeartHandshake size={17} />
            Our arrangement
          </button>
          <button
            className={tab === "record" ? "selected" : ""}
            onClick={() => setTab("record")}
          >
            <FileCheck2 size={17} />
            The record
          </button>
        </nav>
        <div className="cg-header-end">
          <Tag tone="sample">Fictional care circle</Tag>
          {service.paired ? (
            <button
              className="cg-icon"
              title="Lock workspace"
              aria-label="Lock workspace"
              onClick={service.lock}
            >
              <LockKeyhole size={17} />
            </button>
          ) : null}
        </div>
      </header>
      <main id="main" className="cg-main">
        <ErrorBanner service={service} />
        {service.paired && !s ? (
          <section className="cg-empty" role="status" aria-live="polite">
            <h1>
              {service.error
                ? "Your arrangement is unavailable."
                : "Opening your arrangement…"}
            </h1>
            <p>
              {service.error
                ? "Reconnect using the notice above to observe the existing arrangement."
                : "Restoring this service’s current shared view."}
            </p>
          </section>
        ) : !s ? (
          <>
            <section className="cg-landing">
              <div className="cg-landing-copy">
                <p className="cg-eyebrow">
                  <span /> PRIVATE AGENTS. SHARED CARE.
                </p>
                <h1>
                  Life changes.
                  <br />
                  Care can <em>keep up.</em>
                </h1>
                <p className="cg-lede">
                  An appointment. A lift home. Someone there at the door. Bring
                  the pieces together, while each person keeps their own say.
                </p>
                <div className="cg-actions">
                  <button
                    className="cg-button"
                    disabled={!!busy}
                    onClick={() => void start()}
                  >
                    Try the fictional care circle <ArrowRight size={18} />
                  </button>
                  <a className="cg-text" href="?recorded=1">
                    Inspect a recorded agreement <ArrowUpRight size={15} />
                  </a>
                </div>
                <p className="cg-caption">
                  An authored sample with Asha, Ravi, Leena and Dev.
                  <br />
                  Starting decisions are fictional. New decisions happen in each
                  owner’s space.
                </p>
                <details className="cg-pair cg-sample-options">
                  <summary>
                    Optional authored sample policy · off by default
                  </summary>
                  <label className="cg-checkbox" style={{ marginTop: 12 }}>
                    <input
                      type="checkbox"
                      checked={samplePolicy}
                      onChange={(e) => setSamplePolicy(e.target.checked)}
                    />
                    <span>
                      Also seed a reviewed fictional carry-forward policy for
                      this sample. It permits fresh attestation only if a
                      person’s own content, direct counterparts, recipients,
                      complete required coverage and cancellation scope remain
                      unchanged. New or changed parts always require exact
                      review. Each owner can revoke it in their private space.
                    </span>
                  </label>
                </details>
                <PairForm service={service} />
                {busy ? <Wait label={busy} /> : null}
              </div>
              <CareIllustration />
            </section>
            <div className="cg-principles">
              <div>
                <span>01</span>
                <strong>One shared picture.</strong>
                <p>See the responsibilities and handoffs together.</p>
              </div>
              <div>
                <span>02</span>
                <strong>Everyone has a say.</strong>
                <p>Each person reviews their own exact part.</p>
              </div>
              <div>
                <span>03</span>
                <strong>Only change what needs to.</strong>
                <p>Keep the commitments that still work.</p>
              </div>
            </div>
          </>
        ) : (
          <>
            {!service.paired ? (
              <div className="cg-notice warning">
                <LockKeyhole size={19} />
                <div>
                  <strong>
                    Re-enter this service to observe current decisions.
                  </strong>
                  <div className="cg-actions">
                    <button
                      className="cg-button secondary"
                      onClick={() => void service.pair(true)}
                    >
                      Re-enter fictional shared room
                    </button>
                    <PairForm service={service} />
                  </div>
                </div>
              </div>
            ) : null}
            <div className="cg-context">
              <span>
                <span className={stale ? "cg-dot amber" : "cg-dot"} />{" "}
                {stale
                  ? "Historical · reconnect to verify"
                  : "Shared coordination room"}
              </span>
              <span>
                Private reasons stay with their owner <LockKeyhole size={12} />
              </span>
            </div>
            <section className="cg-page-head">
              <div>
                <p className="cg-eyebrow">
                  THE PEOPLE AROUND{" "}
                  {goal?.subject?.toUpperCase() || "A SHARED GOAL"}
                </p>
                <h1>
                  {copy[stale ? "HISTORICAL" : s.status] ||
                    "Make room for what changes."}
                </h1>
                <p>
                  {goal?.title ||
                    "Start with a shared goal. Build an arrangement everyone can choose."}
                </p>
              </div>
              <button
                className="cg-button secondary"
                onClick={() => setNewGoal(!newGoal)}
              >
                <Plus size={17} />
                {newGoal ? "Close goal form" : "New shared goal"}
              </button>
            </section>
            {newGoal || s.draft ? (
              <GoalEditor service={service} close={() => setNewGoal(false)} />
            ) : null}
            {!hasWork ? (
              <div className="cg-empty">
                <Sprout size={38} />
                <h2>Every circle starts somewhere.</h2>
                <p>
                  Try the authored care arrangement or bring a new fictional
                  shared goal.
                </p>
                <button
                  className="cg-button"
                  disabled={!!busy}
                  onClick={() => void start()}
                >
                  Start the fictional arrangement <ArrowRight size={17} />
                </button>
              </div>
            ) : tab === "record" ? (
              <Record service={service} />
            ) : (
              <div className="cg-layout">
                <div className="cg-main-column">
                  <section
                    className="cg-paper"
                    aria-labelledby="arrangement-title"
                  >
                    <div className="cg-sheet-top">
                      <span className="cg-eyebrow">OUR LIVING ARRANGEMENT</span>
                      <span className="cg-revision">
                        REVISION{" "}
                        {agreement?.revision || pending?.revision || "—"}
                      </span>
                    </div>
                    <div className="cg-sheet-heading">
                      <h2 id="arrangement-title">{goal.title}</h2>
                      <span className="cg-seal">
                        <HeartHandshake size={29} />
                      </span>
                    </div>
                    <div className="cg-meta">
                      <span>
                        <CalendarDays size={15} />
                        {list(goal.tasks)[0]?.date || "Date needs review"}
                      </span>
                      <span>
                        <MapPin size={15} />
                        {goal.timezone}
                      </span>
                    </div>
                    <div
                      className={`cg-status-band ${s.status === "NEEDS_HELP" ? "attention" : ""}`}
                    >
                      <span className="cg-status-icon">
                        {s.status === "ACTIVE" && !stale ? (
                          <Check size={18} />
                        ) : (
                          <Leaf size={18} />
                        )}
                      </span>
                      <div>
                        <strong>
                          {readable(stale ? "HISTORICAL" : s.status)}
                        </strong>
                        <p>
                          {goal.confirmed_by === "authored-fictional-sample"
                            ? "Authored fictional starting decisions; later changes require fresh owner authority."
                            : "A fictional reviewed goal. Each owner chooses their exact responsibilities."}
                        </p>
                      </div>
                    </div>
                    <div className="cg-section-label">
                      <h3>Who’s doing what</h3>
                      <span>
                        {pending
                          ? "Current arrangement & proposed changes"
                          : "Current arrangement"}
                      </span>
                    </div>
                    <Timeline
                      state={s}
                      stale={stale || s.status === "HISTORICAL"}
                    />
                    {!pending &&
                    agreement &&
                    ["RECOVERING", "HISTORICAL", "NEEDS_ATTENTION"].includes(
                      s.status,
                    ) ? (
                      <div className="cg-notice warning">
                        <RefreshCw size={18} />
                        <div>
                          <strong>
                            Read the current calendar effects before proceeding.
                          </strong>
                          <p>
                            Earlier observations may be historical. Reconcile
                            this exact revision to inspect what remains; edited
                            entries require owner review.
                          </p>
                          <button
                            className="cg-button secondary"
                            disabled={!!busy || stale}
                            onClick={() =>
                              void service.act(
                                "Reading current calendar observations",
                                "/api/v2/reconcile",
                                {
                                  agreement_id: agreement.agreement_id,
                                  revision: agreement.revision,
                                },
                              )
                            }
                          >
                            Reconcile this arrangement
                          </button>
                        </div>
                      </div>
                    ) : null}
                    <div className="cg-sheet-note">
                      <ShieldCheck size={17} />
                      <p>
                        Calendar verification confirms an entry was observed. It
                        does not confirm a person arrived or a handoff happened.
                      </p>
                    </div>
                  </section>
                  {s.status === "NEEDS_HELP" ? (
                    <div className="cg-help-card">
                      <span className="cg-round-icon">
                        <UsersRound size={24} />
                      </span>
                      <div>
                        <p className="cg-eyebrow">A PERSON’S HELP IS NEEDED</p>
                        <h2>A required part is still uncovered.</h2>
                        <p>
                          The current offers don’t cover every required piece.
                          Someone can accept a new invitation in their private
                          space. A refusal stays a refusal; no one is assigned a
                          capability they have excluded.
                        </p>
                        <p className="cg-caption">
                          A received request still needs a reviewed owner offer
                          and exact approval.
                        </p>
                        {list(s.questions)
                          .filter(
                            (q) =>
                              q.goal_id === goal?.goal_id &&
                              (!s.disruption_id ||
                                q.disruption_id === s.disruption_id),
                          )
                          .map((q, i) => (
                            <div className="cg-request" key={q.request_id || i}>
                              <strong>
                                {person(q.owner_id)} ·{" "}
                                {q.label ||
                                  list(goal?.tasks).find(
                                    (t) => t.task_id === q.task_id,
                                  )?.label ||
                                  "Help request"}
                              </strong>
                              <span>
                                {q.status === "accepted"
                                  ? "Request received"
                                  : readable(q.status || "requested")}
                              </span>
                            </div>
                          ))}
                      </div>
                    </div>
                  ) : null}
                  <section className="cg-next-step">
                    <div className="cg-next-icon">
                      <Sparkles size={22} />
                    </div>
                    <div>
                      <p className="cg-eyebrow">WHEN SOMETHING CHANGES</p>
                      <h2>
                        {pending
                          ? "Review the changes, keep what works."
                          : "Find the next workable arrangement."}
                      </h2>
                      <p>
                        {pending
                          ? "The proposal below names every changed responsibility and direct handoff. Each affected owner decides in their private space."
                          : "Use the current reviewed offers to explore a plan. A proposal only becomes an agreement after the required owner decisions."}
                      </p>
                      <div className="cg-actions">
                        <label className="cg-inline-label">
                          Planning route
                          <select
                            aria-label="Planning route"
                            value={provider}
                            onChange={(e) =>
                              setProvider(e.target.value as Provider)
                            }
                          >
                            <option value="local">
                              Local structured solver
                            </option>
                            <option value="fireworks">
                              Fireworks inference
                            </option>
                            <option value="nebius">Nebius inference</option>
                          </select>
                        </label>
                        <button
                          className="cg-button"
                          disabled={!!busy || stale || planning}
                          onClick={() =>
                            void service.act(
                              "Finding a reviewed arrangement",
                              "/api/v2/plan",
                              { provider, expected_revision: s.revision },
                            )
                          }
                        >
                          {provider === "local"
                            ? "Find a structured arrangement"
                            : "Ask " + person(provider) + " to plan"}
                          <ArrowRight size={17} />
                        </button>
                      </div>
                      <p className="cg-caption">
                        {provider === "local"
                          ? "Local constraint solving. No model inference or provider transmission."
                          : `The shared request and current public offers go to ${person(provider)}. Each included owner must release a current grant for this exact provider. No fallback route.`}
                      </p>
                      {planning ? (
                        <div className="cg-planning">
                          <Wait
                            label={`${person(s.planning.provider || provider)} planning`}
                            startedAt={s.planning.started_at}
                          />
                          <button
                            className="cg-text"
                            onClick={() =>
                              void service.act(
                                "Cancelling the planning request",
                                "/api/v2/cancel",
                                { expected_revision: s.revision },
                              )
                            }
                          >
                            <X size={15} />
                            Cancel planning request
                          </button>
                        </div>
                      ) : busy ? (
                        <Wait label={busy} />
                      ) : null}
                    </div>
                  </section>
                  {pending ? <Delta service={service} /> : null}
                  {s.status === "ACTIVE" && s.agreement?.delta ? (
                    <section className="cg-paper cg-effects-summary">
                      <p className="cg-eyebrow">
                        ACTUAL SELECTIVE DELTA IN THIS REVISION
                      </p>
                      <h3 style={{ marginTop: 12 }}>
                        Preserved parts keep their calendar identity.
                      </h3>
                      <p className="cg-caption">
                        {(s.agreement.delta.retained || []).length} retained
                        commitments ·{" "}
                        {
                          (s.agreement.delta.calendar_mutations || []).filter(
                            (m: Data) => m.kind === "insert",
                          ).length
                        }{" "}
                        requested inserts ·{" "}
                        {
                          (s.agreement.delta.calendar_mutations || []).filter(
                            (m: Data) => m.kind === "update",
                          ).length
                        }{" "}
                        requested updates ·{" "}
                        {
                          (s.agreement.delta.calendar_mutations || []).filter(
                            (m: Data) => m.kind === "delete",
                          ).length
                        }{" "}
                        requested deletes. Observation outcomes remain in the
                        record.
                      </p>
                      <Json
                        value={s.agreement.delta}
                        label="Inspect persisted delta and event identities"
                      />
                    </section>
                  ) : null}
                  <section className="cg-observations">
                    <div>
                      <Clock3 size={18} />
                      <strong>Last observed</strong>
                      <span>{stamp(s.observed_at)}</span>
                    </div>
                    <p>
                      Offered help → owner commitment → verified calendar entry
                      → reported handoff. Each is a separate fact.
                    </p>
                  </section>
                </div>
                <aside className="cg-aside">
                  <section className="cg-circle">
                    <p className="cg-eyebrow">
                      A SMALL CIRCLE, EACH WITH A SAY
                    </p>
                    <h2>
                      The people around
                      <br />
                      {goal.subject || "this goal"}.
                    </h2>
                    <p>
                      Private spaces. Independent decisions. Open one to play
                      that person’s role in this fictional sample.
                    </p>
                    {owners.map((o) => (
                      <div key={ownerId(o)}>
                        <OwnerLink owner={o} />
                        <p className="cg-owner-status">
                          {stale || s.status === "HISTORICAL" ? (
                            "Historical owner state · reconnect"
                          ) : list(s.approval_status).find(
                              (a) => a.owner_id === ownerId(o),
                            )?.status === "approved" ? (
                            <>
                              <Check size={13} />{" "}
                              {list(s.approval_status).find(
                                (a) => a.owner_id === ownerId(o),
                              )?.basis === "standing-policy"
                                ? "Fresh standing-policy attestation"
                                : "Exact revision approved"}
                            </>
                          ) : list(s.offers).some(
                              (a) =>
                                ownerId(payload(a)) === ownerId(o) ||
                                ownerId(a) === ownerId(o),
                            ) ? (
                            "Released offer recorded"
                          ) : (
                            "Owner decides what to offer"
                          )}
                        </p>
                      </div>
                    ))}
                    <div className="cg-private-note">
                      <LockKeyhole size={17} />
                      <p>
                        The shared room receives reviewed offers and decisions.
                        Private memories and personal reasons stay in each
                        owner’s service.
                      </p>
                    </div>
                  </section>
                  <section className="cg-small-card">
                    <Sprout size={24} />
                    <h3>A change doesn’t have to undo the whole day.</h3>
                    <p>
                      Withdraw one responsibility. Keep the ones that still
                      work. Review a new handoff, even when the clock stays the
                      same.
                    </p>
                    <a className="cg-text" href="?legacy=1">
                      Recorded / legacy workflow <ArrowUpRight size={14} />
                    </a>
                  </section>
                </aside>
              </div>
            )}
          </>
        )}
        <footer className="cg-footer">
          <Brand />
          <span>Made for the spaces between people.</span>
          <a href="?legacy=1">
            Recorded / legacy workflow <ArrowUpRight size={13} />
          </a>
        </footer>
      </main>
    </div>
  );
}
function CareIllustration() {
  return (
    <div
      className="cg-art"
      aria-label="An illustrated arrangement of care responsibilities"
    >
      <div className="cg-art-orbit" />
      <div className="cg-art-flower">
        <Sprout size={76} strokeWidth={1.2} />
      </div>
      <div className="cg-art-note note-one">
        <Avatar id="ravi" />
        <div>
          <small>Ravi’s part</small>
          <strong>A lift to the clinic.</strong>
        </div>
        <Check size={16} />
      </div>
      <div className="cg-art-note note-two">
        <Avatar id="asha" />
        <div>
          <small>Asha’s part</small>
          <strong>A familiar face at home.</strong>
        </div>
        <Check size={16} />
      </div>
      <div className="cg-art-note note-three">
        <HeartHandshake size={23} />
        <div>
          <small>Our arrangement</small>
          <strong>Room for life to change.</strong>
        </div>
      </div>
      <span className="cg-art-caption">A little more together.</span>
      <span className="cg-art-star one">✳</span>
      <span className="cg-art-star two">✳</span>
    </div>
  );
}
function Timeline({ state: s, stale }: { state: Data; stale: boolean }) {
  const commitments = list(s.commitments),
    tasks = list(s.goal?.tasks);
  return (
    <ol className="cg-timeline">
      {tasks.map((t, i) => {
        const candidates = commitments.filter((c) => c.task_id === t.task_id),
          c =
            candidates.find(
              (c) => !["withdrawn", "pending"].includes(c.status),
            ) || candidates[0],
          uncovered = !c || c.status === "withdrawn";
        const proposed = list(s.pending?.commitments).find(
          (p) => p.task_id === t.task_id,
        );
        return (
          <li key={t.task_id} className={uncovered ? "uncovered" : ""}>
            <div className="cg-time">
              <strong>{clock(c?.start ?? t.earliest)}</strong>
              <span>
                {clock(
                  c?.end ??
                    (typeof t.earliest === "number" &&
                    typeof t.duration === "number"
                      ? t.earliest + t.duration
                      : undefined),
                )}
              </span>
            </div>
            <span className={`cg-timeline-node ${c?.owner_id || ""}`}>
              {uncovered ? "?" : i + 1}
            </span>
            <div className="cg-task">
              <div className="cg-task-head">
                <h3>{t.label}</h3>
                {!uncovered ? (
                  <span className="cg-assigned">
                    <Avatar id={c.owner_id} />
                    {person(c.owner_id)}
                  </span>
                ) : (
                  <Tag tone="warning">Needs a person</Tag>
                )}
              </div>
              <p>
                {t.start_location}{" "}
                {t.start_location !== t.end_location ? (
                  <>→ {t.end_location}</>
                ) : null}
                <span> · </span>
                {t.duration} min
              </p>
              <div className="cg-task-state">
                {uncovered ? (
                  <span className="cg-amber">
                    {c
                      ? `${person(c.owner_id)} withdrew this part`
                      : "No current commitment"}
                  </span>
                ) : (
                  <>
                    <span>
                      <Check size={12} />
                      {c.status === "pending" ? "Proposed only" : "Committed"}
                    </span>
                    <span
                      className={
                        c.calendar_status === "VERIFIED" && !stale
                          ? "cg-green"
                          : ""
                      }
                    >
                      {c.calendar_status === "VERIFIED" && !stale ? (
                        <Check size={12} />
                      ) : (
                        <Clock3 size={12} />
                      )}
                      Calendar:{" "}
                      {stale
                        ? "historical observation"
                        : readable(c.calendar_status || "not verified")}
                    </span>
                  </>
                )}
              </div>
              {proposed && (uncovered || proposed.owner_id !== c?.owner_id) ? (
                <p className="cg-proposed">
                  <ArrowRight size={13} /> Proposed: {person(proposed.owner_id)}{" "}
                  · {clock(proposed.start)}–{clock(proposed.end)} · awaiting
                  owner review
                </p>
              ) : null}
              {c?.event_id ? (
                <details className="cg-event-detail">
                  <summary>Calendar identity</summary>
                  <code>{c.event_id}</code>
                  <small>Observation ETag {c.etag || "not available"}</small>
                </details>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
function Delta({ service }: { service: LivingService }) {
  const s = service.state!,
    p = s.pending,
    d = p.delta || {},
    approvals = list(s.approval_status);
  return (
    <section className="cg-paper cg-delta">
      <div className="cg-sheet-top">
        <span className="cg-eyebrow">PROPOSED AMENDMENT</span>
        <Tag>Revision {p.revision}</Tag>
      </div>
      <h2>
        A smaller change.
        <br />A fresh decision.
      </h2>
      <p>
        {p.explanation ||
          "Only the necessary responsibilities and calendar effects change."}
      </p>
      <div className="cg-delta-counts">
        {["retained", "changed", "new", "withdrawn"].map((k) => (
          <div key={k}>
            <strong>{Array.isArray(d[k]) ? d[k].length : "—"}</strong>
            <span>{readable(k)}</span>
          </div>
        ))}
      </div>
      <ul className="cg-review-list">
        {list(p.commitments).map((c) => (
          <li key={c.commitment_id}>
            <Avatar id={c.owner_id} />
            <div>
              <strong>
                {person(c.owner_id)} · {c.label}
              </strong>
              <span>
                {clock(c.start)}–{clock(c.end)} · {c.date}
              </span>
              {list(c.dependencies).map((dep, i) => (
                <small key={i}>
                  Handoff link: {person(dep.owner_id)} · {dep.task_id} ·{" "}
                  {clock(dep.start)}–{clock(dep.end)}
                </small>
              ))}
            </div>
            <Tag tone={list(d.retained).length ? "" : ""}>
              {(d.retained || []).includes(c.commitment_id)
                ? "Retained"
                : "Review exact part"}
            </Tag>
          </li>
        ))}
      </ul>
      <h3>Who decides on this revision</h3>
      {approvals.map((a) => (
        <div className="cg-approval-row" key={a.owner_id}>
          <span>{person(a.owner_id)}</span>
          <span>
            {service.stale || s.status === "HISTORICAL"
              ? "Historical owner decision"
              : a.status === "approved"
                ? a.basis === "standing-policy"
                  ? "Fresh policy attestation"
                  : "Exact review approved"
                : "Fresh owner review needed"}
          </span>
        </div>
      ))}
      <p className="cg-caption">
        A changed direct counterpart requires fresh exact review, even if the
        person’s own time and event stay the same. Standing policies are off
        unless an owner explicitly enables one.
      </p>
      <div className="cg-actions">
        <button
          className="cg-button"
          disabled={!!service.busy || service.stale || s.status !== "READY"}
          onClick={() =>
            void service.act(
              "Applying only the approved calendar changes",
              "/api/v2/execute",
              { agreement_id: p.agreement_id, revision: p.revision },
            )
          }
        >
          Apply approved changes <ArrowRight size={17} />
        </button>
        <button
          className="cg-button secondary"
          disabled={!!service.busy || service.stale}
          onClick={() =>
            void service.act(
              "Reading back exact calendar effects",
              "/api/v2/reconcile",
              { agreement_id: p.agreement_id, revision: p.revision },
            )
          }
        >
          <RefreshCw size={15} />
          Reconcile observations
        </button>
      </div>
      <Json value={d} label="Inspect exact selective calendar mutations" />
    </section>
  );
}
function Record({ service }: { service: LivingService }) {
  const s = service.state!;
  async function download(verifier = false) {
    try {
      const { value } = await service.request(
        verifier ? "/api/v2/verifier" : "/api/v2/evidence",
        undefined,
        undefined,
        verifier,
      );
      const u = URL.createObjectURL(
        verifier
          ? value
          : new Blob([JSON.stringify(value, null, 2)], {
              type: "application/json",
            }),
      );
      const a = document.createElement("a");
      a.href = u;
      a.download = verifier
        ? "verify_living_evidence.py"
        : "common-ground-living-evidence.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(u), 1000);
    } catch (e) {
      service.setError(e instanceof Error ? e.message : "Evidence unavailable");
    }
  }
  return (
    <div className="cg-record">
      <section className="cg-paper">
        <p className="cg-eyebrow">THE PORTABLE RECORD</p>
        <h2>Decisions, with their receipts.</h2>
        <p>
          Persisted observations from this fictional installation. An offer,
          consent, calendar readback and reported completion mean different
          things.
        </p>
        <div className="cg-actions">
          <button
            className="cg-button secondary"
            onClick={() => void download()}
          >
            <ArrowDownToLine size={16} />
            Download sanitized record
          </button>
          <button
            className="cg-button secondary"
            onClick={() => void download(true)}
          >
            <ArrowDownToLine size={16} />
            Download offline verifier
          </button>
        </div>
        <p className="cg-caption">
          Offline verifier needs Python, cryptography and rfc8785; no keys or
          database.
        </p>
        <h3>Calendar observations</h3>
        {list(s.receipts).length ? (
          list(s.receipts).map((r, i) => (
            <div className="cg-receipt" key={r.mutation_id || i}>
              <FileCheck2 size={18} />
              <div>
                <strong>
                  {r.owner_id ? `${person(r.owner_id)} · ` : ""}
                  {readable(r.status)}
                </strong>
                <p>{r.commitment_id || r.event_id}</p>
                <small>Verified {stamp(r.verified_at)}</small>
                {r.error ? <p>{r.error}</p> : null}
              </div>
            </div>
          ))
        ) : (
          <p>No v2 calendar readback receipts yet.</p>
        )}
        <h3>Planning attempts</h3>
        {list(s.model_runs).map((r, i) => (
          <Json
            key={r.receipt_id || i}
            value={r}
            label={`${person(r.provider)} · ${readable(r.status)} · ${stamp(r.started_at || r.created_at)}`}
          />
        ))}
        <Json value={s.history} label="Inspect persisted history" />
        <Json
          value={s.questions}
          label="Inspect invitation history across goals"
        />
        <Json value={s.agreement} label="Inspect current exact agreement" />
        <a className="cg-text" href="?legacy=1">
          Inspect recorded / legacy workflow <ArrowUpRight size={15} />
        </a>
      </section>
    </div>
  );
}
const blankTask = () => ({
  task_id: `task-${Math.random().toString(36).slice(2, 8)}`,
  label: "",
  capability: "visit",
  date: "",
  duration: null,
  earliest: null,
  latest: null,
  start_location: "",
  end_location: "",
  predecessors: [],
  required: true,
  subject: "",
  source_quote: "",
});
function GoalEditor({
  service,
  close,
}: {
  service: LivingService;
  close: () => void;
}) {
  const s = service.state!,
    [source, setSource] = useState(""),
    [provider, setProvider] = useState<Provider>("local"),
    [allow, setAllow] = useState(false),
    [draft, setDraft] = useState<Data | null>(null),
    [review, setReview] = useState(false);
  const remote = s.draft?.goal;
  const g = draft || remote;
  function update(k: string, v: any) {
    setDraft({ ...g, [k]: v });
  }
  function task(i: number, k: string, v: any) {
    const tasks = [...list(g?.tasks)];
    tasks[i] = { ...tasks[i], [k]: v };
    update("tasks", tasks);
  }
  async function parse(e: FormEvent) {
    e.preventDefault();
    if (provider === "local") {
      setDraft({
        schema_version: 2,
        goal_id: `goal-${crypto.randomUUID()}`,
        revision: 1,
        title: "",
        description: "",
        timezone: "Asia/Kolkata",
        participants: list(s.owners).map(ownerId),
        subject: "",
        source_text: source,
        tasks: [blankTask(), blankTask()],
        routes: [],
      });
      return;
    }
    await service.act(
      "Extracting a draft for your review",
      "/api/v2/goal/draft",
      { source_text: source, provider, allow_inference: allow },
    );
  }
  return (
    <section className="cg-paper cg-goal-form">
      <div className="cg-sheet-top">
        <p className="cg-eyebrow">A NEW FICTIONAL SHARED GOAL</p>
        <button className="cg-icon" aria-label="Close new goal" onClick={close}>
          <X size={18} />
        </button>
      </div>
      <h2>What would you like to bring together?</h2>
      <form onSubmit={parse}>
        <label>
          The shared request
          <textarea
            rows={3}
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              if (g) setDraft({ ...g, source_text: e.target.value });
              setReview(false);
            }}
            required
            placeholder="Describe the person, responsibilities, explicit dates, durations, locations and journeys…"
          />
        </label>
        <div className="cg-form-row">
          <label>
            How to create the draft
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as Provider)}
            >
              <option value="local">Write a structured goal myself</option>
              <option value="fireworks">
                Ask Fireworks to extract a draft
              </option>
              <option value="nebius">Ask Nebius to extract a draft</option>
            </select>
          </label>
          {provider !== "local" ? (
            <label className="cg-checkbox">
              <input
                type="checkbox"
                checked={allow}
                onChange={(e) => setAllow(e.target.checked)}
              />
              <span>
                I allow this shared request to be sent to {person(provider)} for
                draft extraction. Private owner memory is excluded.
              </span>
            </label>
          ) : null}
          <button
            className="cg-button secondary"
            disabled={!!service.busy || (provider !== "local" && !allow)}
          >
            {provider === "local"
              ? "Open structured review"
              : "Extract draft for review"}
            <ChevronRight size={15} />
          </button>
        </div>
      </form>
      {s.draft?.status && !g ? (
        <div className="cg-notice">
          <ListChecks size={20} />
          <div>
            <strong>{readable(s.draft.status)}</strong>
            {list(s.draft.questions).map((q, i) => (
              <p key={i}>
                {typeof q === "string" ? q : q.question || JSON.stringify(q)}
              </p>
            ))}
          </div>
        </div>
      ) : null}
      {g ? (
        <div className="cg-goal-review">
          <p className="cg-eyebrow">REVIEW EVERY FACT BEFORE CONFIRMING</p>
          <p>
            A draft establishes no facts and authorizes no owner. Fill every
            date, duration, place and directional journey. Latest means the task
            must <strong>end</strong> by that time.
          </p>
          <div className="cg-form-row">
            <label>
              Goal title
              <input
                value={g.title || ""}
                onChange={(e) => update("title", e.target.value)}
              />
            </label>
            <label>
              Person / subject
              <input
                value={g.subject || ""}
                onChange={(e) => update("subject", e.target.value)}
              />
            </label>
            <label>
              Timezone
              <input
                value={g.timezone || ""}
                onChange={(e) => update("timezone", e.target.value)}
              />
            </label>
          </div>
          <label>
            Description
            <input
              value={g.description || ""}
              onChange={(e) => update("description", e.target.value)}
            />
          </label>
          <fieldset className="cg-members">
            <legend>Registered participants · choose 2–6</legend>
            {list(s.owners).map((o) => (
              <label className="cg-checkbox" key={ownerId(o)}>
                <input
                  type="checkbox"
                  checked={(g.participants || []).includes(ownerId(o))}
                  onChange={(e) =>
                    update(
                      "participants",
                      e.target.checked
                        ? [...g.participants, ownerId(o)]
                        : g.participants.filter(
                            (id: string) => id !== ownerId(o),
                          ),
                    )
                  }
                />
                {o.name}
              </label>
            ))}
          </fieldset>
          {list(g.tasks).map((t, i) => (
            <fieldset className="cg-task-editor" key={t.task_id}>
              <legend>Responsibility {i + 1}</legend>
              <div className="cg-form-row">
                <label>
                  Label
                  <input
                    value={t.label}
                    onChange={(e) => task(i, "label", e.target.value)}
                  />
                </label>
                <label>
                  Capability
                  <select
                    value={t.capability}
                    onChange={(e) => task(i, "capability", e.target.value)}
                  >
                    {[
                      "preparation",
                      "driving",
                      "accompaniment",
                      "handoff",
                      "meal",
                      "visit",
                    ].map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Explicit date
                  <input
                    type="date"
                    value={t.date}
                    onChange={(e) => task(i, "date", e.target.value)}
                  />
                </label>
              </div>
              <div className="cg-form-row">
                <label>
                  Duration in minutes
                  <input
                    type="number"
                    min={1}
                    value={t.duration || ""}
                    onChange={(e) =>
                      task(i, "duration", Number(e.target.value))
                    }
                  />
                </label>
                <label>
                  Earliest start
                  <input
                    type="time"
                    value={
                      typeof t.earliest === "number" ? clock(t.earliest) : ""
                    }
                    onChange={(e) =>
                      task(i, "earliest", minutes(e.target.value))
                    }
                  />
                </label>
                <label>
                  Latest end
                  <input
                    type="time"
                    value={typeof t.latest === "number" ? clock(t.latest) : ""}
                    onChange={(e) => task(i, "latest", minutes(e.target.value))}
                  />
                </label>
              </div>
              <div className="cg-form-row">
                <label>
                  Start place
                  <input
                    value={t.start_location}
                    onChange={(e) => task(i, "start_location", e.target.value)}
                  />
                </label>
                <label>
                  End place
                  <input
                    value={t.end_location}
                    onChange={(e) => task(i, "end_location", e.target.value)}
                  />
                </label>
                <label>
                  Subject
                  <input
                    value={t.subject}
                    onChange={(e) => task(i, "subject", e.target.value)}
                  />
                </label>
              </div>
              <fieldset className="cg-dependency-choices">
                <legend>After these responsibilities</legend>
                <p className="cg-caption">
                  Choose the responsibilities that must finish before this one
                  starts.
                </p>
                {list(g.tasks)
                  .filter((other) => other.task_id !== t.task_id)
                  .map((other) => (
                    <label className="cg-checkbox" key={other.task_id}>
                      <input
                        type="checkbox"
                        checked={(t.predecessors || []).includes(other.task_id)}
                        onChange={(e) =>
                          task(
                            i,
                            "predecessors",
                            e.target.checked
                              ? [...(t.predecessors || []), other.task_id]
                              : (t.predecessors || []).filter(
                                  (id: string) => id !== other.task_id,
                                ),
                          )
                        }
                      />
                      {other.label ||
                        `Responsibility ${list(g.tasks).findIndex((candidate) => candidate.task_id === other.task_id) + 1} · add a label`}
                    </label>
                  ))}
              </fieldset>
              <label>
                Exact supporting quote from the shared request
                <input
                  value={t.source_quote}
                  onChange={(e) => task(i, "source_quote", e.target.value)}
                />
              </label>
              <div className="cg-actions">
                <label className="cg-checkbox">
                  <input
                    type="checkbox"
                    checked={t.required}
                    onChange={(e) => task(i, "required", e.target.checked)}
                  />
                  Required responsibility
                </label>
                <button
                  className="cg-text"
                  onClick={() =>
                    update(
                      "tasks",
                      g.tasks
                        .filter((_: Data, n: number) => n !== i)
                        .map((remaining: Data) => ({
                          ...remaining,
                          predecessors: (remaining.predecessors || []).filter(
                            (id: string) => id !== t.task_id,
                          ),
                        })),
                    )
                  }
                >
                  Remove responsibility
                </button>
              </div>
            </fieldset>
          ))}
          <button
            className="cg-text"
            disabled={g.tasks.length >= 12}
            onClick={() => update("tasks", [...g.tasks, blankTask()])}
          >
            <Plus size={15} />
            Add a responsibility
          </button>
          <h3>Confirmed directional routes</h3>
          <p>
            Distinct places require explicit travel time. Same-place travel is
            zero. Reverse journeys need their own route.
          </p>
          {list(g.routes).map((r, i) => (
            <div className="cg-form-row cg-route" key={i}>
              {["from_location", "to_location", "duration", "source_quote"].map(
                (k) => (
                  <label key={k}>
                    {readable(k)}
                    <input
                      type={k === "duration" ? "number" : "text"}
                      value={r[k]}
                      onChange={(e) => {
                        const routes = [...g.routes];
                        routes[i] = {
                          ...r,
                          [k]:
                            k === "duration"
                              ? Number(e.target.value)
                              : e.target.value,
                        };
                        update("routes", routes);
                      }}
                    />
                  </label>
                ),
              )}
              <button
                className="cg-icon"
                aria-label={`Remove route ${i + 1}`}
                onClick={() =>
                  update(
                    "routes",
                    g.routes.filter((_: Data, n: number) => n !== i),
                  )
                }
              >
                <X size={16} />
              </button>
            </div>
          ))}
          <button
            className="cg-text"
            onClick={() =>
              update("routes", [
                ...(g.routes || []),
                {
                  from_location: "",
                  to_location: "",
                  duration: "",
                  source_quote: "",
                },
              ])
            }
          >
            <Plus size={15} />
            Add a confirmed route
          </button>
          <label className="cg-checkbox cg-review-confirm">
            <input
              type="checkbox"
              checked={review}
              onChange={(e) => setReview(e.target.checked)}
            />
            <span>
              I reviewed this complete task graph, facts, source quotes and
              routes. This confirms the shared goal; each owner still chooses
              their own part.
            </span>
          </label>
          <button
            className="cg-button"
            disabled={!review || !!service.busy || service.stale}
            onClick={async () => {
              if (
                await service.act(
                  "Confirming the reviewed shared goal",
                  "/api/v2/goal/confirm",
                  {
                    goal: {
                      ...g,
                      source_text: g.source_text || source,
                      confirmed_at: new Date().toISOString(),
                      confirmed_by: "coordinator-reviewed-form",
                    },
                    expected_revision: s.revision,
                  },
                )
              ) {
                setDraft(null);
                close();
              }
            }}
          >
            Confirm reviewed goal <Check size={17} />
          </button>
        </div>
      ) : null}
    </section>
  );
}
