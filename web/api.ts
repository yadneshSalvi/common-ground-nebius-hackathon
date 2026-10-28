import type { BrokerState, OwnerState, ReleasePreview } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
const brokerBase = "http://127.0.0.1:4302";
const key = "common-ground.session.v2";
export interface Session {
  token: string;
  expires_at: string;
  owner_id?: string;
}
export class Client {
  readonly base: string;
  constructor(private kind: "broker" | "owner") {
    this.base = kind === "broker" ? brokerBase : "";
  }
  private token() {
    try {
      const session = JSON.parse(
        localStorage.getItem(key) || "null",
      ) as Session | null;
      if (
        !session ||
        typeof session.token !== "string" ||
        !Number.isFinite(Date.parse(session.expires_at)) ||
        Date.parse(session.expires_at) <= Date.now()
      ) {
        this.forget();
        return null;
      }
      return session.token;
    } catch {
      this.forget();
      return null;
    }
  }
  hasSession() {
    return Boolean(this.token());
  }
  forget() {
    localStorage.removeItem(key);
  }
  async request<T>(
    path: string,
    body?: object,
    signal?: AbortSignal,
  ): Promise<T> {
    const token = this.token();
    const response = await fetch(this.base + path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
      signal,
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const result = (await response.json()) as {
          detail?: string | { message?: string };
          error?: string;
        };
        detail =
          typeof result.detail === "string"
            ? result.detail
            : result.detail?.message || result.error || detail;
      } catch {
        /* A non-JSON service failure still has a useful status. */
      }
      if (response.status === 401) this.forget();
      throw new ApiError(detail, response.status);
    }
    return response.json() as Promise<T>;
  }
  async pair(pair_code: string) {
    const session = await this.request<Session>("/api/session", { pair_code });
    if (!session.token || !session.expires_at)
      throw new Error(
        "This service did not return a session capability and expiry.",
      );
    localStorage.setItem(key, JSON.stringify(session));
    return session;
  }
  async state<T extends BrokerState | OwnerState>(
    signal?: AbortSignal,
  ): Promise<T> {
    const value = await this.request<unknown>("/api/state", undefined, signal);
    if (!value || typeof value !== "object")
      throw new Error(
        "The local service returned an incompatible state. No decision can be made until it is refreshed.",
      );
    const state = value as Record<string, unknown>;
    const arrays =
      this.kind === "broker"
        ? [
            "owners",
            "offers",
            "approvals",
            "actions",
            "model_runs",
            "disclosures",
            "history",
          ]
        : [
            "proposals",
            "approvals",
            "private_calendar",
            "calendar_events",
            "skills",
            "corrections",
          ];
    if (
      !arrays.every((key) => Array.isArray(state[key])) ||
      !(this.kind === "broker"
        ? state.goal && state.planning && typeof state.revision === "number"
        : state.owner &&
          state.preferences &&
          typeof state.constraint_revision === "number")
    )
      throw new Error(
        "The local service returned an incompatible state. No decision can be made until it is refreshed.",
      );
    return value as T;
  }
  async preview(allow: boolean): Promise<ReleasePreview> {
    const token = this.token();
    const response = await fetch(
      `/api/release-preview?allow_inference=${allow ? "1" : "0"}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "omit",
      },
    );
    if (!response.ok)
      throw new ApiError(
        "The exact release preview could not be loaded. Reconnect to your local service and try again.",
        response.status,
      );
    const value = (await response.json()) as ReleasePreview;
    return {
      ...value,
      preview_digest: response.headers.get("X-Preview-Digest") || undefined,
    };
  }
  async download(path: string, filename: string) {
    const token = this.token();
    const response = await fetch(this.base + path, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: "omit",
    });
    if (!response.ok)
      throw new ApiError(
        `Export failed (${response.status}).`,
        response.status,
      );
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
export function consumePairCode() {
  const hash = new URLSearchParams(location.hash.slice(1));
  const code = hash.get("pair");
  if (code) history.replaceState(null, "", location.pathname + location.search);
  return code;
}
