import { useEffect, useRef, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  Check,
  ChevronDown,
  CircleAlert,
  ClipboardCheck,
  Fingerprint,
  FlaskConical,
  HeartHandshake,
  History,
  KeyRound,
  ListChecks,
  LoaderCircle,
  LockKeyhole,
  Settings2,
  ShieldCheck,
  Sparkles,
  Undo2,
  UserRound,
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
  time,
  useService,
  words,
} from "../web/ui";
import type {
  CalendarEvent,
  OwnerId,
  OwnerState,
  Preferences,
  ReleasePreview,
} from "../web/types";

const faultOptions = [
  [
    "none",
    "Normal operation",
    "Writes and independently reads back the local calendar entry.",
  ],
  [
    "timeout_after_write",
    "Timeout after write",
    "Actually writes an event, then returns an ambiguous result. Reconciliation must inspect it before retrying.",
  ],
  [
    "fail_before_write",
    "Fail before write",
    "Returns a confirmed failure without creating the requested calendar entry.",
  ],
  [
    "pause_before_send",
    "Pause before send",
    "Persists a dispatch intent and pauses transmission so withdrawal and recovery can be tested.",
  ],
  [
    "conflict_before_write",
    "Calendar conflict before write",
    "Introduces a local calendar conflict that blocks the requested action.",
  ],
] as const;
function App() {
  const service = useService<OwnerState>("owner");
  const { state: s, error, busy, act, client, setError } = service;
  const [tab, setTab] = useState<"decision" | "preferences" | "calendar">(
    "decision",
  );
  const [allowInference, setAllowInference] = useState(false);
  const [humanConsent, setHumanConsent] = useState(false);
  const [brokerConsent, setBrokerConsent] = useState(false);
  const [approvalConsent, setApprovalConsent] = useState(false);
  const [preview, setPreview] = useState<ReleasePreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const withdrawalTrigger = useRef<HTMLButtonElement>(null);
  const withdrawalHeading = useRef<HTMLHeadingElement>(null);
  const wasWithdrawing = useRef(false);
  useEffect(() => {
    if (withdrawing) withdrawalHeading.current?.focus();
    else if (wasWithdrawing.current) {
      if (withdrawalTrigger.current && !withdrawalTrigger.current.disabled)
        withdrawalTrigger.current.focus();
      else {
        const next = document.querySelector<HTMLElement>(".release-sheet h2");
        next?.setAttribute("tabindex", "-1");
        next?.focus();
      }
    }
    wasWithdrawing.current = withdrawing;
  }, [withdrawing]);
  const [exporting, setExporting] = useState(false);
  const [eventRemoved, setEventRemoved] = useState(false);
  const initializedReleaseChoices = useRef(false);
  useEffect(() => {
    if (!s || initializedReleaseChoices.current) return;
    initializedReleaseChoices.current = true;
    setAllowInference(
      Boolean(
        s.release?.body.payload.recipients.inference.includes("fireworks"),
      ),
    );
  }, [Boolean(s)]);
  useEffect(() => {
    const selector =
      tab === "decision"
        ? ".owner-main-column > :first-child h2"
        : tab === "preferences"
          ? ".preferences-sheet h2"
          : ".calendar-sheet h2";
    const target = document.querySelector<HTMLElement>(selector);
    if (!target) return;
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
    document
      .getElementById("main")
      ?.scrollIntoView({ block: "start", behavior: "auto" });
  }, [tab]);
  useEffect(() => {
    if (!service.paired || !s) return;
    let current = true;
    setPreviewLoading(true);
    setPreviewError("");
    setPreview(null);
    client
      .preview(allowInference)
      .then((value) => {
        if (current) setPreview(value);
      })
      .catch((e: unknown) => {
        if (current)
          setPreviewError(
            e instanceof Error
              ? e.message
              : "The exact release preview is unavailable.",
          );
      })
      .finally(() => {
        if (current) setPreviewLoading(false);
      });
    return () => {
      current = false;
    };
  }, [
    service.paired,
    s?.constraint_revision,
    s?.consent_revision,
    allowInference,
  ]);
  const wrapper = s?.proposals.find((w) => w.proposal);
  useEffect(() => {
    if (s && location.hash === "#release-offer")
      requestAnimationFrame(() =>
        document
          .getElementById("release-offer")
          ?.scrollIntoView({ block: "start" }),
      );
  }, [Boolean(s)]);
  useEffect(() => {
    setApprovalConsent(false);
  }, [
    wrapper?.proposal?.proposal_id,
    wrapper?.proposal?.version,
    s?.constraint_revision,
    s?.consent_revision,
    s?.release?.body.payload.offer.offer_id,
    s?.release?.body.payload.offer.revision,
  ]);
  if (!service.paired)
    return (
      <Pairing kind="owner" pair={service.pair} error={error} busy={busy} />
    );
  if (!s)
    return error ? (
      <div className="loading">
        <Mark />
        <h1>Your local agent is offline.</h1>
        <ErrorNotice message={error} onRetry={() => void service.refresh()} />
      </div>
    ) : (
      <Loading />
    );
  const ownerId = ("id" in s.owner ? s.owner.id : s.owner.owner_id) as OwnerId;
  const ownerName = s.owner.name;
  const p = wrapper?.proposal;
  const ownActions = p?.actions.filter((a) => a.owner_id === ownerId) || [];
  const approval = s.approvals.find(
    (a) =>
      a.body.payload.proposal_id === p?.proposal_id &&
      a.body.payload.version === p?.version &&
      a.body.payload.proposal_digest === wrapper?.proposal_digest &&
      a.body.payload.manifest_digest === wrapper?.manifest_digest &&
      a.body.consent_revision === s.consent_revision &&
      Date.parse(a.body.payload.execution_not_after) > Date.now() &&
      a.body.payload.constraint_revision === s.constraint_revision &&
      Date.parse(a.body.expires_at) > Date.now(),
  );
  const released =
    s.release && Date.parse(s.release.body.expires_at) > Date.now();
  const ownOfferRef = p?.offer_refs.find((ref) => ref.owner_id === ownerId);
  const staleProposal =
    ownActions.length > 0 &&
    (!released ||
      !ownOfferRef ||
      ownOfferRef.constraint_revision !== s.constraint_revision ||
      ownOfferRef.consent_revision !== s.consent_revision ||
      ownOfferRef.offer_id !== s.release?.body.payload.offer.offer_id ||
      ownOfferRef.revision !== s.release?.body.payload.offer.revision ||
      ownOfferRef.constraint_revision !==
        s.release?.body.payload.offer.constraint_revision ||
      ownOfferRef.consent_revision !== s.release?.body.consent_revision ||
      p?.goal_revision !== s.release?.body.payload.goal_revision ||
      !(Date.parse(p?.expires_at || "") > Date.now()));
  const releasePayload =
    preview?.payload ||
    (preview?.offer && preview?.recipients ? preview : null);
  const offer = releasePayload?.offer;
  const recipients = releasePayload?.recipients;
  const faultMode = typeof s.fault === "string" ? s.fault : s.fault.mode;
  async function exportCalendar() {
    setExporting(true);
    try {
      await client.download(
        "/api/calendar.ics",
        `common-ground-${ownerId}.ics`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Calendar export failed.");
    } finally {
      setExporting(false);
    }
  }
  const releaseSheet = (
    <section id="release-offer" className="release-sheet">
      <div className="section-topline">
        <div>
          <p className="eyebrow">01 · YOUR BOUNDED OFFER</p>
          <h2>Share the useful part.</h2>
        </div>
        {released ? (
          <Pill tone="good">
            <Check size={13} />
            Offer released
          </Pill>
        ) : (
          <Pill>Not currently released</Pill>
        )}
      </div>
      <p className="section-intro">
        A time window and the tasks you can take. Your private reasons, notes,
        and calendar titles stay here.
      </p>
      {previewLoading ? (
        <div className="preview-loading">
          <LoaderCircle size={18} className="spin" />
          Loading your exact release preview…
        </div>
      ) : null}
      {previewError ? <ErrorNotice message={previewError} /> : null}
      {offer ? (
        <div className={`bounded-offer ${ownerId}`}>
          <span className="tiny-label">
            EXACT OFFER PREVIEW · CONSTRAINT REVISION {s.constraint_revision}
          </span>
          <div>
            <Avatar id={ownerId} />
            <span>
              <strong>
                {time(offer.start)}—{time(offer.end)}
              </strong>
              <small>Monday, 2 November · Asia/Kolkata</small>
            </span>
          </div>
          <p>{offer.task_ids.map(words).join(" · ")}</p>
          <span className="capacity-line">
            One responsibility at a time · task allowlist enforced locally
          </span>
          <span className="capacity-line">
            Released burden weight: {offer.preference_cost}
          </span>
        </div>
      ) : null}
      {released && s.release ? (
        <div className="active-release-summary">
          <div>
            <ShieldCheck size={18} />
            <strong>
              Active release · consent revision{" "}
              {s.release.body.consent_revision}
            </strong>
          </div>
          <dl>
            <dt>People</dt>
            <dd>
              {s.release.body.payload.recipients.humans
                .map((id) => names[id as OwnerId] || id)
                .join(", ")}
            </dd>
            <dt>Coordinator</dt>
            <dd>Common Ground broker</dd>
            <dt>Fireworks inference</dt>
            <dd>
              {s.release.body.payload.recipients.inference.includes("fireworks")
                ? "Authorized by this active grant"
                : "Not authorized by this grant"}
            </dd>
            <dt>Expiry</dt>
            <dd>
              {new Date(s.release.body.expires_at).toLocaleString("en-GB", {
                timeZone: "Asia/Kolkata",
              })}{" "}
              IST
            </dd>
          </dl>
          <p>
            These permissions are active. The draft choices below take effect
            only when you release again. To stop future use, review withdrawal
            separately.
          </p>
        </div>
      ) : null}
      <div className="recipient-list">
        <h3>
          {released
            ? "Review the next release · draft choices"
            : "Who receives this offer"}
        </h3>
        {released ? (
          <p className="next-release-hint">
            Review the people and coordinator again. Your draft never changes
            the active grant until you press “Release this reviewed offer
            again.”
          </p>
        ) : null}
        <label className="consent-choice">
          <input
            type="checkbox"
            checked={humanConsent}
            onChange={(e) => setHumanConsent(e.target.checked)}
          />
          <span>
            <strong>The people in this circle</strong>
            <small>
              {recipients?.humans
                .map((id) => names[id as OwnerId] || id)
                .join(", ") || "Asha, Ravi and Leena"}{" "}
              · released fields only
            </small>
          </span>
          <UserRound size={18} />
        </label>
        <label className="consent-choice">
          <input
            type="checkbox"
            checked={brokerConsent}
            onChange={(e) => setBrokerConsent(e.target.checked)}
          />
          <span>
            <strong>The Common Ground coordinator</strong>
            <small>
              Uses your bounded offer to coordinate this appointment.
            </small>
          </span>
          <HeartHandshake size={18} />
        </label>
        <label className="consent-choice inference-choice">
          <input
            type="checkbox"
            checked={allowInference}
            onChange={(e) => setAllowInference(e.target.checked)}
          />
          <span>
            <strong>Fireworks inference · separate, optional</strong>
            <small>
              Permits this released offer to reach NVIDIA Nemotron Ultra on
              Fireworks. No private notes or calendar titles.
            </small>
          </span>
          <Sparkles size={18} />
        </label>
      </div>
      <details className="release-details">
        <summary>
          Review every field being released <ChevronDown size={16} />
        </summary>
        <div className="field-chips">
          {releasePayload?.fields?.map((field) => (
            <code key={field}>{field}</code>
          ))}
        </div>
        <p>
          <strong>Purpose:</strong>{" "}
          {releasePayload?.purpose || "coordinate-appointment"}
        </p>
        <p>
          <strong>Retention:</strong>{" "}
          {releasePayload?.retention ||
            "Released facts remain in the local agreement audit. Withdrawal stops future use."}
        </p>
        <p>
          <strong>Recipients:</strong> people, broker
          {allowInference ? ", and Fireworks" : "; inference not authorized"}.
        </p>
        <JsonDetails title="Exact preview payload" value={preview} />
      </details>
      <div className="release-actions">
        <button
          className="button primary"
          disabled={
            Boolean(busy) ||
            previewLoading ||
            !preview ||
            !humanConsent ||
            !brokerConsent
          }
          onClick={() =>
            void act("Signing and releasing the exact offer", "/api/release", {
              allow_inference: allowInference,
              expected_revision: s.constraint_revision,
              preview_digest: preview?.preview_digest,
            })
          }
        >
          <ArrowUpRight size={17} />
          {released
            ? "Release this reviewed offer again"
            : "Release this reviewed offer"}
          <ArrowRight size={17} />
        </button>
        <button className="text-button" onClick={() => setTab("preferences")}>
          <Settings2 size={15} />
          Change my availability first
        </button>
      </div>
      {s.release ? (
        <JsonDetails
          title="Inspect your last signed release receipt"
          value={s.release}
        />
      ) : null}
    </section>
  );
  const approvalSheet = (
    <section className="approval-sheet">
      <div className="section-topline">
        <div>
          <p className="eyebrow">02 · YOUR EXACT DECISION</p>
          <h2>
            {p
              ? staleProposal
                ? `Version ${p.version} needs a fresh decision.`
                : `A clear yes to version ${p.version}.`
              : "Your decision comes next."}
          </h2>
        </div>
        <Fingerprint size={28} />
      </div>
      {p ? (
        <>
          <p className="section-intro">
            You are approving only your own actions below. Your local agent
            checks this exact proposal against your current private preferences
            before signing.
          </p>
          <div className="decision-version">
            <Pill>PROPOSAL V{p.version}</Pill>
            <span>Current private constraints r{s.constraint_revision}</span>
            <span>Current consent r{s.consent_revision}</span>
            {staleProposal ? <Pill tone="warning">Stale proposal</Pill> : null}
          </div>
          <ol className="own-action-list">
            {ownActions.map((action) => (
              <li key={action.action_id}>
                <CalendarDays size={20} />
                <div>
                  <h3>{action.label}</h3>
                  <p>
                    {time(action.start)}—{time(action.end)} · {action.date} ·{" "}
                    {action.timezone}
                  </p>
                  <small>Creates an owner-only local-calendar entry</small>
                </div>
                <span>{action.end - action.start} min</span>
              </li>
            ))}
          </ol>
          {ownActions.length ? (
            <div className="approval-consequences">
              <ShieldCheck size={20} />
              <div>
                <h3>What your approval authorizes</h3>
                <p>
                  Create these {ownActions.length} local calendar{" "}
                  {ownActions.length === 1 ? "entry" : "entries"} after all
                  required owners approve. If the agreement breaks,
                  conditionally remove only unchanged entries created by this
                  app. A user-edited event stays in your calendar and needs
                  attention.
                </p>
                <p>
                  Withdrawal stops future use. Already transmitted or applied
                  actions need reconciliation; cancellation is not
                  instantaneous.
                </p>
              </div>
            </div>
          ) : (
            <div className="approval-confirmed">
              <ShieldCheck size={20} />
              <div>
                <strong>No actions are assigned to you in this version.</strong>
                <p>
                  You do not need to approve another person’s calendar. Your
                  released offer remains inspectable below.
                </p>
              </div>
            </div>
          )}
          <dl className="approval-digests">
            <dt>Proposal digest</dt>
            <dd className="digest">{wrapper?.proposal_digest}</dd>
            <dt>Action manifest digest</dt>
            <dd className="digest">{wrapper?.manifest_digest}</dd>
            <dt>Valid until</dt>
            <dd>
              {new Date(p.expires_at).toLocaleString("en-GB", {
                timeZone: "Asia/Kolkata",
              })}{" "}
              IST
            </dd>
          </dl>
          {staleProposal ? (
            <div className="notice warning">
              <CircleAlert size={19} />
              <div>
                <strong>This version needs a fresh review.</strong>
                <p>
                  The proposal no longer matches your current consent or private
                  constraint revision, or its validity window expired. Review a
                  fresh release and ask for a new proposal. Calendar effects
                  already applied still need reconciliation.
                </p>
                <a className="owner-link" href="#release-offer">
                  Review my current release
                  <ArrowRight size={15} />
                </a>
                <a
                  className="owner-link stale-proposal-link"
                  href="http://127.0.0.1:4301"
                >
                  Open the shared room for a fresh version
                  <ArrowUpRight size={15} />
                </a>
              </div>
            </div>
          ) : null}
          {!ownActions.length ? null : approval && !staleProposal ? (
            <div className="approval-confirmed">
              <Check size={20} />
              <div>
                <strong>You approved this exact version.</strong>
                <p>
                  The shared coordinator can enact only the current signed
                  manifest, after every required owner approves.
                </p>
              </div>
            </div>
          ) : (
            <>
              <label className="consent-choice final-consent">
                <input
                  type="checkbox"
                  disabled={staleProposal || Boolean(busy)}
                  checked={approvalConsent}
                  onChange={(e) => setApprovalConsent(e.target.checked)}
                />
                <span>
                  I, {ownerName}, approve these exact actions and the
                  conditional cancellation policy above.
                </span>
              </label>
              <div className="approval-bar">
                <span>
                  <strong>
                    {ownerName}’s decision · version {p.version}
                  </strong>
                  <small>
                    {ownActions.length} calendar{" "}
                    {ownActions.length === 1 ? "entry" : "entries"} · local
                    adapter only
                  </small>
                </span>
                <button
                  className="button primary"
                  disabled={
                    !approvalConsent ||
                    staleProposal ||
                    Boolean(busy) ||
                    !ownActions.length ||
                    Date.parse(p.expires_at) <= Date.now()
                  }
                  onClick={() =>
                    void act(
                      `Approving exact version ${p.version}`,
                      "/api/approve",
                      {
                        proposal_id: p.proposal_id,
                        expected_version: p.version,
                      },
                    )
                  }
                >
                  <Fingerprint size={17} />
                  {staleProposal
                    ? "A fresh proposal is required"
                    : "Approve my exact actions"}
                </button>
              </div>
            </>
          )}
          <JsonDetails
            title="Inspect full proposal, checker and approval"
            value={{ ...wrapper, approval }}
          />
        </>
      ) : (
        <div className="waiting-decision">
          <ClipboardCheck size={30} />
          <h3>Nothing to sign yet.</h3>
          <p>
            Release your offer, then return to the shared agreement room. A
            proposal will appear here only after a real plan has passed its
            checks.
          </p>
          <a className="button secondary" href="http://127.0.0.1:4301">
            Go to our agreement
            <ArrowUpRight size={16} />
          </a>
        </div>
      )}
    </section>
  );
  return (
    <div className={`app-shell owner-shell theme-${ownerId}`}>
      <a href="#main" className="skip-link">
        Skip to my decision
      </a>
      <aside className="rail">
        <a
          className="rail-brand"
          href="http://127.0.0.1:4301"
          aria-label="Return to shared agreement"
        >
          <Mark />
          <span>
            common
            <br />
            ground<span className="brand-period">.</span>
          </span>
        </a>
        <div className="owner-identity">
          <Avatar id={ownerId} />
          <span className="tiny-label">YOU ARE IN</span>
          <h2>{ownerName}’s local agent</h2>
          <p>Private to this owner</p>
          <Pill>
            <LockKeyhole size={12} />
            Owner-local service
          </Pill>
        </div>
        <nav className="main-nav" aria-label="My local agent">
          <button
            aria-pressed={tab === "decision"}
            className={tab === "decision" ? "active" : ""}
            onClick={() => setTab("decision")}
          >
            <HeartHandshake size={20} />
            My decision
          </button>
          <button
            aria-pressed={tab === "preferences"}
            className={tab === "preferences" ? "active" : ""}
            onClick={() => setTab("preferences")}
          >
            <UserRound size={20} />
            Preferences & memory
          </button>
          <button
            aria-pressed={tab === "calendar"}
            className={tab === "calendar" ? "active" : ""}
            onClick={() => setTab("calendar")}
          >
            <CalendarDays size={20} />
            My local calendar
          </button>
        </nav>
        <a className="return-link" href="http://127.0.0.1:4301">
          <ArrowLeft size={16} />
          Return to our agreement
        </a>
        <div className="rail-bottom">
          <Fingerprint size={18} />
          <p>
            Your release.
            <br />
            Your signature. Your say.
          </p>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            My agent <span>/</span> {ownerName}’s private space
          </div>
          <div className="top-meta">
            <button className="lock-workspace" onClick={service.lock}>
              <LockKeyhole size={13} />
              Lock workspace
            </button>
            <Pill tone="sample">Fictional role: {ownerName}</Pill>
            <span className="local-indicator">
              <span />
              Local service · {location.port}
            </span>
          </div>
        </header>
        <main id="main" className="main-content">
          <div className="sr-only" role="status" aria-live="polite">
            {p
              ? staleProposal
                ? `Proposal version ${p.version} no longer matches ${ownerName}’s current release. A fresh version is required.`
                : `Proposal version ${p.version} is available for ${ownerName}’s exact decision.`
              : `No current proposal is available for ${ownerName} to sign.`}
          </div>
          <div className="page-heading">
            <div>
              <p className="eyebrow">A LITTLE SPACE TO DECIDE FOR YOURSELF</p>
              <h1>
                {tab === "decision"
                  ? `Your part, ${ownerName}.`
                  : tab === "preferences"
                    ? "An agent that remembers your say."
                    : "Your calendar, close to home."}
              </h1>
              <p>
                {tab === "decision"
                  ? "Choose what to share. See what you’re agreeing to."
                  : tab === "preferences"
                    ? "Structured preferences stay in this owner’s local store."
                    : "Actual durable entries in this fictional owner’s local calendar."}
              </p>
            </div>
            <Avatar id={ownerId} size="large" />
          </div>
          <div className="privacy-strip">
            <LockKeyhole size={18} />
            <span>
              <strong>{ownerName}’s private owner service.</strong> The shared
              broker cannot read this screen or sign on your behalf. Fictional
              sample role switching happens by opening separate local services.
            </span>
          </div>
          {s.coordinator_available === false ? (
            <div className="notice warning">
              <CircleAlert size={18} />
              <div>
                <strong>The shared coordinator is unavailable.</strong>
                <p>
                  Your private owner state is available. Current shared
                  proposals cannot be refreshed or approved until the
                  coordinator reconnects.
                </p>
              </div>
            </div>
          ) : null}
          {error ? (
            <ErrorNotice
              message={error}
              onRetry={() => void service.refresh()}
            />
          ) : null}
          {busy ? (
            <div className="notice operation-status" role="status">
              <LoaderCircle className="spin" size={18} />
              {busy}…
            </div>
          ) : null}
          {tab === "decision" ? (
            <div className="owner-decision-layout">
              <div className="owner-main-column">
                {p ? (
                  <>
                    {approvalSheet}
                    {releaseSheet}
                  </>
                ) : (
                  <>
                    {releaseSheet}
                    {approvalSheet}
                  </>
                )}
              </div>
              <aside className="owner-context-column">
                <section className="owner-context-card">
                  <Avatar id={ownerId} />
                  <p className="eyebrow">THIS IS YOUR SPACE</p>
                  <h2>
                    Room for
                    <br />
                    your own reasons.
                  </h2>
                  <p>
                    Availability is enough. You never need to explain a personal
                    reason to the circle.
                  </p>
                  <div className="context-rule" />
                  <dl>
                    <dt>Preferences</dt>
                    <dd>Revision {s.constraint_revision}</dd>
                    <dt>Consent</dt>
                    <dd>Revision {s.consent_revision}</dd>
                    <dt>Signing identity</dt>
                    <dd>{short(s.owner.key_id || s.release?.body.key_id)}</dd>
                  </dl>
                  <button
                    className="text-button"
                    onClick={() => setTab("preferences")}
                  >
                    Review what my agent remembers
                    <ArrowRight size={15} />
                  </button>
                </section>
                <section className="withdraw-card">
                  <Undo2 size={21} />
                  <h3>My availability changed</h3>
                  <p>
                    Withdraw your offer and approval without sharing a private
                    reason. Calendar changes already made will need
                    reconciliation and safe cancellation.
                  </p>
                  {withdrawing ? (
                    <div
                      id="withdraw-confirmation"
                      className="inline-confirm"
                      role="group"
                      aria-labelledby="withdraw-heading"
                    >
                      <h4
                        id="withdraw-heading"
                        ref={withdrawalHeading}
                        tabIndex={-1}
                      >
                        Withdraw current consent?
                      </h4>
                      <p>
                        This stops future use. Released facts remain in the
                        agreement audit.
                      </p>
                      <button
                        className="button danger"
                        disabled={Boolean(busy)}
                        onClick={async () => {
                          const ok = await act(
                            "Withdrawing your current consent",
                            "/api/withdraw",
                            { expected_revision: s.consent_revision },
                          );
                          if (ok) setWithdrawing(false);
                        }}
                      >
                        Withdraw my offer
                      </button>
                      <button
                        className="text-button"
                        disabled={Boolean(busy)}
                        onClick={() => setWithdrawing(false)}
                      >
                        Keep my current offer
                      </button>
                    </div>
                  ) : (
                    <button
                      ref={withdrawalTrigger}
                      className="button secondary"
                      disabled={Boolean(busy) || !s.release}
                      onClick={() => setWithdrawing(true)}
                    >
                      Review withdrawal
                      <ArrowRight size={16} />
                    </button>
                  )}
                </section>
                <div className="small-note">
                  <LockKeyhole size={18} />
                  <p>
                    Separate processes and HTTP capabilities enforce this local
                    demo’s boundaries. Hostile code running as the same OS user
                    and the administrator are outside its threat model.
                  </p>
                </div>
              </aside>
            </div>
          ) : null}
          {tab === "preferences" ? (
            <div className="preferences-layout">
              <PreferencesForm
                state={s}
                busy={busy}
                save={(body) =>
                  act(
                    "Saving your private preferences",
                    "/api/preferences",
                    body,
                  )
                }
              />
              <section className="memory-sheet">
                <p className="eyebrow">PRIVATE, PERSISTENT MEMORY</p>
                <h2>What carries into next time.</h2>
                <p>
                  Corrections and reusable procedures remain with {ownerName}’s
                  local agent. Structured input is private; it is not sent to a
                  model.
                </p>
                <h3>
                  <ListChecks size={18} />
                  Owner-approved procedures
                </h3>
                {s.skills.length ? (
                  s.skills.map((skill, i) => {
                    const r =
                      skill &&
                      typeof skill === "object" &&
                      !Array.isArray(skill)
                        ? skill
                        : {};
                    return (
                      <article className="skill-item" key={i}>
                        <span>
                          <ShieldCheck size={18} />
                          <strong>{String(r.name || "Owner procedure")}</strong>
                        </span>
                        <p>
                          {String(r.scope || "Scope recorded in the procedure")}
                        </p>
                        <JsonDetails
                          title="Procedure, scope and provenance"
                          value={skill}
                        />
                      </article>
                    );
                  })
                ) : (
                  <p className="muted">No approved procedures are stored.</p>
                )}
                <h3>
                  <History size={18} />
                  Your corrections
                </h3>
                {s.corrections.length ? (
                  <ol className="correction-list">
                    {[...s.corrections].reverse().map((correction, i) => (
                      <li key={i}>
                        <JsonDetails
                          title={`Stored correction ${s.corrections.length - i}`}
                          value={correction}
                        />
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="muted">
                    No preference corrections yet. Your next saved correction
                    will be retained here.
                  </p>
                )}
                <div className="boundary-note">
                  <KeyRound size={18} />
                  <p>
                    Saving a correction increments your constraint revision and
                    invalidates dependent releases and approvals. A fresh offer
                    must be reviewed before the next plan.
                  </p>
                </div>
              </section>
            </div>
          ) : null}
          {tab === "calendar" ? (
            <div className="calendar-layout">
              <section className="calendar-sheet">
                <div className="section-topline">
                  <div>
                    <p className="eyebrow">ACTUAL LOCAL CALENDAR STATE</p>
                    <h2>A place for your commitments.</h2>
                  </div>
                  <button
                    className="button secondary compact"
                    disabled={exporting}
                    onClick={() => void exportCalendar()}
                  >
                    <ArrowDownToLine size={16} />
                    Export .ics
                  </button>
                </div>
                <p className="section-intro">
                  These are real durable entries in this sample owner’s
                  independent local calendar store. No Google Calendar or real
                  account is connected.
                </p>
                {eventRemoved ? (
                  <div className="notice owner-removal-receipt" role="status">
                    <Check size={20} />
                    <div>
                      <strong>
                        The selected local event was removed by its owner.
                      </strong>
                      <p>
                        Return to the shared agreement and choose Reconcile to
                        update its remaining effects and finish recovery.
                      </p>
                      <a href="http://127.0.0.1:4301" className="owner-link">
                        Return to our agreement
                        <ArrowUpRight size={15} />
                      </a>
                    </div>
                  </div>
                ) : null}
                {s.calendar_events.length ? (
                  <ul className="calendar-event-list">
                    {s.calendar_events.map((event) => (
                      <CalendarEventRow
                        key={event.event_id}
                        event={event}
                        busy={busy}
                        edit={(summary) =>
                          act(
                            "Applying a local user calendar edit",
                            `/api/calendar/${encodeURIComponent(event.event_id)}/edit`,
                            { summary },
                          )
                        }
                        remove={async (expected_etag) => {
                          const ok = await act(
                            "Removing the exact local event you confirmed",
                            `/api/calendar/${encodeURIComponent(event.event_id)}/remove`,
                            {
                              expected_etag,
                              confirmation: "remove-this-local-event",
                            },
                          );
                          if (ok) {
                            setEventRemoved(true);
                            requestAnimationFrame(() =>
                              document
                                .querySelector<HTMLElement>(
                                  ".calendar-sheet h2",
                                )
                                ?.focus(),
                            );
                          }
                          return ok;
                        }}
                      />
                    ))}
                  </ul>
                ) : (
                  <div className="empty-state">
                    <CalendarDays size={30} />
                    <h3>No agreement entries yet.</h3>
                    <p>
                      Verified entries appear after all owners approve and the
                      broker enacts the agreement.
                    </p>
                  </div>
                )}
                <h3 className="subsection-title">
                  Private source availability
                </h3>
                <p className="muted">
                  This owner’s authored private source entries. Their titles are
                  never part of the shared offer.
                </p>
                <ul className="private-source-list">
                  {s.private_calendar.map((event) => (
                    <li key={event.source_id}>
                      <LockKeyhole size={17} />
                      <div>
                        <strong>{event.title}</strong>
                        <span>
                          {time(event.start)}—{time(event.end)} · {event.date}
                        </span>
                      </div>
                      <Pill>Private source</Pill>
                    </li>
                  ))}
                </ul>
              </section>
              <aside className="fault-panel">
                <FlaskConical size={25} />
                <p className="eyebrow">LABELED FAULT FIXTURES</p>
                <h2>Try a real interruption.</h2>
                <p>
                  These controls exercise the actual local adapter. A failure
                  does not become a successful calendar receipt.
                </p>
                <label htmlFor="fault-mode">
                  This owner’s calendar adapter behavior
                </label>
                <select
                  id="fault-mode"
                  value={faultMode}
                  disabled={Boolean(busy)}
                  onChange={(e) =>
                    void act("Changing the local fault fixture", "/api/fault", {
                      mode: e.target.value,
                    })
                  }
                >
                  {faultOptions.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <div className="fault-explanation">
                  <CircleAlert size={19} />
                  <p>
                    {faultOptions.find(([value]) => value === faultMode)?.[2] ||
                      faultMode}
                  </p>
                </div>
                <p className="fine-print">
                  The selected fault persists locally. Return it to normal
                  operation before testing a recovery that needs a new write.
                </p>
                <a className="button secondary" href="http://127.0.0.1:4301">
                  Inspect shared action receipts
                  <ArrowUpRight size={16} />
                </a>
              </aside>
            </div>
          ) : null}
          <footer className="workspace-footer">
            <span>
              <Mark small />
              {ownerName}’s owner-local space
            </span>
            <span>Fictional sample · private to this paired service</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
function PreferencesForm({
  state,
  busy,
  save,
}: {
  state: OwnerState;
  busy: string;
  save: (body: object) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<Preferences>(state.preferences);
  const [baseRevision, setBaseRevision] = useState(state.constraint_revision);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const stale = baseRevision !== state.constraint_revision;
  useEffect(() => {
    if (!dirty) {
      setDraft(state.preferences);
      setBaseRevision(state.constraint_revision);
    }
  }, [state.constraint_revision, dirty]);
  function update<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setDraft((old) => ({ ...old, [key]: value }));
    setDirty(true);
    setSaved(false);
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await save({
      expected_revision: baseRevision,
      availability_start: draft.availability_start,
      availability_end: draft.availability_end,
      task_ids: draft.task_ids,
      ask_before_driving: draft.ask_before_driving,
      preference_cost: draft.preference_cost ?? 0,
      private_note: draft.private_note || "",
    });
    if (ok) {
      setDirty(false);
      setSaved(true);
    }
  }
  const tasks = ["prepare", "outbound", "accompany", "return", "handoff"];
  return (
    <section className="preferences-sheet">
      <p className="eyebrow">PRIVATE STRUCTURED PREFERENCES</p>
      <h2>Tell your agent what works.</h2>
      <p className="section-intro">
        No remote private extraction is configured. These structured fields and
        your private note stay inside this owner’s service.
      </p>
      {stale && dirty ? (
        <div className="notice warning">
          <CircleAlert size={18} />
          <div>
            <strong>Your local state changed.</strong>
            <p>
              Your draft is preserved. Reload the current preferences before
              saving against a new revision.
            </p>
            <button
              className="text-button"
              onClick={() => {
                setDraft(state.preferences);
                setBaseRevision(state.constraint_revision);
                setDirty(false);
              }}
            >
              Load current revision {state.constraint_revision}
            </button>
          </div>
        </div>
      ) : null}
      <form onSubmit={submit}>
        <fieldset>
          <legend>My available window · 2 November 2026</legend>
          <div className="time-inputs">
            <label>
              Available from
              <input
                type="time"
                required
                value={time(draft.availability_start)}
                onChange={(e) => {
                  const [h, m] = e.target.value.split(":").map(Number);
                  update("availability_start", h * 60 + m);
                }}
              />
            </label>
            <span>to</span>
            <label>
              Available until
              <input
                type="time"
                required
                value={time(draft.availability_end)}
                onChange={(e) => {
                  const [h, m] = e.target.value.split(":").map(Number);
                  update("availability_end", h * 60 + m);
                }}
              />
            </label>
          </div>
          <p className="field-hint">
            Asia/Kolkata · this is the broad window you may choose to release.
          </p>
        </fieldset>
        <fieldset>
          <legend>Responsibilities I’m willing to offer</legend>
          <div className="task-options">
            {tasks.map((task) => (
              <label className="task-option" key={task}>
                <input
                  type="checkbox"
                  checked={draft.task_ids.includes(task)}
                  onChange={(e) =>
                    update(
                      "task_ids",
                      e.target.checked
                        ? [...draft.task_ids, task]
                        : draft.task_ids.filter((t) => t !== task),
                    )
                  }
                />
                <span>{words(task)}</span>
              </label>
            ))}
          </div>
          <p className="field-hint">
            Local capabilities and private conflicts still apply to every
            approval.
          </p>
        </fieldset>
        <fieldset>
          <legend>How much extra help can I take?</legend>
          <label className="preference-weight-label" htmlFor="preference-cost">
            My explicit burden weight
          </label>
          <input
            id="preference-cost"
            type="number"
            min={0}
            max={100}
            step={1}
            value={draft.preference_cost ?? 0}
            onChange={(event) =>
              update("preference_cost", Number(event.target.value))
            }
          />
          <p className="field-hint">
            0–100, chosen by you. Lower weights are preferred after preserving
            existing commitments. This number is included in a reviewed release;
            your reason stays private.
          </p>
        </fieldset>
        <label className="consent-choice">
          <input
            type="checkbox"
            checked={draft.ask_before_driving}
            onChange={(e) => update("ask_before_driving", e.target.checked)}
          />
          <span>
            <strong>Always ask me before a driving commitment</strong>
            <small>
              A durable preference. It never replaces exact individual approval.
            </small>
          </span>
        </label>
        <label className="note-label" htmlFor="private-note">
          <LockKeyhole size={15} />A private note to my local agent
        </label>
        <textarea
          id="private-note"
          rows={4}
          value={draft.private_note || ""}
          onChange={(e) => update("private_note", e.target.value)}
          placeholder="Your reason is yours. This note is never released."
          maxLength={2000}
        />
        <p className="field-hint">
          Optional. Not sent to the circle, broker, or Fireworks.
        </p>
        <div className="preference-save">
          <p>
            <ShieldCheck size={17} />
            Saving invalidates dependent offers and approvals. You’ll review a
            fresh release afterward.
          </p>
          <button
            className="button primary"
            disabled={
              Boolean(busy) ||
              !dirty ||
              stale ||
              draft.availability_end <= draft.availability_start ||
              !draft.task_ids.length
            }
          >
            <Check size={17} />
            Save my private preferences
          </button>
          {saved ? (
            <span className="saved-message" role="status">
              <Check size={16} />
              Saved in your local agent.
            </span>
          ) : null}
        </div>
      </form>
    </section>
  );
}
function CalendarEventRow({
  event,
  busy,
  edit,
  remove,
}: {
  event: CalendarEvent;
  busy: string;
  edit: (summary: string) => Promise<boolean>;
  remove: (etag: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const editTrigger = useRef<HTMLButtonElement>(null);
  const editInput = useRef<HTMLInputElement>(null);
  const wasEditing = useRef(false);
  useEffect(() => {
    if (editing) editInput.current?.focus();
    else if (wasEditing.current) editTrigger.current?.focus();
    wasEditing.current = editing;
  }, [editing]);
  const [summary, setSummary] = useState(event.summary);
  const [removeTarget, setRemoveTarget] = useState<CalendarEvent | null>(null);
  return (
    <li>
      <div className="calendar-event-time">
        <strong>{time(event.start)}</strong>
        <span>{time(event.end)}</span>
      </div>
      <div className="calendar-event-content">
        <h3>{event.summary}</h3>
        <p>
          {event.date} · {event.timezone || "Asia/Kolkata"}
        </p>
        <small>
          Event {short(event.event_id)} · ETag {short(event.etag)}
        </small>
        {event.user_edited === true ? (
          <Pill tone="warning">
            User edited · preserved until your decision
          </Pill>
        ) : null}
        {editing ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (await edit(summary)) setEditing(false);
            }}
          >
            <label htmlFor={`edit-${event.event_id}`}>
              Local user-edit fixture · event summary
            </label>
            <input
              ref={editInput}
              id={`edit-${event.event_id}`}
              required
              maxLength={200}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
            />
            <p className="field-hint">
              A real local edit changes the ETag. Conditional cancellation must
              preserve this edited entry.
            </p>
            <div>
              <button
                className="button secondary compact"
                disabled={Boolean(busy)}
              >
                Apply local user edit
              </button>
              <button
                type="button"
                className="text-button"
                onClick={() => setEditing(false)}
              >
                Keep current entry
              </button>
            </div>
          </form>
        ) : (
          <button
            ref={editTrigger}
            className="text-button"
            onClick={() => {
              setSummary(event.summary);
              setEditing(true);
            }}
          >
            Try a local user edit
            <ChevronDown size={15} />
          </button>
        )}
        <button
          className="text-button remove-event-button"
          disabled={Boolean(busy) || !event.etag}
          onClick={() => setRemoveTarget({ ...event })}
        >
          Remove local event
          <Undo2 size={15} />
        </button>
        {removeTarget ? (
          <RemoveEventDialog
            event={removeTarget}
            currentEtag={event.etag}
            busy={busy}
            close={() => setRemoveTarget(null)}
            remove={remove}
          />
        ) : null}
      </div>
    </li>
  );
}
function RemoveEventDialog({
  event,
  currentEtag,
  busy,
  close,
  remove,
}: {
  event: CalendarEvent;
  currentEtag: string | undefined;
  busy: string;
  close: () => void;
  remove: (etag: string) => Promise<boolean>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const stale = event.etag !== currentEtag;
  const [failure, setFailure] = useState("");
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
      aria-labelledby={`remove-title-${event.event_id}`}
      onCancel={(event) => {
        if (busy) event.preventDefault();
        else close();
      }}
    >
      <section className="confirm-sheet remove-event-dialog">
        <p className="eyebrow">YOUR EXPLICIT OWNER DECISION</p>
        <h2 id={`remove-title-${event.event_id}`}>Remove this local event?</h2>
        <div className="event-removal-target">
          <h3>{event.summary}</h3>
          <p>
            {time(event.start)}—{time(event.end)} · {event.date} ·{" "}
            {event.timezone || "Asia/Kolkata"}
          </p>
          <dl>
            <dt>Exact event</dt>
            <dd className="digest">{event.event_id}</dd>
            <dt>Current ETag</dt>
            <dd className="digest">{event.etag}</dd>
          </dl>
        </div>
        <p>
          This permanently removes this one entry from your local sample
          calendar. The broker preserves a user-edited event until you make this
          explicit decision. No other event is removed.
        </p>
        <p>
          After removal, return to the shared agreement and choose Reconcile to
          finish recovery.
        </p>
        {stale ? (
          <ErrorNotice message="The event changed while this confirmation was open. Keep it and reopen the current event before deciding." />
        ) : null}
        {failure ? <ErrorNotice message={failure} /> : null}
        <div>
          <button
            autoFocus
            className="button secondary"
            disabled={Boolean(busy)}
            onClick={close}
          >
            Keep this event
          </button>
          <button
            className="button danger"
            disabled={Boolean(busy) || stale || !event.etag}
            onClick={async () => {
              if (event.etag) {
                if (await remove(event.etag)) close();
                else
                  setFailure(
                    "This event was not removed. Keep this event to return and review the local service response.",
                  );
              }
            }}
          >
            {busy ? "Removing local event…" : "Remove this local event"}
          </button>
        </div>
      </section>
    </dialog>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
