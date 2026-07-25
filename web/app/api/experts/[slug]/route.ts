import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import type { ExpertDetail } from "@/lib/api/types";

export async function GET(
  _req: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]">,
) {
  const { slug } = await ctx.params;
  try {
    const expert = await proxyJson<ExpertDetail>(
      `/experts/${encodeURIComponent(slug)}`,
    );
    return NextResponse.json(expert);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
