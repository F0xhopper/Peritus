import { createHash, randomBytes } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { cookies } from "next/headers";
import { apiFetch } from "@/lib/api/server";
import { LOGIN_NEXT_COOKIE, PKCE_VERIFIER_COOKIE } from "@/lib/auth/cookies";

// Kicks off the Google OAuth flow. We generate the PKCE pair here so the
// verifier only ever lives in an httpOnly cookie — the browser is redirected
// to Supabase's authorize URL carrying just the challenge, and the callback
// route completes the exchange server-side (same posture as the OTP flow:
// no tokens in client JS).

const PKCE_COOKIE_MAX_AGE = 60 * 10; // the round-trip through Google is quick

export async function GET(request: NextRequest) {
  const next = request.nextUrl.searchParams.get("next");
  const safeNext = next && next.startsWith("/") ? next : "/experts";

  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const redirectTo = `${request.nextUrl.origin}/api/auth/callback`;

  let url: string;
  try {
    ({ url } = await apiFetch(
      `/auth/oauth/authorize?provider=google&code_challenge=${challenge}&redirect_to=${encodeURIComponent(redirectTo)}`,
    ));
  } catch {
    return NextResponse.redirect(
      new URL("/login?error=google", request.url),
    );
  }

  const store = await cookies();
  const cookieOpts = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: PKCE_COOKIE_MAX_AGE,
  };
  store.set(PKCE_VERIFIER_COOKIE, verifier, cookieOpts);
  store.set(LOGIN_NEXT_COOKIE, safeNext, cookieOpts);

  return NextResponse.redirect(url);
}
