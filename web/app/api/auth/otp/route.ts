import { NextResponse } from "next/server";
import { apiFetch, ApiError } from "@/lib/api/server";

export async function POST(request: Request) {
  const { email } = await request.json();

  try {
    await apiFetch("/auth/otp", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    return new NextResponse(null, { status: 204 });
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
