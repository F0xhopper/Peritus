import { NextResponse, type NextRequest } from "next/server";
import { cookies } from "next/headers";
import { apiFetch } from "@/lib/api/server";
import { LOGIN_NEXT_COOKIE, PKCE_VERIFIER_COOKIE } from "@/lib/auth/cookies";
import { setSessionCookies, type Session } from "@/lib/auth/session";

// OAuth landing point: Supabase redirects here with a one-time code after the
// Google handshake. We pair it with the PKCE verifier cookie set in
// /api/auth/google/start and let the backend do the token exchange, so the
// browser never sees Supabase tokens outside our httpOnly cookies.

export async function GET(request: NextRequest) {
  const store = await cookies();
  const verifier = store.get(PKCE_VERIFIER_COOKIE)?.value;
  const next = store.get(LOGIN_NEXT_COOKIE)?.value;
  const safeNext = next && next.startsWith("/") ? next : "/experts";
  store.delete(PKCE_VERIFIER_COOKIE);
  store.delete(LOGIN_NEXT_COOKIE);

  const failure = NextResponse.redirect(new URL("/login?error=google", request.url));

  // GoTrue reports provider/user errors (e.g. the user hit "Cancel" on
  // Google's consent screen) as error query params instead of a code.
  const params = request.nextUrl.searchParams;
  const code = params.get("code");
  if (params.get("error") || !code || !verifier) {
    return failure;
  }

  try {
    const session: Session = await apiFetch("/auth/oauth/exchange", {
      method: "POST",
      body: JSON.stringify({ auth_code: code, code_verifier: verifier }),
    });
    await setSessionCookies(session);
  } catch {
    return failure;
  }

  return NextResponse.redirect(new URL(safeNext, request.url));
}
