// Cookie names and shaping only — no "server-only" / next/headers import, so
// this is safe to use from proxy.ts, which writes cookies onto a NextResponse
// instead of through next/headers' cookies() store.
export const ACCESS_TOKEN_COOKIE = "peritus_access_token";
export const REFRESH_TOKEN_COOKIE = "peritus_refresh_token";

// Short-lived cookies bridging the OAuth redirect: the PKCE verifier set when
// we send the browser to Google, read back in /api/auth/callback.
export const PKCE_VERIFIER_COOKIE = "peritus_pkce_verifier";
export const LOGIN_NEXT_COOKIE = "peritus_login_next";

// Supabase refresh tokens are long-lived and rotate on use; cap the cookie
// itself at 30 days so an abandoned session still expires eventually.
const REFRESH_TOKEN_MAX_AGE = 60 * 60 * 24 * 30;

// Retire the access cookie a minute before its token actually expires. The
// proxy treats a missing access cookie as "time to refresh", so this margin
// makes it renew on the request *before* the backend would start 401ing,
// rather than mid-render where cookies can't be written.
const ACCESS_TOKEN_EXPIRY_MARGIN = 60;

export interface Session {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export interface SessionCookie {
  name: string;
  value: string;
  options: {
    httpOnly: true;
    secure: boolean;
    sameSite: "lax";
    path: string;
    maxAge: number;
  };
}

/** The httpOnly cookies that carry a session, ready to hand to either cookie
 * API. Never readable from client JS — the browser holds these tokens but only
 * our own server code sees them (mitigates XSS token theft). */
export function sessionCookies(session: Session): SessionCookie[] {
  const shared = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
  } as const;

  return [
    {
      name: ACCESS_TOKEN_COOKIE,
      value: session.access_token,
      options: {
        ...shared,
        // Floored so an implausibly short token can't drop the cookie to zero
        // and make every single request refresh.
        maxAge: Math.max(
          session.expires_in - ACCESS_TOKEN_EXPIRY_MARGIN,
          ACCESS_TOKEN_EXPIRY_MARGIN,
        ),
      },
    },
    {
      name: REFRESH_TOKEN_COOKIE,
      value: session.refresh_token,
      options: { ...shared, maxAge: REFRESH_TOKEN_MAX_AGE },
    },
  ];
}
