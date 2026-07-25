import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import type { ConversationSummary } from "@/lib/api/types";

export async function GET(request: NextRequest) {
  // Clamped server-side too; the backend rejects > 50 with a 422.
  const limit = request.nextUrl.searchParams.get("limit") ?? "20";
  try {
    const conversations = await proxyJson<ConversationSummary[]>(
      `/conversations?limit=${encodeURIComponent(limit)}`,
    );
    return NextResponse.json(conversations);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
