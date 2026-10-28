import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  Check,
  ChevronDown,
  CircleHelp,
  ClipboardCheck,
  Clock3,
  FileCheck2,
  Fingerprint,
  Flower2,
  GitBranch,
  HeartHandshake,
  LayoutList,
  Link2,
  ListChecks,
  LoaderCircle,
  LockKeyhole,
  MapPin,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Undo2,
  UsersRound,
} from "lucide-react";
import {
  Avatar,
  ErrorNotice,
  JsonDetails,
  Loading,
  Mark,
  names,
  Pairing,
  Pill,
  short,
  Status,
  time,
  useService,
  words,
} from "./ui";
import type {
  BrokerState,
  Envelope,
  Owner,
  OwnerId,
  ReleasePayload,
} from "./types";

const statusCopy: Record<string, string> = {
  COLLECTING: "A good plan starts with everyone’s say.",
  PROPOSED: "A possible afternoon, ready for your review.",
  AWAITING_APPROVAL: "The plan is here. Each person decides.",
  READY: "Everyone has agreed to this exact version.",
  PREPARED: "Everyone has agreed. Ready to make it happen.",
  APPLYING: "Adding each person’s part to their local calendar.",
  VERIFYING: "Checking the calendar entries, one by one.",
  ACTIVE: "The responsibilities are agreed and calendar effects verified.",
  REPLAN_REQUIRED: "Something changed. Let’s find the next workable plan.",
  NEEDS_ATTENTION: "Some calendar effects need a person’s attention.",
  RECOVERING: "Checking what happened before taking the next step.",
  COMPENSATED: "Applied calendar entries have been safely removed.",
};
function OwnerLink({
  owner,
  label = "Open local agent",
}: {
  owner: Owner;
  label?: string;
}) {
  return (
    <a
      className="owner-link"
      href={owner.url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {label}
      <ArrowUpRight size={15} />
      <span className="sr-only">
        {" "}
        for {owner.name}, opens a separate local service
      </span>
    </a>
  );
}
function App() {
  const service = useService<BrokerState>("broker");
  const [tab, setTab] = useState<"agreement" | "sharing" | "evidence">(
    "agreement",
  );
  const [textView, setTextView] = useState(false);
  const [exporting, setExporting] = useState("");
  const [confirm, setConfirm] = useState<"compensate" | "new-round" | null>(
    null,
  );
  const { state: s, client, busy, act, error, setError } = service;
  useEffect(() => {
    const target = document.getElementById(`${tab}-title`);
    if (!target) return;
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
    document
      .getElementById("main")
      ?.scrollIntoView({ block: "start", behavior: "auto" });
  }, [tab]);
  if (!service.paired)
    return (
      <Pairing kind="broker" pair={service.pair} error={error} busy={busy} />
    );
  if (!s)
    return error ? (
      <div className="loading">
        <Mark />
        <h1>The shared room is offline.</h1>
        <ErrorNotice message={error} onRetry={() => void service.refresh()} />
      </div>
    ) : (
      <Loading />
    );
  const p = s.proposal;
  const releases = s.offers.filter(
    (o) => Date.parse(o.body.expires_at) > Date.now(),
  );
  const currentApproval = (id: OwnerId) => {
    const release = releases.find((release) => release.body.issuer === id);
    const ref = p?.offer_refs.find((ref) => ref.owner_id === id);
    if (
      !release ||
      !ref ||
      ref.offer_id !== release.body.payload.offer.offer_id ||
      ref.revision !== release.body.payload.offer.revision ||
      ref.constraint_revision !==
        release.body.payload.offer.constraint_revision ||
      ref.consent_revision !== release.body.consent_revision ||
      p?.goal_revision !== release.body.payload.goal_revision
    )
      return undefined;
    return s.approvals.find(
      (a) =>
        a.body.issuer === id &&
        a.body.payload.proposal_id === p?.proposal_id &&
        a.body.payload.version === p?.version &&
        a.body.payload.proposal_digest === s.proposal_digest &&
        a.body.payload.manifest_digest === s.manifest_digest &&
        a.body.consent_revision === release.body.consent_revision &&
        a.body.payload.constraint_revision ===
          p?.offer_refs.find((ref) => ref.owner_id === id)
            ?.constraint_revision &&
        Date.parse(a.body.payload.execution_not_after) > Date.now() &&
        Date.parse(a.body.expires_at) > Date.now(),
    );
  };
  const requiredOwners = s.owners.filter((owner) =>
    p?.actions.some((action) => action.owner_id === owner.id),
  );
  const approvals = requiredOwners.filter((o) => currentApproval(o.id)).length;
  const allInference =
    releases.length > 0 &&
    releases.every((r) =>
      r.body.payload.recipients.inference.includes("fireworks"),
    );
  const someOffers = releases.length > 0;
  const inferenceBlocked = s.owners.filter((owner) =>
    releases.some(
      (release) =>
        release.body.issuer === owner.id &&
        !release.body.payload.recipients.inference.includes("fireworks"),
    ),
  );
  const allOffers = s.owners.every((o) =>
    releases.some((r) => r.body.issuer === o.id),
  );
  const planning =
    s.planning.status === "RUNNING" || s.planning.status === "PLANNING";
  const actions = s.actions.length ? s.actions : p?.actions || [];
  const verified = actions.filter((a) => a.status === "VERIFIED").length;
  const hasEffects = actions.some((a) =>
    ["VERIFIED", "AMBIGUOUS", "NEEDS_ATTENTION", "PAUSED"].includes(
      a.status || "",
    ),
  );
  const executionHeading: Record<string, string> = {
    ACTIVE: "Everyone knows their part.",
    NEEDS_ATTENTION: "A calendar change needs you.",
    RECOVERING: "Checking what really happened.",
    VERIFYING: "Checking every calendar effect.",
    APPLYING: "Making each part real.",
    REPLAN_REQUIRED: "A change needs a fresh agreement.",
    COMPENSATED: "Ready for the next plan.",
  };
  const needsReconcile = [
    "RECOVERING",
    "NEEDS_ATTENTION",
    "REPLAN_REQUIRED",
    "VERIFYING",
  ].includes(s.state);
  const needsNewRound = [
    "COMPENSATED",
    "CANCELLED",
    "EXPIRED",
    "SUPERSEDED",
  ].includes(s.state);
  const canEnact = [
    "AWAITING_APPROVAL",
    "PROPOSED",
    "READY",
    "PREPARED",
  ].includes(s.state);
  const executionDescription: Record<string, string> = {
    ACTIVE: `${verified} of ${actions.length} calendar effects were read back and verified. Each responsibility belongs to the person who approved it.`,
    NEEDS_ATTENTION:
      "Review the actual action receipts and remaining calendar effects below. User-edited entries are preserved for a person to resolve.",
    RECOVERING:
      "Inspect deterministic calendar entries before retrying. Applied changes and uncertain outcomes remain visible until reconciled.",
    VERIFYING:
      "The owner agents are reading back their independent local calendar entries. Only verified effects receive a checkmark.",
    APPLYING:
      "Each owner agent checks current consent and the approved manifest before its calendar action.",
    REPLAN_REQUIRED:
      "A released offer or current approval changed. Inspect existing calendar effects, then begin a fresh agreement round with renewed individual approval.",
    COMPENSATED:
      "The cancelled agreement remains in the audit. Begin a fresh round when the next set of offers is ready.",
  };
  const tasks = p?.tasks || s.goal.tasks || [];
  async function download(path: string, filename: string) {
    setExporting(path);
    try {
      await client.download(path, filename);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setExporting("");
    }
  }
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to agreement
      </a>
      <aside className="rail">
        <a className="rail-brand" href="#" aria-label="Common Ground home">
          <Mark />
          <span>
            common
            <br />
            ground<span className="brand-period">.</span>
          </span>
        </a>
        <div className="workspace-name">
          <span className="tiny-label">OUR CIRCLE</span>
          <strong>The people around Dev</strong>
          <span className="circle-mini">
            <Avatar id="asha" size="tiny" />
            <Avatar id="ravi" size="tiny" />
            <Avatar id="leena" size="tiny" />
            Three independent agents
          </span>
        </div>
        <nav className="main-nav" aria-label="Workspace">
          <button
            aria-pressed={tab === "agreement"}
            className={tab === "agreement" ? "active" : ""}
            onClick={() => setTab("agreement")}
          >
            <HeartHandshake size={20} />
            Our agreement
            <span className="nav-dot" />
          </button>
          <button
            aria-pressed={tab === "sharing"}
            className={tab === "sharing" ? "active" : ""}
            onClick={() => setTab("sharing")}
          >
            <Link2 size={20} />
            What we shared
          </button>
          <button
            aria-pressed={tab === "evidence"}
            className={tab === "evidence" ? "active" : ""}
            onClick={() => setTab("evidence")}
          >
            <FileCheck2 size={20} />
            Evidence & receipts
          </button>
        </nav>
        <div className="rail-owners">
          <span className="tiny-label">OWNER-LOCAL SPACES</span>
          {s.owners.map((o) => (
            <a
              key={o.id}
              className="rail-owner"
              href={o.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Avatar id={o.id} size="tiny" />
              <span>
                {o.name}
                <small>{o.role}</small>
              </span>
              <ArrowUpRight size={15} />
            </a>
          ))}
        </div>
        <div className="rail-bottom">
          <LockKeyhole size={17} />
          <p>
            Private reasons stay
            <br />
            with their owner.
          </p>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            Our circles <span>/</span> The people around Dev
          </div>
          <div className="top-meta">
            <button className="lock-workspace" onClick={service.lock}>
              <LockKeyhole size={13} />
              Lock workspace
            </button>
            <Pill tone="sample">Sample scenario</Pill>
            <span className="local-indicator">
              <span />
              Local workspace
            </span>
          </div>
        </header>
        <main id="main" className="main-content">
          <div className="sr-only" role="status" aria-live="polite">
            {p
              ? `Proposal version ${p.version}. ${statusCopy[s.state] || words(s.state)}`
              : statusCopy[s.state] || words(s.state)}
          </div>
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                A SHARED PLAN, A LITTLE MORE PEACE OF MIND
              </p>
              <h1>Let’s be there for Dev.</h1>
              <p>
                One afternoon. A few helping hands. Everyone’s own decision.
              </p>
            </div>
            <div className="date-stamp">
              <CalendarDays size={21} />
              <div>
                <strong>Monday, 2 November</strong>
                <span>2026 · Asia/Kolkata</span>
              </div>
            </div>
          </div>
          {error ? (
            <ErrorNotice
              message={error}
              onRetry={() => void service.refresh()}
            />
          ) : null}
          <div className="sample-context">
            <Flower2 size={16} />
            <span>
              Fictional family sample · Open a person’s separate local service
              to play their role. Pairing codes stay with the launcher.
            </span>
            <button
              onClick={() => void service.refresh()}
              className="text-button"
              aria-label="Refresh shared state"
            >
              <RefreshCw size={14} />
              <span>Refresh</span>
            </button>
          </div>
          {tab === "agreement" ? (
            <div className="agreement-layout">
              <div className="agreement-column">
                <section
                  className="agreement-sheet"
                  aria-labelledby="agreement-title"
                >
                  <header className="sheet-header">
                    <div className="sheet-kicker">
                      <span>THE AGREEMENT</span>
                      <span>
                        {p
                          ? `VERSION ${p.version.toString().padStart(2, "0")}`
                          : "GATHERING OFFERS"}
                      </span>
                    </div>
                    <div className="sheet-title-row">
                      <h2 id="agreement-title">
                        Dev’s afternoon
                        <br />
                        appointment
                      </h2>
                      <span className="appointment-seal">
                        <HeartHandshake size={28} />
                      </span>
                    </div>
                    <div className="appointment-meta">
                      <span>
                        <MapPin size={15} />
                        Home → clinic → home
                      </span>
                      <span>
                        <Clock3 size={15} />
                        Appointment at 14:00
                      </span>
                    </div>
                    <div className="sheet-status">
                      <Status status={s.state} />
                      <p>{statusCopy[s.state] || words(s.state)}</p>
                    </div>
                  </header>
                  <div className="responsibility-title">
                    <h3>Who’s doing what</h3>
                    <span>
                      {p
                        ? "Exact proposed responsibilities"
                        : "The pieces we’re bringing together"}
                    </span>
                  </div>
                  <ol className="responsibility-list">
                    {tasks.map((task, i) => {
                      const assignment = p?.assignments.find(
                        (a) => a.task_id === task.task_id,
                      );
                      const receipt = actions.find(
                        (a) => a.task_id === task.task_id,
                      );
                      const owner = s.owners.find(
                        (o) => o.id === assignment?.owner_id,
                      );
                      return (
                        <li
                          key={task.task_id}
                          className={
                            receipt?.status === "VERIFIED" ? "verified" : ""
                          }
                        >
                          <div className="timeline-time">
                            <strong>
                              {time(assignment?.start ?? task.earliest)}
                            </strong>
                            <span>
                              {time(
                                assignment?.end ??
                                  task.earliest + task.duration,
                              )}
                            </span>
                          </div>
                          <div className="timeline-track">
                            <span className={owner?.id || "unassigned"}>
                              {receipt?.status === "VERIFIED" ? (
                                <Check size={13} />
                              ) : (
                                i + 1
                              )}
                            </span>
                          </div>
                          <div className="responsibility-body">
                            <div>
                              <h4>{task.label}</h4>
                              <p>
                                {task.location} <span>·</span> {task.duration}{" "}
                                min
                              </p>
                            </div>
                            {owner ? (
                              <span className="assigned-owner">
                                <Avatar id={owner.id} size="tiny" />
                                {owner.name}
                              </span>
                            ) : (
                              <span className="unassigned-label">
                                To be agreed
                              </span>
                            )}
                            {receipt?.status ? (
                              <div className="receipt-inline">
                                <Status status={receipt.status} />
                                {receipt.error ? <p>{receipt.error}</p> : null}
                                {receipt.remaining_effect ? (
                                  <p>
                                    Remaining calendar effect requires review in
                                    the owner’s local agent.
                                  </p>
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                  <footer className="sheet-footer">
                    <ShieldCheck size={19} />
                    <p>
                      {p
                        ? p.checker.valid
                          ? "Independently checked against released offers. Each owner still validates their own private constraints."
                          : "The independent check did not pass. This proposal cannot be enacted."
                        : "The local solver will check the whole journey. Each person keeps the final say."}
                    </p>
                  </footer>
                </section>
                {p ? (
                  <section className="explanation-note">
                    <Sparkles size={20} />
                    <div>
                      <h3>
                        {p.model_receipt_id
                          ? "Nemotron’s proposed tradeoff"
                          : "A structured plan, checked locally"}
                      </h3>
                      {p.model_receipt_id ? (
                        <p className="model-provenance">
                          This model suggestion preceded the solver. The
                          responsibilities above are the independently checked
                          proposal.
                        </p>
                      ) : null}
                      <p>
                        {typeof p.explanation === "string"
                          ? p.explanation
                          : "View the structured planning explanation in the proposal record."}
                      </p>
                      <details>
                        <summary>
                          View exact version & validity{" "}
                          <ChevronDown size={15} />
                        </summary>
                        <dl className="technical-dl">
                          <dt>Proposal</dt>
                          <dd>
                            {p.proposal_id} · v{p.version}
                          </dd>
                          <dt>Proposal digest</dt>
                          <dd className="digest">{s.proposal_digest}</dd>
                          <dt>Action manifest</dt>
                          <dd className="digest">{s.manifest_digest}</dd>
                          <dt>Expires</dt>
                          <dd>
                            {new Date(p.expires_at).toLocaleString("en-GB", {
                              timeZone: "Asia/Kolkata",
                            })}{" "}
                            IST
                          </dd>
                          <dt>Solver</dt>
                          <dd>{p.solver.status}</dd>
                        </dl>
                        <JsonDetails
                          title="Full immutable proposal"
                          value={p}
                        />
                      </details>
                    </div>
                  </section>
                ) : (
                  <section className="quiet-promise">
                    <span className="handdrawn">
                      A plan that fits,
                      <br />
                      without the whole backstory.
                    </span>
                    <p>
                      Only a person’s released offer reaches this table. Their
                      calendar titles, notes, and reasons stay in their own
                      local agent.
                    </p>
                  </section>
                )}
              </div>
              <aside className="decision-column">
                <section className="next-step-panel">
                  <div className="section-eyebrow">
                    <span className="step-number">{p ? "02" : "01"}</span>
                    <span>THE NEXT SMALL STEP</span>
                  </div>
                  <h2>
                    {planning
                      ? "Bringing the pieces together."
                      : executionHeading[s.state]
                        ? executionHeading[s.state]
                        : p
                          ? approvals === requiredOwners.length
                            ? "Ready to make it real."
                            : "A yes from each person."
                          : allOffers
                            ? "Find the fit."
                            : "Start with everyone’s offer."}
                  </h2>
                  <p>
                    {planning
                      ? "The planner works only from authorized released facts. A proposal appears after the solver and independent checker agree."
                      : executionDescription[s.state]
                        ? executionDescription[s.state]
                        : p
                          ? "Each person reviews this exact version in their own local agent. Approval authorizes only their listed calendar actions."
                          : "Each owner chooses a time window and responsibilities, then reviews exactly what they are sharing."}
                  </p>
                  <ul className="consent-checklist">
                    {s.owners.map((o) => {
                      const released = releases.some(
                        (r) => r.body.issuer === o.id,
                      );
                      const approved = Boolean(currentApproval(o.id));
                      const required = requiredOwners.some(
                        (owner) => owner.id === o.id,
                      );
                      return (
                        <li key={o.id}>
                          <Avatar id={o.id} size="tiny" />
                          <div>
                            <strong>{o.name}</strong>
                            <span>
                              {p
                                ? !required
                                  ? "No actions in this version"
                                  : approved
                                    ? `Approved version ${p.version}`
                                    : "Decision still yours"
                                : released
                                  ? "Offer released"
                                  : "Offer not yet released"}
                            </span>
                          </div>
                          <span
                            className={`check-circle ${(p ? approved : released) ? "done" : ""}`}
                          >
                            {(p ? approved : released) ? (
                              <Check size={13} />
                            ) : (
                              <span />
                            )}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                  {!p ? (
                    <>
                      {inferenceBlocked.length ? (
                        <div className="inference-blocked">
                          <LockKeyhole size={16} />
                          <div>
                            <strong>Fireworks permission is missing.</strong>
                            <p>
                              {inferenceBlocked
                                .map((owner) => owner.name)
                                .join(", ")}{" "}
                              {inferenceBlocked.length === 1 ? "has" : "have"}{" "}
                              released to the circle without authorizing
                              Fireworks. Each person can separately review that
                              choice in their own local agent. The local solver
                              can use the current circle-only offers.
                            </p>
                            {inferenceBlocked.map((owner) => (
                              <a
                                key={owner.id}
                                href={`${owner.url}#release-offer`}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                Review {owner.name}’s Fireworks sharing
                                <ArrowUpRight size={13} />
                              </a>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      <button
                        className="button primary"
                        disabled={
                          !someOffers ||
                          !allInference ||
                          Boolean(busy) ||
                          planning
                        }
                        onClick={() =>
                          void act("Requesting live proposal", "/api/plan", {
                            mode: "live",
                            expected_revision: s.revision,
                          })
                        }
                      >
                        {planning ? (
                          <LoaderCircle className="spin" size={17} />
                        ) : (
                          <Sparkles size={17} />
                        )}
                        Plan with Nemotron
                        <ArrowRight size={17} />
                      </button>
                      <p className="button-caption">
                        Live Fireworks Ultra · each contributing release must
                        separately permit inference.
                      </p>
                      <button
                        className="button secondary"
                        disabled={!someOffers || Boolean(busy) || planning}
                        onClick={() =>
                          void act("Solving locally", "/api/plan", {
                            mode: "local",
                            expected_revision: s.revision,
                          })
                        }
                      >
                        <ListChecks size={17} />
                        Use the local structured solver
                      </button>
                      <p className="button-caption">
                        No model call. Same deterministic checks.
                      </p>
                    </>
                  ) : (
                    <>
                      <div className="approval-progress">
                        <span>
                          {approvals} of {requiredOwners.length} required
                          approvals
                        </span>
                        <span>v{p.version}</span>
                        <div>
                          <i
                            style={{
                              width: `${(approvals / Math.max(1, requiredOwners.length)) * 100}%`,
                            }}
                          />
                        </div>
                      </div>
                      <button
                        className="button primary"
                        disabled={
                          Boolean(busy) ||
                          (!needsReconcile &&
                            !needsNewRound &&
                            (approvals !== requiredOwners.length ||
                              !p.checker.valid ||
                              !canEnact ||
                              hasEffects))
                        }
                        onClick={() => {
                          if (needsNewRound) {
                            setConfirm("new-round");
                            return;
                          }
                          if (needsReconcile) {
                            void act(
                              "Reconciling real calendar effects",
                              "/api/reconcile",
                              { proposal_id: p.proposal_id },
                            );
                            return;
                          }
                          void act(
                            "Preparing calendar actions",
                            "/api/execute",
                            {
                              proposal_id: p.proposal_id,
                              expected_version: p.version,
                            },
                          );
                        }}
                      >
                        {needsReconcile ? (
                          <RefreshCw size={17} />
                        ) : needsNewRound ? (
                          <GitBranch size={17} />
                        ) : (
                          <CalendarDays size={17} />
                        )}
                        {needsReconcile
                          ? "Reconcile calendar effects"
                          : needsNewRound
                            ? "Begin a fresh agreement round"
                            : s.state === "ACTIVE"
                              ? "Calendar effects verified"
                              : s.state === "APPLYING"
                                ? "Applying approved actions"
                                : "Enact this agreement"}
                        <ArrowRight size={17} />
                      </button>
                      <p className="button-caption">
                        {needsReconcile ? (
                          "Reads actual local-calendar state before the next step. Only the owner can explicitly remove a user-edited entry."
                        ) : needsNewRound ? (
                          "Preserves the audit and safely reviews earlier calendar effects before starting again."
                        ) : (
                          <>
                            Creates {p.actions.length} entries in separate local
                            calendars. No invitations or real calendar accounts.
                          </>
                        )}
                      </p>
                    </>
                  )}
                  {busy ? (
                    <p className="operation-status" role="status">
                      <LoaderCircle size={15} className="spin" />
                      {busy}…
                    </p>
                  ) : null}
                  {s.planning.error ? (
                    <ErrorNotice message={s.planning.error} />
                  ) : null}
                </section>
                <section className="local-decisions">
                  <h3>
                    <Fingerprint size={18} />
                    Each person has their own door.
                  </h3>
                  <p>
                    Preferences, releases and final signatures happen in the
                    owner’s separate local service.
                  </p>
                  {s.owners.map((o) => (
                    <div className="local-door" key={o.id}>
                      <Avatar id={o.id} size="tiny" />
                      <strong>{o.name}</strong>
                      <OwnerLink owner={o} />
                    </div>
                  ))}
                </section>
                {p ? (
                  <section className="recovery-panel">
                    <h3>
                      <GitBranch size={18} />
                      When plans change
                    </h3>
                    <p>
                      {verified > 0
                        ? `${verified} of ${actions.length} calendar effects verified. `
                        : ""}
                      Check ambiguous writes before retrying. Cancellation
                      removes only unchanged entries created by this agreement.
                    </p>
                    <button
                      className="button secondary"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        void act(
                          "Reconciling real calendar effects",
                          "/api/reconcile",
                          { proposal_id: p.proposal_id },
                        )
                      }
                    >
                      <RefreshCw size={16} />
                      Reconcile calendar effects
                    </button>
                    <button
                      className="text-button"
                      disabled={Boolean(busy)}
                      onClick={() => setConfirm("compensate")}
                    >
                      <Undo2 size={15} />
                      Cancel applied calendar changes
                    </button>
                    <button
                      className="text-button"
                      disabled={Boolean(busy)}
                      onClick={() => setConfirm("new-round")}
                    >
                      <GitBranch size={15} />
                      Begin a fresh agreement round
                    </button>
                  </section>
                ) : (
                  <section className="small-note">
                    <CircleHelp size={19} />
                    <p>
                      Release to the circle and consent to Fireworks are
                      separate choices. The local solver is always an explicit
                      alternative.
                    </p>
                  </section>
                )}
              </aside>
            </div>
          ) : null}
          {tab === "sharing" ? (
            <section className="sharing-sheet">
              <div className="section-topline">
                <div>
                  <p className="eyebrow">ONLY WHAT WAS CHOSEN</p>
                  <h2 id="sharing-title">Small offers. Clear boundaries.</h2>
                </div>
                <button
                  className="button secondary compact"
                  onClick={() => setTextView(!textView)}
                >
                  {textView ? (
                    <UsersRound size={16} />
                  ) : (
                    <LayoutList size={16} />
                  )}{" "}
                  {textView ? "Island view" : "Equivalent text view"}
                </button>
              </div>
              <p className="section-intro">
                These are the actual offers released to this circle. No private
                calendar title, personal note, or reason travels along a ribbon.
              </p>
              <div className={`owner-islands ${textView ? "text-view" : ""}`}>
                {s.owners.map((o) => (
                  <ReleasedIsland
                    key={o.id}
                    owner={o}
                    release={releases.find((r) => r.body.issuer === o.id)}
                  />
                ))}
              </div>
              <div className="shared-destination">
                <Mark small />
                <div>
                  <strong>The shared agreement room</strong>
                  <p>
                    Released offers only · signatures bind the recipients and
                    purpose
                  </p>
                </div>
              </div>
              <div className="boundary-note">
                <LockKeyhole size={20} />
                <div>
                  <h3>Private stays behind each owner’s door.</h3>
                  <p>
                    The broker cannot open the private preference form, calendar
                    source, or signing endpoint. This local demo does not
                    protect against the same operating-system administrator.
                  </p>
                </div>
              </div>
              <JsonDetails
                title="Inspect released grants and actual disclosures"
                value={{ grants: s.offers, disclosures: s.disclosures }}
              />
            </section>
          ) : null}
          {tab === "evidence" ? (
            <section className="evidence-sheet">
              <div className="section-topline">
                <div>
                  <p className="eyebrow">AN AGREEMENT YOU CAN INSPECT</p>
                  <h2 id="evidence-title">Show the work.</h2>
                </div>
                <button
                  className="button primary compact"
                  disabled={Boolean(exporting)}
                  onClick={() =>
                    void download(
                      "/api/evidence",
                      "common-ground-evidence.json",
                    )
                  }
                >
                  <ArrowDownToLine size={16} />
                  Export evidence
                </button>
              </div>
              <p className="section-intro">
                Actual model attempts, signed decisions, independent checks, and
                local calendar effects. Failed attempts remain part of the
                record.
              </p>
              <div className="evidence-summary">
                <div>
                  <ClipboardCheck size={23} />
                  <strong>
                    {p ? `Version ${p.version}` : "No proposal yet"}
                  </strong>
                  <span>
                    {p
                      ? short(s.proposal_digest)
                      : "Waiting for released offers"}
                  </span>
                </div>
                <div>
                  <ShieldCheck size={23} />
                  <strong>
                    {p
                      ? p.checker.valid
                        ? "Independent check passed"
                        : "Check needs attention"
                      : "Not checked yet"}
                  </strong>
                  <span>{p?.solver.status || "A candidate is required"}</span>
                </div>
                <div>
                  <CalendarDays size={23} />
                  <strong>{verified} verified calendar effects</strong>
                  <span>
                    {actions.length
                      ? `Across ${actions.length} proposed actions`
                      : "No calendar writes requested"}
                  </span>
                </div>
              </div>
              <h3 className="subsection-title">Model run receipts</h3>
              {s.model_runs.length ? (
                <div className="run-list">
                  {s.model_runs.map((run, i) => (
                    <article key={run.receipt_id || i} className="run-row">
                      <div>
                        <Sparkles size={18} />
                        <strong>
                          {run.provider || "Provider recorded in receipt"}
                        </strong>
                        <Status status={run.status || "RECORDED"} />
                      </div>
                      <p className="model-name">{run.model}</p>
                      {run.error ? (
                        <p className="run-error">{run.error}</p>
                      ) : null}
                      <JsonDetails
                        title={`Receipt ${run.receipt_id || i + 1}`}
                        value={run}
                      />
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <Sparkles size={24} />
                  <p>No model calls have been made in this workspace.</p>
                  <span>
                    A local structured-solver plan does not create a model
                    receipt.
                  </span>
                </div>
              )}
              <h3 className="subsection-title">Durable agreement history</h3>
              {s.history.length ? (
                <ol className="history-list">
                  {[...s.history].reverse().map((item, i) => {
                    const record =
                      item && typeof item === "object" && !Array.isArray(item)
                        ? item
                        : {};
                    return (
                      <li key={i}>
                        <span className="history-pin" />
                        <div>
                          <strong>
                            {String(
                              record.summary || record.type || "Protocol event",
                            )}
                          </strong>
                          <small>
                            {record.time
                              ? new Date(String(record.time)).toLocaleString(
                                  "en-GB",
                                  { timeZone: "Asia/Kolkata" },
                                ) + " IST"
                              : "Time in full record"}
                          </small>
                          <JsonDetails title="Event record" value={item} />
                        </div>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <div className="empty-state">
                  <p>No agreement events yet.</p>
                </div>
              )}
              <div className="export-row">
                <button
                  className="button secondary"
                  disabled={Boolean(exporting)}
                  onClick={() =>
                    void download(
                      "/api/agreement.ics",
                      "common-ground-agreement.ics",
                    )
                  }
                >
                  <CalendarDays size={17} />
                  Export agreement calendar (.ics)
                </button>
                <span>
                  Planned and verified entries are labeled in the export.
                </span>
              </div>
              <JsonDetails
                title="Signed approvals and action receipts"
                value={{
                  proposal: p,
                  proposal_digest: s.proposal_digest,
                  manifest_digest: s.manifest_digest,
                  approvals: s.approvals,
                  actions: s.actions,
                }}
              />
              <div className="boundary-note">
                <FileCheck2 size={20} />
                <p>
                  Authored local sample. No participant study, clinical outcome,
                  distributed isolation, or live Google Calendar integration is
                  claimed. Nebius submission runtime qualification remains a
                  separate step.
                </p>
              </div>
            </section>
          ) : null}
          <footer className="workspace-footer">
            <span>
              <Mark small />
              Together, with room for yourself.
            </span>
            <span>
              {service.lastLoaded
                ? `Last checked ${service.lastLoaded.toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata" })} IST`
                : "Waiting for local service"}
              <span className="footer-divider">·</span>Released state only
            </span>
          </footer>
        </main>
      </div>
      {confirm ? (
        <Confirmation
          kind={confirm}
          close={() => setConfirm(null)}
          confirm={() => {
            const action = confirm;
            setConfirm(null);
            void act(
              action === "compensate"
                ? "Conditionally removing calendar effects"
                : "Starting a new round",
              `/api/${action}`,
              action === "compensate"
                ? { proposal_id: p?.proposal_id }
                : { expected_revision: s.revision },
            );
          }}
        />
      ) : null}
    </div>
  );
}
function Confirmation({
  kind,
  close,
  confirm,
}: {
  kind: "compensate" | "new-round";
  close: () => void;
  confirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement;
    node?.showModal();
    return () => {
      node?.close();
      if (previous instanceof HTMLElement && previous.isConnected)
        requestAnimationFrame(() => previous.focus());
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="confirm-dialog"
      aria-labelledby="confirm-title"
      onCancel={close}
    >
      <section className="confirm-sheet">
        <h2 id="confirm-title">
          {kind === "compensate"
            ? "Cancel the applied changes?"
            : "Begin a new agreement round?"}
        </h2>
        <p>
          {kind === "compensate"
            ? "The owner agents will remove only unchanged calendar entries created by this agreement. A user-edited event will remain visible and need attention."
            : "The broker will safely compensate preceding calendar effects and preserve the history. Any new proposal will need fresh individual approvals."}
        </p>
        <div>
          <button autoFocus className="button secondary" onClick={close}>
            Keep this agreement
          </button>
          <button className="button primary" onClick={confirm}>
            {kind === "compensate"
              ? "Cancel applied changes"
              : "Start new round"}
          </button>
        </div>
      </section>
    </dialog>
  );
}
function ReleasedIsland({
  owner,
  release,
}: {
  owner: Owner;
  release?: Envelope<ReleasePayload>;
}) {
  const r = release?.body.payload;
  return (
    <article className={`owner-island ${owner.id}`}>
      <div className="island-head">
        <Avatar id={owner.id} />
        <div>
          <h3>{owner.name}</h3>
          <span>{owner.role}</span>
        </div>
        <LockKeyhole size={17} />
      </div>
      <div className="private-boundary">
        <span>PRIVATE OWNER SPACE</span>
        <p>Preferences & calendar stay local</p>
        <OwnerLink owner={owner} />
      </div>
      {r ? (
        <div className="offer-ribbon">
          <span className="tiny-label">
            RELEASED OFFER · REV {r.offer.revision}
          </span>
          <strong>
            {time(r.offer.start)}—{time(r.offer.end)}
          </strong>
          <p>{r.offer.task_ids.map(words).join(" · ")}</p>
          <dl>
            <dt>People</dt>
            <dd>
              {r.recipients.humans
                .map((id) => names[id as OwnerId] || id)
                .join(", ")}
            </dd>
            <dt>Coordinator</dt>
            <dd>Common Ground broker</dd>
            <dt>Inference</dt>
            <dd>
              {r.recipients.inference.length
                ? r.recipients.inference.map(words).join(", ")
                : "Not authorized"}
            </dd>
          </dl>
          <small>
            Expires{" "}
            {new Date(release.body.expires_at).toLocaleString("en-GB", {
              timeZone: "Asia/Kolkata",
            })}{" "}
            IST
          </small>
          <JsonDetails title="Exact signed release" value={release} />
        </div>
      ) : (
        <div className="unreleased-offer">
          <LockKeyhole size={18} />
          <strong>No active released offer</strong>
          <p>Only {owner.name} can choose what to share.</p>
        </div>
      )}
    </article>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
