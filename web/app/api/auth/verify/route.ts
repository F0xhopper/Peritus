import { NextResponse } from "next/server";
import { apiFetch, ApiError } from "@/lib/api/server";
import { setSessionCookies, type Session } from "@/lib/auth/session";

export async function POST(request: Request) {
  const { email, token } = await request.json();

  try {
    const session: Session & { user: { id: string; email: string | null } } =
      await apiFetch("/auth/verify", {
        method: "POST",
        body: JSON.stringify({ email, token }),
      });

    await setSessionCookies(session);
    return NextResponse.json({ user: session.user });
  } catch (err) {
    if (err instanceof ApiError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    return NextResponse.json(
      { error: "Could not reach the auth server." },
      { status: 502 },
    );
  }
}
