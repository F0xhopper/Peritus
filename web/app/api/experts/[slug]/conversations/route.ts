import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import type { ConversationSummary } from "@/lib/api/types";

export async function GET(
  _req: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]/conversations">,
) {
  const { slug } = await ctx.params;
  try {
    const conversations = await proxyJson<ConversationSummary[]>(
      `/experts/${encodeURIComponent(slug)}/conversations`,
    );
    return NextResponse.json(conversations);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}

export async function POST(
  _req: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]/conversations">,
) {
  const { slug } = await ctx.params;
  try {
    // 409 from the backend when the expert isn't ready — passed through as-is.
    const conversation = await proxyJson<ConversationSummary>(
      `/experts/${encodeURIComponent(slug)}/conversations`,
      { method: "POST" },
    );
    return NextResponse.json(conversation);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
