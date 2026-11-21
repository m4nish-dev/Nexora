/**
 * Backend API client.
 *
 * Every failure is normalised into an ApiError with a human-readable message, so the UI can
 * always render something meaningful (the contract forbids a blank screen on 422/503).
 */

const REQUEST_TIMEOUT_MS = 90_000;

function resolveBaseUrl() {
  const runtime = typeof window !== "undefined" ? window.__NEXORA_CONFIG__?.API_BASE_URL : undefined;
  const base = runtime || import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
  return base.replace(/\/+$/, "");
}

export const API_BASE_URL = resolveBaseUrl();

export class ApiError extends Error {
  constructor(message, { status = 0, kind = "unknown", detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind; // "validation" | "unavailable" | "not_found" | "network" | "timeout" | "server" | "unknown"
    this.detail = detail;
  }
}

function validationMessage(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    const field = Array.isArray(first?.loc) ? first.loc.filter((p) => p !== "body").join(".") : "";
    const msg = first?.msg ?? "Invalid request";
    return field ? `${field}: ${msg}` : msg;
  }
  return "The request was invalid.";
}

function errorFromResponse(status, body) {
  const detail = body?.detail ?? null;
  if (status === 422) {
    return new ApiError(`Request rejected — ${validationMessage(detail)}`, { status, kind: "validation", detail });
  }
  if (status === 503) {
    const message =
      detail === "all providers unavailable"
        ? "All providers are unavailable right now. Every API key in the pool failed — please try again in a moment."
        : `Service unavailable${typeof detail === "string" ? ` — ${detail}` : ""}.`;
    return new ApiError(message, { status, kind: "unavailable", detail });
  }
  if (status === 404) {
    return new ApiError(typeof detail === "string" ? detail : "Not found.", { status, kind: "not_found", detail });
  }
  if (status === 502) {
    return new ApiError("The model provider rejected this request. Try rephrasing or shortening it.", {
      status,
      kind: "server",
      detail,
    });
  }
  return new ApiError(`Unexpected server error (${status}).`, { status, kind: "server", detail });
}

async function request(path, { method = "GET", body, headers = {}, signal, timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const onAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", onAbort, { once: true });
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: { Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    if (controller.signal.aborted && controller.signal.reason?.name === "TimeoutError") {
      throw new ApiError("The server took too long to respond.", { kind: "timeout" });
    }
    if (signal?.aborted) throw err;
    throw new ApiError("Can't reach the Nexora server. Check your connection and try again.", { kind: "network" });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) throw errorFromResponse(response.status, data);
  if (data === null) throw new ApiError("The server returned an unreadable response.", { status: response.status });
  return data;
}

export function sendChat({ sessionId, message, systemPrompt, simulateFailure, signal }) {
  const body = { session_id: sessionId, message };
  if (systemPrompt) body.system_prompt = systemPrompt;
  const headers = simulateFailure ? { "X-Simulate-Failure": simulateFailure } : {};
  return request("/chat", { method: "POST", body, headers, signal });
}

export function getHealth({ signal } = {}) {
  return request("/health", { signal, timeoutMs: 10_000 });
}

export function getSessionMessages(sessionId, { signal } = {}) {
  return request(`/sessions/${encodeURIComponent(sessionId)}/messages`, { signal });
}
