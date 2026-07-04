import { NextResponse } from "next/server";
import { refreshSession } from "@/lib/auth/session";

export async function POST() {
  const accessToken = await refreshSession();
  if (!accessToken) {
    return NextResponse.json({ error: "Session expired." }, { status: 401 });
  }
  return NextResponse.json({ ok: true });
}
