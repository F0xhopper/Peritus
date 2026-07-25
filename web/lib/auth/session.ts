import "server-only";
import { cookies } from "next/headers";
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  sessionCookies,
  type Session,
} from "@/lib/auth/cookies";
import { isDeadRefreshToken, requestRefresh } from "@/lib/auth/refresh";

// httpOnly cookies, never read from client JS — the browser never sees these
// tokens directly, only our own /api/auth/* route handlers do (mitigates XSS
// token theft; see DASHBOARD_PLAN.md section 2).

export type { Session };

export async function setSessionCookies(session: Session) {
  const store = await cookies();
  for (const { name, value, options } of sessionCookies(session)) {
    store.set(name, value, options);
  }
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
 * refresh token is missing/expired (cookies are cleared in that case).
 *
 * Next.js only allows cookie writes from route handlers, server actions and
 * the proxy — never during a server component render. proxy.ts renews sessions
 * before the render starts so this normally runs somewhere it can persist, but
 * a render that lands here anyway still gets a usable token: dropping the write
 * costs one rotation, whereas failing would bounce the user to /login. */
export async function refreshSession(): Promise<string | null> {
  const refreshToken = await getRefreshToken();
  if (!refreshToken) return null;

  let session: Session;
  try {
    session = await requestRefresh(refreshToken);
  } catch (err) {
    if (isDeadRefreshToken(err)) {
      await persistIfWritable(clearSessionCookies);
    }
    return null;
  }

  await persistIfWritable(() => setSessionCookies(session));
  return session.access_token;
}

async function persistIfWritable(write: () => Promise<void>) {
  try {
    await write();
  } catch {
    // Server component render — cookies are read-only here.
  }
}
