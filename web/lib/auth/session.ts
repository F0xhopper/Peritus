import "server-only";
import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api/server";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth/cookies";

// httpOnly cookies, never read from client JS — the browser never sees these
// tokens directly, only our own /api/auth/* route handlers do (mitigates XSS
// token theft; see DASHBOARD_PLAN.md section 2).

// Supabase refresh tokens are long-lived and rotate on use; cap the cookie
// itself at 30 days so an abandoned session still expires eventually.
const REFRESH_TOKEN_MAX_AGE = 60 * 60 * 24 * 30;

export interface Session {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export async function setSessionCookies(session: Session) {
  const store = await cookies();
  const cookieOpts = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
  };

  store.set(ACCESS_TOKEN_COOKIE, session.access_token, {
    ...cookieOpts,
    maxAge: session.expires_in,
  });
  store.set(REFRESH_TOKEN_COOKIE, session.refresh_token, {
    ...cookieOpts,
    maxAge: REFRESH_TOKEN_MAX_AGE,
  });
}

export async function clearSessionCookies() {
  const store = await cookies();
  store.delete(ACCESS_TOKEN_COOKIE);
  store.delete(REFRESH_TOKEN_COOKIE);
}

export async function getAccessToken() {
  const store = await cookies();
  return store.get(ACCESS_TOKEN_COOKIE)?.value ?? null;
}

export async function getRefreshToken() {
  const store = await cookies();
  return store.get(REFRESH_TOKEN_COOKIE)?.value ?? null;
}

/** Refresh the session in place. Returns the new access token, or null if the
 * refresh token is missing/expired (cookies are cleared in that case). */
export async function refreshSession(): Promise<string | null> {
  const refreshToken = await getRefreshToken();
  if (!refreshToken) return null;

  try {
    const session: Session = await apiFetch("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    await setSessionCookies(session);
    return session.access_token;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      await clearSessionCookies();
    }
    return null;
  }
}
