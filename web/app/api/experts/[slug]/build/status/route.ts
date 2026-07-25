import { NextResponse } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import type { BuildStatus } from "@/lib/api/types";

// Point-in-time job status. The progress page is driven by the event stream,
// not by polling this — it exists so a client can tell a finished build from a
// stalled one after the stream closes, and to report attempt counts the event
// log only mentions on retry.

export async function GET(
  _request: Request,
  ctx: RouteContext<"/api/experts/[slug]/build/status">,
) {
  const { slug } = await ctx.params;

  try {
    const status = await proxyJson<BuildStatus>(
      `/experts/${encodeURIComponent(slug)}/build/status`,
    );
    return NextResponse.json(status);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
