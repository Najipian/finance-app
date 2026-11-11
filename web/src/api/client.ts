/**
 * Minimal typed HTTP client for Onesum API.
 *
 * - The access token lives only in memory; the refresh token in sessionStorage
 *   (cleared when the tab closes). See docs/development-log.md for the trade-off.
 * - On a 401 the client refreshes once (shared by concurrent requests, because a
 *   refresh token is single-use) and retries the request.
 * - Errors are RFC 9457 problem details, surfaced as `ApiError`.
 */

const BASE = "/api/v1";
const REFRESH_KEY = "finance.refresh";

export interface Problem {
  title: string;
  status: number;
  detail?: string;
  errors?: { loc: (string | number)[]; msg: string }[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title);
    this.status = problem.status;
    this.problem = problem;
  }
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
let onSessionEnded: () => void = () => {};

export function setSessionEndedHandler(handler: () => void): void {
  onSessionEnded = handler;
}

export function storeTokens(tokens: TokenPair): void {
  accessToken = tokens.access_token;
  sessionStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

export function clearTokens(): void {
  accessToken = null;
  sessionStorage.removeItem(REFRESH_KEY);
}

export function hasSession(): boolean {
  return accessToken !== null || sessionStorage.getItem(REFRESH_KEY) !== null;
}

export function refreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_KEY);
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Problem;
    return new ApiError({ ...body, status: response.status });
  } catch {
    return new ApiError({ title: response.statusText || "Request failed", status: response.status });
  }
}

/** Exchange the refresh token for a new pair. Single-flight across callers. */
export function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    const token = refreshToken();
    if (!token) return false;
    const response = await fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token }),
    });
    if (!response.ok) {
      clearTokens();
      return false;
    }
    storeTokens((await response.json()) as TokenPair);
    return true;
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  auth?: boolean;
}

function url(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

/** Call the API and parse JSON. Throws `ApiError` on non-2xx. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, auth = true } = options;
  const send = (): Promise<Response> =>
    fetch(url(path, query), {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(auth && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  if (auth && accessToken === null && refreshToken()) {
    await refreshSession();
  }
  let response = await send();
  if (response.status === 401 && auth) {
    if (await refreshSession()) {
      response = await send();
    } else {
      onSessionEnded();
    }
  }
  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
