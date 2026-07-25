import { apiFetch, ApiError } from "@/lib/api/server";
import type { Session } from "@/lib/auth/cookies";

// Split out from session.ts so proxy.ts can renew a session too: session.ts
// imports next/headers, which the proxy can't use.

/** Trade a refresh token for a fresh session. Throws on failure — use
 * `isDeadRefreshToken` to tell a spent token from an unreachable API. */
export function requestRefresh(refreshToken: string): Promise<Session> {
  return apiFetch("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

/** Whether a failed refresh means "sign in again" rather than "try later".
 *
 * We send a fixed request shape, so any 4xx is about the credential itself:
 * GoTrue reports a revoked or expired refresh token as 400, not 401. Timeouts
 * and 5xx are transient and must not cost the user their session. */
export function isDeadRefreshToken(err: unknown): boolean {
  return err instanceof ApiError && err.status >= 400 && err.status < 500;
}
