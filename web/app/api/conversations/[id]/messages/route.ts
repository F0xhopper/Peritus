import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyFetch, proxyErrorResponse } from "@/lib/api/proxy";

export async function POST(
  request: NextRequest,
  ctx: RouteContext<"/api/conversations/[id]/messages">,
) {
  const { id } = await ctx.params;

  // A client that aborts mid-upload leaves an empty/truncated body here, so
  // this must answer with a status rather than throw an unhandled SyntaxError.
  let question: unknown;
  try {
    question = (await request.json())?.question;
  } catch {
    return NextResponse.json({ error: "Malformed request body." }, { status: 400 });
  }
  if (typeof question !== "string" || !question.trim()) {
    return NextResponse.json({ error: "A question is required." }, { status: 400 });
  }

  try {
    const upstream = await proxyFetch(
      `/conversations/${encodeURIComponent(id)}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ question }),
        // Forward the client's abort (Stop button, tab close) to FastAPI so it
        // persists the partial answer as `interrupted` and releases its claim
        // instead of streaming into a dead socket.
        signal: request.signal,
      },
    );

    if (!upstream.ok || !upstream.body) {
      // Pre-stream failures (404 not-yours, 409 busy/not-ready) are plain JSON.
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

    // Pipe the SSE body straight through — no buffering, no re-parsing.
    return new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        // Tells nginx-style proxies not to buffer, which would batch tokens
        // into one late chunk and destroy the streaming feel.
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
