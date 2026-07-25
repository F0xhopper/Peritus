import { NextResponse, type NextRequest } from "next/server";
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  sessionCookies,
  type Session,
} from "@/lib/auth/cookies";
import { isDeadRefreshToken, requestRefresh } from "@/lib/auth/refresh";

const DASHBOARD_ROUTES = ["/experts", "/chats", "/analytics", "/settings"];

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isDashboardRoute = DASHBOARD_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );

  if (!isDashboardRoute) {
    return NextResponse.next();
  }

  if (request.cookies.has(ACCESS_TOKEN_COOKIE)) {
    return NextResponse.next();
  }

  // The access cookie lasts an hour; the refresh cookie lasts weeks. Renew here
  // rather than mid-render, because dashboard pages are server components and
  // Next.js discards cookie writes made during a render — a session refreshed
  // there would be thrown away and the user sent back to /login on every visit
  // once the first hour was up.
  const refreshToken = request.cookies.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) {
    return redirectToLogin(request);
  }

  let session: Session;
  try {
    session = await requestRefresh(refreshToken);
  } catch (err) {
    // Only a rejected refresh token means "log in again". Anything else (API
    // down, network blip) is transient, so let the page render and show its own
    // error instead of destroying a session that is probably still good.
    if (isDeadRefreshToken(err)) {
      return redirectToLogin(request, { clearSession: true });
    }
    return NextResponse.next();
  }

  const renewed = sessionCookies(session);
  // Onto the request so this render sees the new access token, and onto the
  // response so the browser keeps it for the next one.
  for (const { name, value } of renewed) {
    request.cookies.set(name, value);
  }
  const response = NextResponse.next({
    request: { headers: request.headers },
  });
  for (const { name, value, options } of renewed) {
    response.cookies.set(name, value, options);
  }
  return response;
}

function redirectToLogin(
  request: NextRequest,
  { clearSession = false }: { clearSession?: boolean } = {},
) {
  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", request.nextUrl.pathname);
  const response = NextResponse.redirect(loginUrl);
  if (clearSession) {
    response.cookies.delete(ACCESS_TOKEN_COOKIE);
    response.cookies.delete(REFRESH_TOKEN_COOKIE);
  }
  return response;
}

export const config = {
  matcher: [
    "/experts/:path*",
    "/chats/:path*",
    "/analytics/:path*",
    "/settings/:path*",
  ],
};
