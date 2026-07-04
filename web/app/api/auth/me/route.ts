import { NextResponse } from "next/server";
import { apiFetch, ApiError } from "@/lib/api/server";
import { getAccessToken, refreshSession } from "@/lib/auth/session";

export async function GET() {
  let accessToken = await getAccessToken();
  if (!accessToken) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }

  try {
    const me = await apiFetch("/auth/me", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return NextResponse.json(me);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      accessToken = await refreshSession();
      if (accessToken) {
        const me = await apiFetch("/auth/me", {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        return NextResponse.json(me);
      }
    }
    const status = err instanceof ApiError ? err.status : 502;
    return NextResponse.json({ error: "Not signed in." }, { status });
  }
}
