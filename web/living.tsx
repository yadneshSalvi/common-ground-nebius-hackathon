import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ArrowUpRight,
  CircleAlert,
  Flower2,
  LockKeyhole,
  RefreshCw,
} from "lucide-react";
import "@fontsource/fraunces/latin-400.css";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/source-sans-3/latin-400.css";
import "@fontsource/source-sans-3/latin-500.css";
import "@fontsource/source-sans-3/latin-600.css";
import "./living.css";
export type Data = Record<string, any>;
export type Provider = "local" | "fireworks" | "nebius";
const SESSION = "common-ground.living.session.v2";
export const person = (id?: string) =>
  id ? id.charAt(0).toUpperCase() + id.slice(1) : "Unassigned";
export const clock = (n?: number) =>
  typeof n === "number"
    ? `${Math.floor(n / 60)
        .toString()
        .padStart(2, "0")}:${(n % 60).toString().padStart(2, "0")}`
    : "Not confirmed";
export const minutes = (s: string) => {
  const [h, m] = s.split(":").map(Number);
  return h * 60 + m;
};
export const readable = (s?: string) =>
  (s || "Not observed")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^./, (c) => c.toUpperCase());
export const list = (value: any): Data[] => (Array.isArray(value) ? value : []);
export const payload = (o: Data) => o.body?.payload || o.payload || o;
export const ownerId = (o: Data) => o.owner_id || o.id || o.body?.issuer;
export const stamp = (value?: string) =>
  value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not observed";
export function Brand() {
  return (
    <span className="cg-brand">
      <span className="cg-mark" aria-hidden="true">
        <Flower2 size={31} />
      </span>
      <span>
        common ground<span className="cg-period">.</span>
      </span>
    </span>
  );
}
export function Avatar({ id }: { id?: string }) {
  return (
    <span aria-hidden="true" className={`cg-avatar ${id || "unassigned"}`}>
      {person(id).slice(0, 1)}
    </span>
  );
}
export function Tag({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`cg-tag ${tone}`}>{children}</span>;
}
export function Json({
  value,
  label = "Inspect exact record",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="cg-json">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function OwnerLink({ owner, label }: { owner: Data; label?: string }) {
  const id = ownerId(owner);
  return (
    <a
      className="cg-person-link"
      href={owner.url || owner.origin}
      target="_blank"
      rel="noopener noreferrer"
    >
      <Avatar id={id} />
      <span>
        <strong>{owner.name || person(id)}</strong>
        <small>{label || "Open private owner space"}</small>
      </span>
      <ArrowUpRight size={17} />
    </a>
  );
}
class ServiceError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export function useLiving(kind: "broker" | "owner") {
  const base = kind === "broker" ? "http://127.0.0.1:4302" : "";
  const [state, setState] = useState<Data | null>(null),
    [paired, setPaired] = useState(() => {
      try {
        const s = JSON.parse(localStorage.getItem(SESSION) || "null");
        return !!s?.token && Date.parse(s.expires_at) > Date.now();
      } catch {
        return false;
      }
    }),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(""),
    [stale, setStale] = useState(false),
    [halt, setHalt] = useState(false);
  const mounted = useRef(true);
  const epoch = useRef(0);
  const request = useCallback(
    async (path: string, body?: Data, signal?: AbortSignal, file = false) => {
      let saved: Data | null = null;
      try {
        saved = JSON.parse(localStorage.getItem(SESSION) || "null");
      } catch {
        /* unavailable session */
      }
      if (
        saved &&
        !["/sample/session", "/api/session"].includes(path) &&
        Date.parse(saved.expires_at) <= Date.now()
      ) {
        localStorage.removeItem(SESSION);
        throw new ServiceError(
          "Your session expired. Re-enter this service to observe current decisions.",
          401,
        );
      }
      const response = await fetch(base + path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          ...(saved?.token ? { Authorization: `Bearer ${saved.token}` } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "omit",
        signal: signal || AbortSignal.timeout(15000),
      });
      const value =
        file && response.ok
          ? await response.blob()
          : await response.json().catch(() => ({}));
      if (!response.ok)
        throw new ServiceError(
          typeof value.detail === "string"
            ? value.detail
            : Array.isArray(value.detail)
              ? value.detail
                  .map(
                    (issue: Data) =>
                      `${issue.msg} (${(issue.loc || []).join(".")})`,
                  )
                  .join("; ")
              : value.detail?.message ||
                value.error ||
                `Service returned ${response.status}.`,
          response.status,
        );
      return { value, headers: response.headers };
    },
    [base],
  );
  const failed = useCallback((e: unknown) => {
    if (!mounted.current) return;
    setError(
      e instanceof Error ? e.message : "The service could not be reached.",
    );
    if (
      e instanceof ServiceError &&
      e.status < 500 &&
      ![401, 403].includes(e.status)
    )
      return;
    epoch.current += 1;
    setStale(true);
    setHalt(true);
    if (e instanceof ServiceError && [401, 403].includes(e.status)) {
      localStorage.removeItem(SESSION);
      setPaired(false);
    }
  }, []);
  const refresh = useCallback(async () => {
    const generation = epoch.current;
    try {
      const { value } = await request("/api/v2/state");
      if (value.schema_version !== 2 && kind === "broker")
        throw new Error(
          "The living agreement API is unavailable. Recorded workflow remains accessible.",
        );
      if (mounted.current && generation === epoch.current) {
        setState(value);
        setStale(false);
        setHalt(false);
        setError("");
      }
      return value;
    } catch (e) {
      failed(e);
      return null;
    }
  }, [request, failed, kind]);
  const pair = useCallback(
    async (sample = false, code = "") => {
      setBusy(sample ? "Opening fictional circle" : "Pairing this service");
      setError("");
      try {
        const { value } = await request(
          sample ? "/sample/session" : "/api/session",
          sample ? {} : { pair_code: code },
        );
        if (!value.token || !value.expires_at)
          throw new Error("The service did not issue a valid session.");
        localStorage.setItem(SESSION, JSON.stringify(value));
        epoch.current += 1;
        setPaired(true);
        setHalt(false);
        await refresh();
        return true;
      } catch (e) {
        failed(e);
        return false;
      } finally {
        setBusy("");
      }
    },
    [request, refresh, failed],
  );
  const act = useCallback(
    async (label: string, path: string, body: Data = {}) => {
      setBusy(label);
      setError("");
      try {
        const { value } = await request(path, body);
        await refresh();
        return value || { ok: true };
      } catch (e) {
        failed(e);
        return null;
      } finally {
        setBusy("");
      }
    },
    [request, refresh, failed],
  );
  useEffect(() => {
    mounted.current = true;
    const hash = new URLSearchParams(location.hash.slice(1));
    const code = hash.get("pair");
    if (code) {
      history.replaceState(null, "", location.pathname + location.search);
      void pair(false, code);
    } else if (paired) void refresh();
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!paired || halt) return;
    const interval = setInterval(() => void refresh(), 4000);
    return () => clearInterval(interval);
  }, [paired, halt, refresh]);
  return {
    state,
    paired,
    error,
    busy,
    stale,
    request,
    act,
    pair,
    refresh,
    setError,
    lock: () => {
      epoch.current += 1;
      localStorage.removeItem(SESSION);
      setPaired(false);
      setStale(true);
      setHalt(true);
    },
  };
}
export type LivingService = ReturnType<typeof useLiving>;
export function ErrorBanner({ service }: { service: LivingService }) {
  if (!service.error && !service.stale) return null;
  return (
    <div className="cg-notice warning" role="alert">
      <CircleAlert size={20} />
      <div>
        <strong>{service.error || "Current status is unavailable."}</strong>
        {service.stale ? (
          <p>
            Last observed information is historical. Fresh approvals and
            calendar status need a successful connection.
          </p>
        ) : null}
        <button className="cg-text" onClick={() => void service.refresh()}>
          <RefreshCw size={14} /> Reconnect and refresh
        </button>
      </div>
    </div>
  );
}
export function PairForm({
  service,
  owner = false,
}: {
  service: LivingService;
  owner?: boolean;
}) {
  const [code, setCode] = useState("");
  return (
    <details className="cg-pair">
      <summary>
        <LockKeyhole size={14} />{" "}
        {owner ? "Pair a private owner service" : "Pair an existing workspace"}
      </summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void service.pair(false, code);
        }}
      >
        <label>
          Launcher pairing code
          <input
            type="password"
            autoComplete="off"
            value={code}
            required
            onChange={(e) => setCode(e.target.value)}
          />
        </label>
        <button className="cg-button secondary" disabled={!!service.busy}>
          Pair this service
        </button>
      </form>
    </details>
  );
}
export function Wait({
  label,
  startedAt,
}: {
  label: string;
  startedAt?: string;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start =
      startedAt && Number.isFinite(Date.parse(startedAt))
        ? Date.parse(startedAt)
        : Date.now();
    const i = setInterval(
      () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000))),
      1000,
    );
    return () => clearInterval(i);
  }, [label, startedAt]);
  return (
    <span className="cg-wait" role="status">
      <span className="cg-spinner" />
      {label} · {elapsed}s elapsed
    </span>
  );
}
