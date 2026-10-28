import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  ArrowRight,
  Check,
  CircleAlert,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { ApiError, Client, consumePairCode } from "./api";
import type { BrokerState, OwnerState, OwnerId } from "./types";
import "@fontsource/fraunces/latin-400.css";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/source-sans-3/latin-400.css";
import "@fontsource/source-sans-3/latin-500.css";
import "@fontsource/source-sans-3/latin-600.css";
import "./styles.css";

export const names: Record<OwnerId, string> = {
  asha: "Asha",
  ravi: "Ravi",
  leena: "Leena",
};
export const time = (minutes: number) =>
  `${Math.floor(minutes / 60)
    .toString()
    .padStart(2, "0")}:${(minutes % 60).toString().padStart(2, "0")}`;
export const short = (value?: string) =>
  value ? `${value.slice(0, 10)}…${value.slice(-6)}` : "Not issued";
export const words = (s: string) =>
  s
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^./, (c) => c.toUpperCase());
export function Mark({ small = false }: { small?: boolean }) {
  return (
    <svg
      className={small ? "brand-mark small" : "brand-mark"}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M12 39a22 22 0 0 1 32-26"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <path
        d="M27 8a22 22 0 0 1 27 34"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
        opacity=".65"
      />
      <path
        d="M53 43a22 22 0 0 1-39 6"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
        opacity=".4"
      />
    </svg>
  );
}
export function Avatar({ id, size = "" }: { id: OwnerId; size?: string }) {
  return (
    <span className={`avatar ${id} ${size}`} aria-hidden="true">
      {id === "asha" ? "A" : id === "ravi" ? "R" : "L"}
    </span>
  );
}
export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
export function Status({ status }: { status: string }) {
  const good = [
    "VERIFIED",
    "ACTIVE",
    "APPROVED",
    "OPTIMAL",
    "COMPENSATED",
  ].includes(status);
  const bad = [
    "FAILED",
    "NEEDS_ATTENTION",
    "REPLAN_REQUIRED",
    "AMBIGUOUS",
    "RECOVERING",
  ].includes(status);
  return (
    <Pill tone={good ? "good" : bad ? "warning" : "neutral"}>
      {good ? (
        <Check size={13} />
      ) : bad ? (
        <CircleAlert size={13} />
      ) : (
        <span className="status-dot" />
      )}
      {words(status)}
    </Pill>
  );
}
export function ErrorNotice({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="notice error">
      <CircleAlert size={20} />
      <div>
        <strong>We need a moment here.</strong>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button
          className="icon-button"
          onClick={onRetry}
          aria-label="Retry loading"
        >
          <RefreshCw size={18} />
        </button>
      ) : null}
    </div>
  );
}
export function useService<T extends BrokerState | OwnerState>(
  kind: "broker" | "owner",
) {
  const [client] = useState(() => new Client(kind));
  const [pairCode] = useState(consumePairCode);
  const [paired, setPaired] = useState(() => client.hasSession());
  const [state, setState] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [busy, setBusy] = useState("");
  const [lastLoaded, setLastLoaded] = useState<Date | null>(null);
  async function refresh(clearActionError = true) {
    if (clearActionError) setError("");
    try {
      const next = await client.state<T>();
      setState(next);
      setLastLoaded(new Date());
      setConnectionError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setPaired(false);
        setState(null);
      }
      setConnectionError(
        e instanceof Error ? e.message : "The local service is unavailable.",
      );
    }
  }
  async function pair(code: string) {
    setBusy("Pairing");
    setError("");
    try {
      await client.pair(code.trim());
      setPaired(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pairing failed.");
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    if (pairCode) void pair(pairCode);
  }, []);
  useEffect(() => {
    if (!paired) return;
    void refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void refresh(false);
    }, 3000);
    return () => clearInterval(timer);
  }, [paired]);
  async function act(label: string, path: string, body: object) {
    setBusy(label);
    setError("");
    try {
      await client.request(path, body);
      await refresh(false);
      return true;
    } catch (e) {
      await refresh(false);
      setError(
        e instanceof Error ? e.message : "The action could not be completed.",
      );
      return false;
    } finally {
      setBusy("");
    }
  }
  function lock() {
    client.forget();
    setState(null);
    setError("");
    setConnectionError("");
    setPaired(false);
  }
  return {
    client,
    state,
    paired,
    pair,
    error: error || connectionError,
    setError,
    busy,
    act,
    refresh,
    lastLoaded,
    lock,
  };
}
export function Pairing({
  kind,
  pair,
  error,
  busy,
}: {
  kind: "broker" | "owner";
  pair: (code: string) => Promise<void>;
  error: string;
  busy: string;
}) {
  const [code, setCode] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    void pair(code);
  }
  return (
    <main className="pairing-page">
      <header className="pair-brand">
        <Mark />
        <span>common ground</span>
        <Pill>Sample scenario</Pill>
      </header>
      <div className="pair-layout">
        <section className="pair-story">
          <p className="eyebrow">A LITTLE LESS BACK AND FORTH</p>
          <h1>
            Make a plan together.
            <br />
            <em>Keep your reasons yours.</em>
          </h1>
          <p className="pair-description">
            An afternoon appointment. Three people who care. One clear
            agreement, with everyone’s say in it.
          </p>
          <div className="pair-people">
            <Avatar id="asha" />
            <Avatar id="ravi" />
            <Avatar id="leena" />
            <span>
              Asha, Ravi & Leena
              <br />
              <small>A fictional family circle</small>
            </span>
          </div>
          <div
            className="pair-illustration"
            aria-label="Coordination steps: prepare, drive, accompany and handoff"
          >
            <span className="illustration-line" />
            <div>
              <span>12:20</span>
              <b>Prepare</b>
              <small>Asha</small>
            </div>
            <div>
              <span>13:10</span>
              <b>Drive</b>
              <small>Ravi</small>
            </div>
            <div>
              <span>13:50</span>
              <b>Be there</b>
              <small>Leena</small>
            </div>
            <div>
              <span>16:00</span>
              <b>Handoff</b>
              <small>Asha</small>
            </div>
          </div>
          <p className="fine-print">
            Illustrated sample goal · this preview does not create an agreement
            or calendar action.
          </p>
        </section>
        <section className="pair-card">
          <span className="pair-lock">
            <KeyRound size={26} />
          </span>
          <p className="eyebrow">
            {kind === "owner"
              ? "YOUR OWNER-LOCAL AGENT"
              : "THE SHARED AGREEMENT ROOM"}
          </p>
          <h2>
            A trusted place
            <br /> to begin.
          </h2>
          <p>
            {kind === "owner"
              ? "Pair directly with this owner’s local service to review private preferences, release an offer, and sign a decision."
              : "Pair with the local coordinator to see released offers and bring the responsibilities together."}
          </p>
          <form onSubmit={submit}>
            <label htmlFor="pair-code">Local pairing code</label>
            <input
              id="pair-code"
              type="password"
              autoComplete="off"
              spellCheck={false}
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Paste the code from your launcher"
            />
            <button className="button primary" disabled={Boolean(busy)}>
              {busy ? <LoaderCircle className="spin" size={18} /> : null}
              {busy || "Open my workspace"}
              <ArrowRight size={18} />
            </button>
          </form>
          {error ? <ErrorNotice message={error} /> : null}
          <div className="pair-boundary">
            <LockKeyhole size={17} />
            <span>
              The launcher prints a separate pairing link for each service. Your
              paired session stays in this service’s browser origin for up to
              one hour. Lock the workspace to clear it.
            </span>
          </div>
        </section>
      </div>
      <footer className="pair-footer">
        <ShieldCheck size={16} />
        Local-only fictional sample. No real accounts or external calendar
        connections. Hostile code running as the same OS user and the
        administrator are outside this local demo’s threat model.
      </footer>
    </main>
  );
}
export function Loading() {
  return (
    <main className="loading">
      <Mark />
      <h1>Pulling up the shared table.</h1>
      <p>Connecting to the paired local service…</p>
      <LoaderCircle className="spin" size={24} />
    </main>
  );
}
export function JsonDetails({
  title,
  value,
}: {
  title: string;
  value: unknown;
}) {
  return (
    <details className="json-details">
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
