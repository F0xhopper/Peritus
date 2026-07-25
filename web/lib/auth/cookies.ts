// Cookie name constants only — no "server-only" / next/headers import, so
// this is safe to use from middleware.ts (Edge runtime), which can't use
// next/headers' cookies() the way route handlers and session.ts do.
export const ACCESS_TOKEN_COOKIE = "peritus_access_token";
export const REFRESH_TOKEN_COOKIE = "peritus_refresh_token";

// Short-lived cookies bridging the OAuth redirect: the PKCE verifier set when
// we send the browser to Google, read back in /api/auth/callback.
export const PKCE_VERIFIER_COOKIE = "peritus_pkce_verifier";
export const LOGIN_NEXT_COOKIE = "peritus_login_next";
