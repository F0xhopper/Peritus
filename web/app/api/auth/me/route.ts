import { NextResponse } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";

export async function GET() {
  try {
    // proxyJson refreshes an expired access token before giving up — a missing
    // access cookie is normal an hour into a session, not a logged-out user.
    return NextResponse.json(await proxyJson("/auth/me"));
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
