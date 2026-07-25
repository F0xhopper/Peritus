import { NextResponse } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";

// A running worker notices the cancel on its next heartbeat and aborts
// cooperatively; a queued job simply never starts. The backend also appends a
// terminal `cancelled` event, so any page tailing the log ends cleanly rather
// than hanging on a build that will never emit again.
//
// 409 ("No active build for this expert") is a real answer, not a failure —
// it means the build finished between the page render and the click. It
// reaches the caller with its status intact via proxyErrorResponse.

export async function POST(
  _request: Request,
  ctx: RouteContext<"/api/experts/[slug]/build/cancel">,
) {
  const { slug } = await ctx.params;

  try {
    const result = await proxyJson<{ job_id: number; status: string }>(
      `/experts/${encodeURIComponent(slug)}/build/cancel`,
      { method: "POST" },
    );
    return NextResponse.json(result, { status: 202 });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
