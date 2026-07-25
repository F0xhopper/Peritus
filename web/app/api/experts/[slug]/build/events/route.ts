import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyFetch, proxyErrorResponse } from "@/lib/api/proxy";

// Resumable tail of an expert's durable build log. `?after=<seq>` is passed
// straight through: the backend replays every persisted event above that
// cursor, so a client that reconnects after a dropped socket resumes exactly
// where it stopped instead of replaying from zero or losing the gap.

export async function GET(
  request: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]/build/events">,
) {
  const { slug } = await ctx.params;

  // Clamp rather than forward blindly: the backend declares `after` as
  // `Query(0, ge=0)` and would 422 on junk, which surfaces to the user as a
  // dead stream rather than a restart from the beginning.
  const raw = Number(request.nextUrl.searchParams.get("after"));
  const after = Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0;

  try {
    const upstream = await proxyFetch(
      `/experts/${encodeURIComponent(slug)}/build/events?after=${after}`,
      {
        // Forward the client's abort (navigating away, tab close) so FastAPI
        // stops tailing. The build itself is unaffected — that is the point of
        // the durable job queue.
        signal: request.signal,
      },
    );

    if (!upstream.ok || !upstream.body) {
      // Pre-stream failures: 404 for "not yours" or "never built".
      const text = await upstream.text().catch(() => "");
      let message = text;
      try {
        message = JSON.parse(text).detail ?? text;
      } catch {
        // not JSON — use the raw body
      }
      return NextResponse.json(
        { error: message || upstream.statusText },
        { status: upstream.status },
      );
    }

    return new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        // Tells nginx-style proxies not to buffer, which would batch a build's
        // progress into one late chunk and defeat the whole page.
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
