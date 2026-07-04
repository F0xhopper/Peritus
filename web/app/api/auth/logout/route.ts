import { NextResponse } from "next/server";
import { apiFetch } from "@/lib/api/server";
import { clearSessionCookies, getAccessToken } from "@/lib/auth/session";

export async function POST() {
  const accessToken = await getAccessToken();

  if (accessToken) {
    // Best-effort revoke — an already-expired token isn't an error for the
    // caller, we're clearing the local session either way.
    await apiFetch("/auth/logout", {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    }).catch(() => {});
  }

  await clearSessionCookies();
  return new NextResponse(null, { status: 204 });
}
