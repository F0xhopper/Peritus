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

/** Deletes the expert and everything that cascades off it — sources, chunks,
 * graph, and every conversation held with it. The backend cancels an in-flight
 * build first, so a queued or building expert can be deleted too. */
export async function DELETE(
  _req: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]">,
) {
  const { slug } = await ctx.params;
  try {
    await proxyJson(`/experts/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    });
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
