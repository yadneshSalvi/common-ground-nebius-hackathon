import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  CircleAlert,
  FileCheck2,
  HeartHandshake,
  LockKeyhole,
  Pencil,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  Avatar,
  Brand,
  ErrorBanner,
  Json,
  PairForm,
  Tag,
  Wait,
  clock,
  list,
  ownerId,
  person,
  readable,
  stamp,
  useLiving,
  type Data,
  type LivingService,
} from "../web/living";
export default function LivingOwnerApp() {
  const service = useLiving("owner"),
    { state: s, busy, stale } = service;
  const [tab, setTab] = useState("decisions"),
    [selected, setSelected] = useState<string[]>([]),
    [withdrawReview, setWithdrawReview] = useState(false);
  const [provider, setProvider] = useState("none"),
    [preview, setPreview] = useState<Data | null>(null),
    [releaseReview, setReleaseReview] = useState(false),
    [approveReview, setApproveReview] = useState(false),
    [recordedApproval, setRecordedApproval] = useState<Data | null>(null);
  const id = s ? ownerId(s.owner) : undefined;
  const name = s?.owner?.name || (id ? person(id) : "Your owner");
  useEffect(() => {
    setApproveReview(false);
  }, [s?.pending_digest]);
  useEffect(() => {
    setPreview(null);
    setReleaseReview(false);
  }, [s?.revision]);
  const goal =
      list(s?.goals).find((g) => g.goal_id === s?.pending?.goal?.goal_id) ||
      list(s?.goals).at(-1),
    pending = s?.pending,
    agreement = s?.agreement,
    withdrawn = s?.withdrawn?.[agreement?.agreement_id] || [],
    own = list(agreement?.commitments).filter(
      (c) => c.owner_id === id && !withdrawn.includes(c.commitment_id),
    ),
    proposed = list(pending?.commitments).filter((c) => c.owner_id === id);
  const approvedPayload = recordedApproval?.consent?.body?.payload;
  const approvalMatchesCurrent = !!(
    recordedApproval &&
    pending &&
    recordedApproval.consent.body.issuer === id &&
    approvedPayload?.owner_id === id &&
    approvedPayload.agreement_id === pending.agreement_id &&
    approvedPayload.revision === pending.revision &&
    approvedPayload.agreement_digest === s?.pending_digest &&
    approvedPayload.consent_revision === s?.consent_revision &&
    recordedApproval.owner_constraint_revision === s?.constraint_revision
  );
  const approvalRecorded =
    approvalMatchesCurrent &&
    !stale &&
    Date.parse(approvedPayload.execution_not_after) > Date.now() &&
    Date.parse(recordedApproval!.consent.body.expires_at) > Date.now();
  useEffect(() => {
    if (recordedApproval && !approvalMatchesCurrent) {
      setRecordedApproval(null);
      setApproveReview(false);
    }
  }, [recordedApproval, approvalMatchesCurrent]);
  async function getPreview() {
    setPreview(null);
    setReleaseReview(false);
    try {
      const { value, headers } = await service.request(
        `/api/v2/offer-preview?goal_id=${encodeURIComponent(goal?.goal_id || "")}&provider=${provider}`,
      );
      setPreview({
        ...value,
        preview_digest: value.preview_digest || headers.get("X-Preview-Digest"),
      });
    } catch (e) {
      service.setError(
        e instanceof Error ? e.message : "Release preview is unavailable",
      );
    }
  }
  return (
    <div className="cg-app cg-owner-app">
      <a className="cg-skip" href="#main">
        Skip to my decisions
      </a>
      <header className="cg-header">
        <a href={s?.broker_ui_url || "/"}>
          <Brand />
        </a>
        <nav aria-label="Owner navigation">
          <button
            className={tab === "decisions" ? "selected" : ""}
            onClick={() => setTab("decisions")}
          >
            <HeartHandshake size={16} />
            My decisions
          </button>
          <button
            className={tab === "memory" ? "selected" : ""}
            onClick={() => setTab("memory")}
          >
            <LockKeyhole size={16} />
            Private memory
          </button>
          <button
            className={tab === "calendar" ? "selected" : ""}
            onClick={() => setTab("calendar")}
          >
            <CalendarDays size={16} />
            My calendar
          </button>
        </nav>
        <div className="cg-header-end">
          <Tag tone="private">{name}’s private space</Tag>
          {service.paired ? (
            <button
              className="cg-icon"
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
                ? "Your private space is unavailable."
                : "Opening your private space…"}
            </h1>
            <p>
              {service.error
                ? "Reconnect using the notice above to restore current owner state."
                : "Restoring this owner service’s current decisions."}
            </p>
          </section>
        ) : !s ? (
          <section className="cg-owner-entry">
            <div className="cg-owner-entry-icon">
              <Avatar id={id} />
              <LockKeyhole size={24} />
            </div>
            <p className="cg-eyebrow">A SEPARATE OWNER SERVICE</p>
            <h1>
              Your part.
              <br />
              <em>Your decision.</em>
            </h1>
            <p>
              Review what you offer, remember what matters to you, and approve
              your exact responsibilities here.
            </p>
            <button
              className="cg-button"
              disabled={!!busy}
              onClick={() => void service.pair(true)}
            >
              Enter this fictional owner space <ArrowRight size={17} />
            </button>
            <p className="cg-caption">
              For this explicitly fictional installation only. This service
              issues its own owner session; the shared room receives no owner
              credentials.
            </p>
            <PairForm owner service={service} />
            {busy ? <Wait label={busy} /> : null}
          </section>
        ) : (
          <>
            {!service.paired ? (
              <div className="cg-notice warning">
                <LockKeyhole size={19} />
                <div>
                  <strong>
                    Re-enter this owner service to make fresh decisions.
                  </strong>
                  <div className="cg-actions">
                    <button
                      className="cg-button secondary"
                      onClick={() => void service.pair(true)}
                    >
                      Re-enter fictional owner space
                    </button>
                    <PairForm owner service={service} />
                  </div>
                </div>
              </div>
            ) : null}
            <div className="cg-context">
              <a href={s?.broker_ui_url || "/"}>
                <ArrowLeft size={14} />
                Back to the shared arrangement
              </a>
              <span>
                <LockKeyhole size={12} />
                {stale
                  ? "Historical · reconnect to observe"
                  : "Private to this paired service"}
              </span>
            </div>
            <section className="cg-page-head">
              <div>
                <p className="cg-eyebrow">
                  {name.toUpperCase()}’S OWNER SPACE · FICTIONAL SAMPLE
                </p>
                <h1>
                  {tab === "memory"
                    ? "What matters to you, remembered."
                    : tab === "calendar"
                      ? "Your commitments, observed."
                      : "You choose what you can give."}
                </h1>
                <p>
                  {tab === "memory"
                    ? "Reviewed structured rules guide your next offer. Your private reasons stay here."
                    : tab === "calendar"
                      ? "App-created calendar entries and their actual observation receipts."
                      : "A shared arrangement works when everyone has their own say."}
                </p>
              </div>
              <Avatar id={id} />
            </section>
            {s.coordinator_available === false ? (
              <div className="cg-notice warning">
                <CircleAlert size={19} />
                <div>
                  <strong>The shared coordinator is unavailable.</strong>
                  <p>
                    Local private memory remains accessible. Shared decisions
                    and coverage need a fresh observation when the coordinator
                    reconnects.
                  </p>
                </div>
              </div>
            ) : null}
            {tab === "decisions" ? (
              <div className="cg-layout">
                <div className="cg-main-column">
                  <section className="cg-paper">
                    <div className="cg-sheet-top">
                      <span className="cg-eyebrow">
                        YOUR CURRENT RESPONSIBILITIES
                      </span>
                      <Tag>
                        {agreement
                          ? `Revision ${agreement.revision}`
                          : "No agreement yet"}
                      </Tag>
                    </div>
                    <h2>
                      {goal?.title || "Start with a shared reviewed goal."}
                    </h2>
                    {own.length ? (
                      <>
                        <p>
                          Something changed? You can withdraw one part while
                          keeping the others. No reason is sent to the circle.
                        </p>
                        <ul className="cg-withdraw-list">
                          {own.map((c) => (
                            <li key={c.commitment_id}>
                              <label>
                                <input
                                  type="checkbox"
                                  checked={selected.includes(c.commitment_id)}
                                  onChange={(e) => {
                                    setWithdrawReview(false);
                                    setSelected(
                                      e.target.checked
                                        ? [...selected, c.commitment_id]
                                        : selected.filter(
                                            (x) => x !== c.commitment_id,
                                          ),
                                    );
                                  }}
                                />
                                <div>
                                  <strong>{c.label}</strong>
                                  <span>
                                    {clock(c.start)}–{clock(c.end)} · {c.date}
                                  </span>
                                  <small>
                                    {c.start_location} → {c.end_location}
                                  </small>
                                </div>
                              </label>
                              <Tag>Committed</Tag>
                            </li>
                          ))}
                        </ul>
                        {!withdrawReview ? (
                          <button
                            className="cg-button secondary"
                            disabled={!selected.length || !!busy || stale}
                            onClick={() => setWithdrawReview(true)}
                          >
                            Review selected withdrawal <ArrowRight size={15} />
                          </button>
                        ) : (
                          <div className="cg-notice warning">
                            <CircleAlert size={21} />
                            <div>
                              <strong>
                                Withdraw only {selected.length} selected{" "}
                                {selected.length === 1
                                  ? "responsibility"
                                  : "responsibilities"}
                                ?
                              </strong>
                              <p>
                                Your other commitments remain. The shared
                                arrangement will need fresh coverage for these
                                pieces. Your private reason is not requested or
                                released.
                              </p>
                              <div className="cg-actions">
                                <button
                                  className="cg-button danger"
                                  disabled={!!busy || stale}
                                  onClick={async () => {
                                    if (
                                      await service.act(
                                        "Withdrawing only your selected responsibilities",
                                        "/api/v2/withdraw",
                                        {
                                          agreement_id: agreement.agreement_id,
                                          base_revision: agreement.revision,
                                          commitment_ids: selected,
                                          expected_revision: s.revision,
                                        },
                                      )
                                    ) {
                                      setSelected([]);
                                      setWithdrawReview(false);
                                    }
                                  }}
                                >
                                  Withdraw selected parts
                                </button>
                                <button
                                  className="cg-text"
                                  onClick={() => setWithdrawReview(false)}
                                >
                                  Keep my commitments
                                </button>
                              </div>
                            </div>
                          </div>
                        )}
                      </>
                    ) : (
                      <p>No current responsibilities are assigned to you.</p>
                    )}
                  </section>
                  {pending ? (
                    <section className="cg-paper cg-owner-proposal">
                      <div className="cg-sheet-top">
                        <span className="cg-eyebrow">A FRESH EXACT REVIEW</span>
                        <Tag>Revision {pending.revision}</Tag>
                      </div>
                      <h2>Your part in the next arrangement.</h2>
                      <p>
                        Review your responsibilities and direct counterparts
                        together. A changed handoff needs your fresh review even
                        when your own time remains the same.
                      </p>
                      {proposed.length ? (
                        proposed.map((c) => (
                          <div className="cg-own-part" key={c.commitment_id}>
                            <h3>{c.label}</h3>
                            <p>
                              <strong>
                                {clock(c.start)}–{clock(c.end)}
                              </strong>{" "}
                              · {c.date} · {c.timezone}
                            </p>
                            <p>
                              {c.start_location} → {c.end_location}
                            </p>
                            {list(c.dependencies).map((d, i) => (
                              <div className="cg-dependency" key={i}>
                                <Avatar id={d.owner_id} />
                                <div>
                                  <strong>
                                    {person(d.owner_id)} ·{" "}
                                    {d.label ||
                                      list(goal?.tasks).find(
                                        (t) => t.task_id === d.task_id,
                                      )?.label ||
                                      "Connected responsibility"}
                                  </strong>
                                  <span>
                                    {d.date} · {clock(d.start)}–{clock(d.end)} ·{" "}
                                    {d.start_location} → {d.end_location}
                                  </span>
                                </div>
                              </div>
                            ))}
                            <Json
                              value={c}
                              label="Inspect this exact commitment and dependency bindings"
                            />
                          </div>
                        ))
                      ) : (
                        <p>
                          This revision removes your former part. Review the
                          removed effects in the exact delta below.
                        </p>
                      )}
                      <Json
                        value={pending.delta}
                        label="Inspect exact calendar changes and retained effects"
                      />
                      {approvalRecorded ? (
                        <div
                          className="cg-notice"
                          role="status"
                          aria-live="polite"
                        >
                          <Check size={19} />
                          <div>
                            <strong>
                              Your approval is recorded for revision{" "}
                              {pending.revision}.
                            </strong>
                            <p>
                              This approves your exact part. Applying the
                              arrangement and verifying calendar effects are
                              separate steps.
                            </p>
                          </div>
                        </div>
                      ) : null}
                      <label className="cg-checkbox cg-review-confirm">
                        <input
                          type="checkbox"
                          checked={approvalRecorded || approveReview}
                          disabled={approvalRecorded || !!busy || stale}
                          onChange={(e) => setApproveReview(e.target.checked)}
                        />
                        <span>
                          I reviewed this exact revision, my responsibilities,
                          direct handoffs and calendar effects. I approve my
                          part until the agreement’s execution deadline.
                        </span>
                      </label>
                      <button
                        className="cg-button"
                        disabled={
                          approvalRecorded ||
                          !approveReview ||
                          !!busy ||
                          stale ||
                          !s.pending_digest
                        }
                        onClick={async () => {
                          const submitted = {
                            agreement_id: pending.agreement_id,
                            revision: pending.revision,
                            agreement_digest: s.pending_digest,
                          };
                          const result = await service.act(
                            "Recording your exact owner approval",
                            "/api/v2/approve",
                            submitted,
                          );
                          if (result) {
                            const consent = result.consent;
                            const signed = consent?.body?.payload;
                            if (
                              consent?.signature &&
                              consent.body.issuer === id &&
                              signed?.owner_id === id &&
                              signed.agreement_id === submitted.agreement_id &&
                              signed.revision === submitted.revision &&
                              signed.agreement_digest ===
                                submitted.agreement_digest
                            ) {
                              setRecordedApproval({
                                consent,
                                owner_constraint_revision:
                                  s.constraint_revision,
                              });
                              setApproveReview(false);
                            } else
                              service.setError(
                                "The service returned no matching signed approval. Refresh your owner state before deciding again.",
                              );
                          }
                        }}
                      >
                        {approvalRecorded
                          ? "Approval recorded"
                          : "Approve my exact part"}{" "}
                        <Check size={17} />
                      </button>
                      {!s.pending_digest ? (
                        <p className="cg-caption">
                          An exact agreement digest is required before approval
                          is available.
                        </p>
                      ) : null}
                    </section>
                  ) : null}
                  <section className="cg-paper">
                    <p className="cg-eyebrow">REVIEW BEFORE YOU RELEASE</p>
                    <h2>Here’s what you can offer.</h2>
                    <p>
                      Your agent uses only confirmed structured memory and the
                      reviewed goal. Preview the exact public offer, people,
                      provider and conditions before releasing it.
                    </p>
                    {goal ? (
                      <>
                        <label>
                          Where this public offer may be used
                          <select
                            aria-label="Offer provider"
                            value={provider}
                            onChange={(e) => {
                              setProvider(e.target.value);
                              setPreview(null);
                              setReleaseReview(false);
                            }}
                          >
                            <option value="none">
                              Circle & broker only · no inference
                            </option>
                            <option value="fireworks">
                              Circle, broker & Fireworks
                            </option>
                            <option value="nebius">
                              Circle, broker & Nebius
                            </option>
                          </select>
                        </label>
                        <button
                          className="cg-button secondary"
                          disabled={!!busy || stale}
                          onClick={() => void getPreview()}
                        >
                          Preview exact public offer <ArrowRight size={16} />
                        </button>
                        {preview ? (
                          <div className="cg-release-preview">
                            <h3>Your public release</h3>
                            <OfferPreview
                              release={preview.release || preview}
                              goal={goal}
                            />
                            <Json
                              value={preview.release}
                              label="Inspect exact release fields"
                            />
                            {preview.private_explanation ? (
                              <details className="cg-private-explanation">
                                <summary>
                                  <LockKeyhole size={14} />
                                  Private explanation · stays in this service
                                </summary>
                                {typeof preview.private_explanation ===
                                "string" ? (
                                  <p>{preview.private_explanation}</p>
                                ) : (
                                  <Json
                                    value={preview.private_explanation}
                                    label="Inspect private explanation"
                                  />
                                )}
                              </details>
                            ) : null}
                            <label className="cg-checkbox cg-review-confirm">
                              <input
                                type="checkbox"
                                checked={releaseReview}
                                onChange={(e) =>
                                  setReleaseReview(e.target.checked)
                                }
                              />
                              <span>
                                I reviewed the tasks, windows, conditions, human
                                recipients and{" "}
                                {provider === "none"
                                  ? "absence of inference access"
                                  : `${person(provider)} inference access`}{" "}
                                in this exact release.
                              </span>
                            </label>
                            <button
                              className="cg-button"
                              disabled={
                                !releaseReview ||
                                !!busy ||
                                stale ||
                                !preview.preview_digest
                              }
                              onClick={async () => {
                                if (
                                  await service.act(
                                    "Releasing only the reviewed public offer",
                                    "/api/v2/release",
                                    {
                                      goal_id: goal.goal_id,
                                      provider,
                                      preview_digest: preview.preview_digest,
                                      expected_revision: s.revision,
                                    },
                                  )
                                ) {
                                  setPreview(null);
                                  setReleaseReview(false);
                                }
                              }}
                            >
                              Release this exact offer <ArrowRight size={16} />
                            </button>
                          </div>
                        ) : null}
                      </>
                    ) : (
                      <p>
                        A confirmed shared goal must reach this owner service
                        before an offer can be prepared.
                      </p>
                    )}
                  </section>
                  {list(s.requests).filter(
                    (r) =>
                      r.goal_id === goal?.goal_id &&
                      (!s.current_disruption_id ||
                        r.disruption_id === s.current_disruption_id),
                  ).length ? (
                    <section className="cg-paper">
                      <p className="cg-eyebrow">INVITATIONS, NOT OBLIGATIONS</p>
                      <h2>Requests for your help.</h2>
                      {list(s.requests)
                        .filter(
                          (r) =>
                            r.goal_id === goal?.goal_id &&
                            (!s.current_disruption_id ||
                              r.disruption_id === s.current_disruption_id),
                        )
                        .map((r) => (
                          <div className="cg-request-card" key={r.request_id}>
                            <h3>
                              {r.label ||
                                list(goal?.tasks).find(
                                  (t) => t.task_id === r.task_id,
                                )?.label ||
                                "An alternative arrangement"}
                            </h3>
                            <p>
                              {r.question ||
                                r.message ||
                                "The circle is asking whether you can offer this piece. Your current private permission and refusal scope apply."}
                            </p>
                            <Tag>
                              {r.status === "accepted"
                                ? "Request received"
                                : readable(r.status)}
                            </Tag>
                            {r.status === "accepted" ? (
                              <p className="cg-caption">
                                Your reviewed offer and exact approval are still
                                required.
                              </p>
                            ) : null}
                            <div className="cg-actions">
                              {r.status === "invitation_pending" ? (
                                <button
                                  className="cg-button"
                                  disabled={!!busy || stale}
                                  onClick={() =>
                                    void service.act(
                                      "Accepting a fresh invitation for this request",
                                      "/api/v2/requests/" +
                                        encodeURIComponent(r.request_id) +
                                        "/accept-invitation",
                                      { expected_revision: s.revision },
                                    )
                                  }
                                >
                                  Accept this fresh invitation
                                </button>
                              ) : null}
                              <button
                                className="cg-button secondary"
                                disabled={
                                  !!busy || stale || r.status !== "accepted"
                                }
                                onClick={() =>
                                  void service.act(
                                    "Declining this invitation without a public reason",
                                    "/api/v2/refuse",
                                    {
                                      request_id: r.request_id,
                                      expected_revision: s.revision,
                                    },
                                  )
                                }
                              >
                                Decline this request
                              </button>
                              <button
                                className="cg-text"
                                onClick={() => setTab("memory")}
                              >
                                Review what I can offer <ArrowRight size={14} />
                              </button>
                            </div>
                          </div>
                        ))}
                    </section>
                  ) : null}
                </div>
                <aside className="cg-aside">
                  <section className="cg-circle">
                    <LockKeyhole size={25} />
                    <h2>
                      Your reasons
                      <br />
                      are yours.
                    </h2>
                    <p>
                      Your note and structured memories stay here. Only the
                      exact public release and your signed decisions go to the
                      shared room.
                    </p>
                    <div className="cg-owner-tip">
                      <ShieldCheck size={19} />
                      <div>
                        <strong>Changed counterpart?</strong>
                        <p>
                          That’s a changed responsibility, even if your time
                          stays the same. Review the new direct handoff before
                          approving.
                        </p>
                      </div>
                    </div>
                    <button
                      className="cg-text"
                      onClick={() => setTab("memory")}
                    >
                      Review private memory <ArrowRight size={15} />
                    </button>
                  </section>
                  <Policy service={service} />
                </aside>
              </div>
            ) : tab === "memory" ? (
              <Memory service={service} />
            ) : (
              <Calendar service={service} />
            )}
            {busy ? (
              <div className="cg-sticky-status">
                <Wait label={busy} />
              </div>
            ) : null}
          </>
        )}
        <footer className="cg-footer">
          <Brand />
          <span>{name}’s separate owner service · fictional sample</span>
          <a href="?legacy=1">Recorded / legacy owner workflow</a>
        </footer>
      </main>
    </div>
  );
}
function OfferPreview({ release: r, goal }: { release: Data; goal?: Data }) {
  const p = r.body?.payload || r.payload || r;
  const taskLabel = (id: string) =>
    list(goal?.tasks).find((t) => t.task_id === id)?.label ||
    "Specified responsibility";
  return (
    <>
      <dl className="cg-release-facts">
        <div>
          <dt>Responsibilities</dt>
          <dd>
            {(p.task_ids || [])
              .map(
                (id: string) =>
                  list(goal?.tasks).find((t) => t.task_id === id)?.label ||
                  "Responsibility awaiting goal details",
              )
              .join(", ") || "None"}
          </dd>
        </div>
        <div>
          <dt>Human recipients</dt>
          <dd>
            {(p.recipients?.humans || []).map(person).join(", ") || "None"}
          </dd>
        </div>
        <div>
          <dt>Inference recipients</dt>
          <dd>
            {(p.recipients?.inference || []).map(person).join(", ") || "None"}
          </dd>
        </div>
        <div>
          <dt>Coordination recipient</dt>
          <dd>
            {p.recipients?.broker ? "Shared coordination service" : "None"}
          </dd>
        </div>
        <div>
          <dt>Expires</dt>
          <dd>{stamp(p.expires_at)}</dd>
        </div>
      </dl>
      {list(p.windows).map((w, i) => (
        <p key={i}>
          <strong>Available window:</strong> {w.date} · {clock(w.start)}–
          {clock(w.end)}
        </p>
      ))}
      {list(p.conditions).map((c, i) => (
        <div className="cg-notice" key={i}>
          <HeartHandshake size={19} />
          <p>
            <strong>Condition:</strong> {person(c.receiver_id)} must take{" "}
            {taskLabel(c.receiver_task_id)} and finish by {clock(c.by)} on the
            offered task’s date. Applies to {taskLabel(c.task_id)}.
          </p>
        </div>
      ))}
    </>
  );
}
function Policy({ service }: { service: LivingService }) {
  const s = service.state!,
    [review, setReview] = useState(false),
    [expiry, setExpiry] = useState("");
  const enabled =
    !!s.policy?.enabled && Date.parse(s.policy.expires_at) > Date.now();
  return (
    <section className="cg-small-card">
      <ShieldCheck size={24} />
      <p className="cg-eyebrow">OPTIONAL OWNER POLICY</p>
      <h3>Carry forward unchanged parts?</h3>
      <Tag tone={enabled ? "good" : ""}>
        {enabled
          ? s.policy.provenance?.toLowerCase().includes("authored")
            ? "Authored sample policy enabled"
            : "Owner-enabled"
          : "Off by default"}
      </Tag>
      <p>
        A fresh policy attestation is allowed only when your content, direct
        counterparts, recipients, complete coverage and cancellation scope all
        remain unchanged. New or changed parts always need exact review.
      </p>
      {!enabled ? (
        <>
          <label>
            Policy expiry · required
            <input
              required
              type="datetime-local"
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
            />
          </label>
          <label className="cg-checkbox">
            <input
              type="checkbox"
              checked={review}
              onChange={(e) => setReview(e.target.checked)}
            />
            <span>I reviewed and enable this narrow standing policy.</span>
          </label>
        </>
      ) : null}
      <button
        className="cg-button secondary"
        disabled={
          !!service.busy ||
          service.stale ||
          (!enabled && (!review || !expiry || Date.parse(expiry) <= Date.now()))
        }
        onClick={() =>
          void service.act(
            enabled
              ? "Revoking the carry-forward policy"
              : "Saving your reviewed carry-forward policy",
            "/api/v2/policy",
            {
              expected_revision: s.revision,
              enabled: !enabled,
              expires_at: expiry ? new Date(expiry).toISOString() : null,
            },
          )
        }
      >
        {enabled ? "Revoke carry-forward policy" : "Enable reviewed policy"}
      </button>
    </section>
  );
}
const ruleNames: Record<string, string> = {
  excluded_capability: "Do not offer a capability",
  weekly_capacity: "Weekly capacity in minutes",
  request_category: "Permission for a request category",
  handoff_deadline: "Handoff deadline",
  require_receiver: "Require a named receiver",
};
function Memory({ service }: { service: LivingService }) {
  const s = service.state!,
    [editing, setEditing] = useState<Data | null>(null),
    [removing, setRemoving] = useState<string | null>(null);
  return (
    <div className="cg-memory-layout">
      <section className="cg-paper">
        <div className="cg-sheet-top">
          <p className="cg-eyebrow">REVIEWED STRUCTURED MEMORY</p>
          <Tag tone="private">
            <LockKeyhole size={12} />
            Owner only
          </Tag>
        </div>
        <h2>
          A little context.
          <br />
          Kept close.
        </h2>
        <p>
          These rules affect your next offer only after you explicitly review
          and save them. A private note never becomes a public reason.
        </p>
        {list(s.memories).length ? (
          list(s.memories).map((m) => (
            <article className="cg-memory" key={m.memory_id}>
              <div className="cg-memory-heading">
                <span className="cg-memory-icon">
                  <LockKeyhole size={17} />
                </span>
                <div>
                  <h3>{ruleNames[m.type] || readable(m.type)}</h3>
                  <p>
                    {Object.entries(m.value || {})
                      .map(
                        ([k, v]) =>
                          `${readable(k)}: ${k === "by" ? clock(Number(v)) : k === "receiver_id" ? person(String(v)) : String(v)}`,
                      )
                      .join(" · ")}
                  </p>
                </div>
              </div>
              <dl className="cg-memory-meta">
                <div>
                  <dt>Provenance</dt>
                  <dd>{m.provenance}</dd>
                </div>
                <div>
                  <dt>Scope</dt>
                  <dd>{m.scope?.goal_id || "Owner-wide"}</dd>
                </div>
                <div>
                  <dt>Expiry</dt>
                  <dd>
                    {m.expires_at ? stamp(m.expires_at) : "No set expiry"}
                  </dd>
                </div>
                <div>
                  <dt>Revision</dt>
                  <dd>{m.revision}</dd>
                </div>
              </dl>
              {m.private_note ? (
                <details className="cg-private-explanation">
                  <summary>My private note</summary>
                  <p>{m.private_note}</p>
                </details>
              ) : null}
              <div className="cg-actions">
                <button
                  className="cg-text"
                  onClick={() => setEditing({ ...m })}
                >
                  <Pencil size={14} />
                  Correct rule
                </button>
                <button
                  className="cg-text"
                  onClick={() => setRemoving(m.memory_id)}
                >
                  <Trash2 size={14} />
                  Delete memory
                </button>
              </div>
              {removing === m.memory_id ? (
                <div className="cg-notice warning">
                  <CircleAlert size={18} />
                  <div>
                    <strong>Delete this memory and its private content?</strong>
                    <p>
                      Only a content-free deletion receipt remains. Affected
                      offers and authority need renewed review.
                    </p>
                    <div className="cg-actions">
                      <button
                        className="cg-button danger"
                        disabled={!!service.busy || service.stale}
                        onClick={async () => {
                          if (
                            await service.act(
                              "Deleting this owner-local memory",
                              "/api/v2/memory/" +
                                encodeURIComponent(m.memory_id) +
                                "/delete",
                              { expected_revision: s.revision },
                            )
                          ) {
                            setRemoving(null);
                          }
                        }}
                      >
                        Delete this memory
                      </button>
                      <button
                        className="cg-text"
                        onClick={() => setRemoving(null)}
                      >
                        Keep memory
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </article>
          ))
        ) : (
          <div className="cg-empty small">
            <LockKeyhole size={26} />
            <h3>No reviewed private rules yet.</h3>
            <p>
              Your agent won’t infer a private preference from an unreviewed
              note.
            </p>
          </div>
        )}
        <button
          className="cg-button secondary"
          onClick={() =>
            setEditing({
              type: "excluded_capability",
              value: { capability: "driving" },
              scope: {},
              provenance: "Owner reviewed directly",
              expires_at: null,
              private_note: "",
            })
          }
        >
          <Plus size={16} />
          Add a reviewed rule
        </button>
      </section>
      <div>
        {editing ? (
          <MemoryEditor
            key={editing.memory_id || "new"}
            memory={editing}
            service={service}
            close={() => setEditing(null)}
          />
        ) : (
          <section className="cg-small-card">
            <HeartHandshake size={27} />
            <h3>“I can return with Dev if Asha receives by 16:15.”</h3>
            <p>
              A condition like this becomes a reviewed “Require a named
              receiver” rule. The public offer contains the condition; your
              reason stays private.
            </p>
            <p>
              To make yourself unavailable for an invitation, add an exclusion
              scoped to that goal and task. You can also decline an individual
              request without a reason.
            </p>
          </section>
        )}
        <Policy service={service} />
      </div>
    </div>
  );
}
function MemoryEditor({
  memory: m,
  service,
  close,
}: {
  memory: Data;
  service: LivingService;
  close: () => void;
}) {
  const [draft, setDraft] = useState(m),
    [review, setReview] = useState(false);
  const [baseRevision] = useState(service.state?.revision);
  const staleDraft = baseRevision !== service.state?.revision;
  function change(k: string, v: any) {
    setDraft((d) => ({ ...d, [k]: v }));
    setReview(false);
  }
  function val(k: string, v: any) {
    change("value", { ...draft.value, [k]: v });
  }
  return (
    <section className="cg-paper cg-memory-editor">
      <p className="cg-eyebrow">
        {m.memory_id ? "CORRECT AN EXISTING RULE" : "NEW OWNER-LOCAL RULE"}
      </p>
      <h2>Make it explicit.</h2>
      {staleDraft ? (
        <div className="cg-notice warning">
          <CircleAlert size={18} />
          <p>
            Your private state changed while this draft was open. Your edits are
            preserved here. Cancel and reopen the current rule before saving.
          </p>
        </div>
      ) : null}
      <label>
        Rule type
        <select
          value={draft.type}
          onChange={(e) => {
            change("type", e.target.value);
            setDraft((d) => ({ ...d, type: e.target.value, value: {} }));
          }}
        >
          {Object.entries(ruleNames).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      {["excluded_capability", "require_receiver", "handoff_deadline"].includes(
        draft.type,
      ) ? (
        <label>
          Capability
          <select
            value={draft.value.capability || ""}
            onChange={(e) => val("capability", e.target.value)}
          >
            <option value="">Choose a capability</option>
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
      ) : null}
      {draft.type === "weekly_capacity" ? (
        <label>
          Minutes per week
          <input
            type="number"
            min={0}
            value={draft.value.minutes ?? ""}
            onChange={(e) => val("minutes", Number(e.target.value))}
          />
        </label>
      ) : null}
      {draft.type === "request_category" ? (
        <>
          <label>
            Request capability category
            <select
              value={draft.value.category || ""}
              onChange={(e) => val("category", e.target.value)}
            >
              <option value="">Choose capability</option>
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
          <label className="cg-checkbox">
            <input
              type="checkbox"
              checked={!!draft.value.allowed}
              onChange={(e) => val("allowed", e.target.checked)}
            />
            I allow requests in this category
          </label>
        </>
      ) : null}
      {draft.type === "require_receiver" ? (
        <>
          <label>
            Named receiver
            <select
              value={draft.value.receiver_id || ""}
              onChange={(e) => val("receiver_id", e.target.value)}
            >
              <option value="">Choose registered person</option>
              {["asha", "ravi", "leena"].map((id) => (
                <option key={id} value={id}>
                  {person(id)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Receiver task ID
            <input
              value={draft.value.receiver_task_id || ""}
              onChange={(e) => val("receiver_task_id", e.target.value)}
              placeholder="handoff"
            />
          </label>
        </>
      ) : null}
      {["require_receiver", "handoff_deadline"].includes(draft.type) ? (
        <label>
          Must finish by · local time
          <input
            type="time"
            value={draft.value.by !== undefined ? clock(draft.value.by) : ""}
            onChange={(e) => {
              const [h, m] = e.target.value.split(":").map(Number);
              val("by", h * 60 + m);
            }}
          />
        </label>
      ) : null}
      {["excluded_capability", "handoff_deadline", "require_receiver"].includes(
        draft.type,
      ) ? (
        <>
          <label>
            Optional task ID · narrow this rule
            <input
              value={draft.value.task_id || ""}
              onChange={(e) => {
                const next = { ...draft.value };
                if (e.target.value) next.task_id = e.target.value;
                else delete next.task_id;
                change("value", next);
              }}
              placeholder="return"
            />
          </label>
        </>
      ) : null}
      <label>
        Goal scope
        <select
          value={draft.scope?.goal_id || ""}
          onChange={(e) =>
            change("scope", e.target.value ? { goal_id: e.target.value } : {})
          }
        >
          <option value="">All my goals</option>
          {list(service.state?.goals).map((g) => (
            <option key={g.goal_id} value={g.goal_id}>
              {g.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        Provenance
        <input
          value={draft.provenance || ""}
          onChange={(e) => change("provenance", e.target.value)}
        />
      </label>
      <label>
        Expiry · optional
        <input
          type="datetime-local"
          value={
            draft.expires_at
              ? new Date(
                  new Date(draft.expires_at).getTime() -
                    new Date(draft.expires_at).getTimezoneOffset() * 60000,
                )
                  .toISOString()
                  .slice(0, 16)
              : ""
          }
          onChange={(e) =>
            change(
              "expires_at",
              e.target.value ? new Date(e.target.value).toISOString() : null,
            )
          }
        />
      </label>
      <label>
        <LockKeyhole size={13} />
        Private note · never shared
        <textarea
          rows={3}
          value={draft.private_note || ""}
          onChange={(e) => change("private_note", e.target.value)}
          placeholder="Your reason is yours."
        />
      </label>
      <label className="cg-checkbox cg-review-confirm">
        <input
          type="checkbox"
          checked={review}
          onChange={(e) => setReview(e.target.checked)}
        />
        <span>
          I reviewed this structured rule, its scope and provenance. Save it as
          my confirmed memory.
        </span>
      </label>
      <div className="cg-actions">
        <button
          className="cg-button"
          disabled={!review || !!service.busy || service.stale}
          onClick={async () => {
            if (
              await service.act(
                "Saving your reviewed private rule",
                "/api/v2/memory",
                {
                  expected_revision: baseRevision,
                  memory: {
                    memory_id: draft.memory_id,
                    type: draft.type,
                    value: draft.value,
                    scope: draft.scope,
                    provenance: draft.provenance,
                    expires_at: draft.expires_at,
                    private_note: draft.private_note,
                    owner_confirmed: true,
                  },
                },
              )
            )
              close();
          }}
        >
          Save reviewed memory <Check size={16} />
        </button>
        <button className="cg-text" onClick={close}>
          Cancel edit
        </button>
      </div>
    </section>
  );
}
function Calendar({ service }: { service: LivingService }) {
  const s = service.state!;
  return (
    <div className="cg-record">
      <section className="cg-paper">
        <p className="cg-eyebrow">OBSERVED APP-CREATED ENTRIES</p>
        <h2>A calendar is one part of the story.</h2>
        <p>
          These are calendar effects, separate from human arrival or reported
          handoff completion. Loss of access means the current status is
          unconfirmed.
        </p>
        {s.calendar_available === false ? (
          <div className="cg-notice warning">
            <CircleAlert size={19} />
            <div>
              <strong>
                Calendar access is unavailable · current effects unconfirmed.
              </strong>
              <p>
                {s.calendar_error ||
                  "The owner could not read the current calendar. Earlier receipts remain historical."}
              </p>
            </div>
          </div>
        ) : null}
        {list(s.calendar_events).length ? (
          list(s.calendar_events).map((e, i) => (
            <CalendarEntry key={e.event_id || i} event={e} service={service} />
          ))
        ) : (
          <div className="cg-empty small">
            <CalendarDays size={30} />
            <h3>No observed living-calendar entries.</h3>
            <p>
              Calendar effects appear after approved execution and readback.
            </p>
          </div>
        )}
        <h3>Mutation receipts</h3>
        {list(s.receipts).map((r, i) => (
          <div className="cg-receipt" key={r.mutation_id || i}>
            <FileCheck2 size={19} />
            <div>
              <strong>{readable(r.status)}</strong>
              <p>
                {r.event_id} · {stamp(r.verified_at)}
              </p>
              {r.error ? <p>{r.error}</p> : null}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

function CalendarEntry({
  event: e,
  service,
}: {
  event: Data;
  service: LivingService;
}) {
  const [editing, setEditing] = useState(false),
    [summary, setSummary] = useState(
      e.label || e.summary || e.intent?.label || "",
    );
  return (
    <article className="cg-calendar-event">
      <CalendarDays size={23} />
      <div>
        <h3>
          {e.label || e.summary || e.intent?.label || "App-created entry"}
        </h3>
        <p>
          {e.date} · {clock(e.start)}–{clock(e.end)} · {e.timezone}
        </p>
        <code>{e.event_id}</code>
        <p>ETag: {e.etag || "not observed"}</p>
        {e.user_edited ? (
          <Tag tone="warning">User edited · preserve for owner review</Tag>
        ) : null}
        <Json value={e} label="Inspect owner-local observed entry" />
        {service.state?.sample ? (
          editing ? (
            <form
              style={{ marginTop: 18 }}
              onSubmit={async (event) => {
                event.preventDefault();
                if (
                  await service.act(
                    "Applying your explicitly authored local calendar edit",
                    "/api/v2/calendar/" +
                      encodeURIComponent(e.event_id) +
                      "/edit",
                    { summary },
                  )
                )
                  setEditing(false);
              }}
            >
              <label>
                Fictional local user-edit fixture · summary
                <input
                  autoFocus
                  maxLength={1000}
                  required
                  value={summary}
                  onChange={(event) => setSummary(event.target.value)}
                />
              </label>
              <p className="cg-caption">
                This actually edits your local sample entry and changes its
                ETag. A later conditional mutation must preserve the edited
                entry for your review.
              </p>
              <div className="cg-actions">
                <button
                  className="cg-button secondary"
                  disabled={!!service.busy || service.stale}
                >
                  Apply local sample edit
                </button>
                <button
                  type="button"
                  className="cg-text"
                  onClick={() => setEditing(false)}
                >
                  Keep current entry
                </button>
              </div>
            </form>
          ) : (
            <button
              className="cg-text"
              style={{ marginTop: 15 }}
              onClick={() => setEditing(true)}
            >
              <Pencil size={13} />
              Try a labeled local user edit
            </button>
          )
        ) : null}
      </div>
    </article>
  );
}
