import "server-only";
import { NextResponse } from "next/server";
import { ApiError } from "@/lib/api/server";
import { getAccessToken, refreshSession } from "@/lib/auth/session";

// Server-only helper for route handlers and server components calling the
// FastAPI backend on the user's behalf. Centralizes the attach-token →
// on-401-refresh-once → retry dance the auth routes previously did ad hoc.
// The browser never sees the access token; it only talks to our /api/* routes.

const API_BASE_URL = process.env.PERITUS_API_URL ?? "http://localhost:8000";

/** Thrown when there is no session at all, or the refresh token is dead. */
export class NotAuthenticatedError extends Error {
  constructor() {
    super("Not signed in.");
  }
}

async function callUpstream(path: string, token: string, init?: RequestInit) {
  return fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
      Authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });
}

/** Call the backend with the caller's bearer token, refreshing once on 401.
 * Returns the raw Response so streaming callers can pipe the body through. */
export async function proxyFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  let token = await getAccessToken();
  if (!token) {
    // No access cookie (expired) — the refresh cookie outlives it by weeks, so
    // try that before declaring the session dead.
    token = await refreshSession();
    if (!token) throw new NotAuthenticatedError();
  }

  let res = await callUpstream(path, token, init);
  if (res.status === 401) {
    const refreshed = await refreshSession();
    if (!refreshed) throw new NotAuthenticatedError();
    res = await callUpstream(path, refreshed, init);
  }
  return res;
}

async function toApiError(res: Response): Promise<ApiError> {
  const body = await res.text().catch(() => "");
  let message = body;
  try {
    // Entitlement denials send a structured `detail` object (code, tier,
    // remedy, …) rather than a string — see EntitlementError.to_payload in
    // billing/domain.py. Only its `message` is prose fit for ApiError.
    const detail = JSON.parse(body).detail;
    message = typeof detail === "string" ? detail : (detail?.message ?? body);
  } catch {
    // not JSON — use the raw body
  }
  return new ApiError(res.status, message || res.statusText);
}

/** proxyFetch + JSON decoding. Throws ApiError on any non-2xx. */
export async function proxyJson<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await proxyFetch(path, init);
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return null as T;
  return res.json() as Promise<T>;
}

/** Map a thrown proxy error onto a JSON response for a route handler.
 * Keeps every handler's catch block to one line and preserves the backend's
 * status codes (notably 404-not-403 for other users' rows, and 409s). */
export function proxyErrorResponse(err: unknown): NextResponse {
  if (err instanceof NotAuthenticatedError) {
    return NextResponse.json({ error: err.message }, { status: 401 });
  }
  if (err instanceof ApiError) {
    return NextResponse.json({ error: err.message }, { status: err.status });
  }
  return NextResponse.json(
    { error: "Could not reach the Peritus API." },
    { status: 502 },
  );
}
