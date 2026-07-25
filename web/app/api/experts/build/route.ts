import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyFetch, proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import { slugifyTopic } from "@/lib/slug";
import type { ExpertSummary, ExpertTier } from "@/lib/api/types";

// Starts a build and answers with the slug to watch, rather than piping the
// build's own stream back to the caller.
//
// `POST /experts/build` returns an SSE stream, but the job is enqueued and the
// expert row created *before* that response begins — and the backend is
// explicit that "terminating the connection does not affect the build". So
// this handler waits only for the response headers (proof of enqueue), drops
// the stream, and hands back a slug. The page it redirects to re-attaches with
// `GET /experts/{slug}/build/events?after=0`, which replays the durable log
// from the beginning, so nothing is missed in the gap.
//
// The alternative — holding this connection open for the whole build — would
// tie a multi-minute job to one page's lifetime for no benefit, when the
// backend went to the trouble of making it survivable.

const TIERS: ExpertTier[] = ["lite", "standard", "pro"];

export async function POST(request: NextRequest) {
  let body: { topic?: unknown; tier?: unknown; sources?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Malformed request body." }, { status: 400 });
  }

  const topic = typeof body.topic === "string" ? body.topic.trim() : "";
  if (!topic) {
    return NextResponse.json({ error: "A topic is required." }, { status: 400 });
  }
  if (topic.length > 300) {
    return NextResponse.json(
      { error: "Topic must be 300 characters or fewer." },
      { status: 400 },
    );
  }

  const tier = TIERS.includes(body.tier as ExpertTier)
    ? (body.tier as ExpertTier)
    : "standard";

  // An empty array would be sent as "allow nothing" and starve the build, so
  // it collapses to null — the backend's "let the planner choose".
  const sources =
    Array.isArray(body.sources) && body.sources.length > 0
      ? body.sources.filter((s): s is string => typeof s === "string")
      : null;

  // Mirrors the backend's own guard, so an all-punctuation topic fails here
  // with a usable message instead of after a round trip.
  const guess = slugifyTopic(topic);
  if (!guess) {
    return NextResponse.json(
      { error: "Topic must contain at least one letter or number." },
      { status: 400 },
    );
  }

  try {
    const upstream = await proxyFetch("/experts/build", {
      method: "POST",
      body: JSON.stringify({ topic, tier, sources }),
    });

    if (!upstream.ok) {
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

    // Headers are in, so the job is enqueued. Let the stream go.
    await upstream.body?.cancel().catch(() => {});

    const slug = await resolveSlug(guess, topic);
    return NextResponse.json({ slug }, { status: 202 });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}

/** Confirm the mirrored slug actually exists, and fall back to finding the
 * expert by topic if it doesn't. Keeps `slugifyTopic` from being a correctness
 * dependency: drift costs an extra request, not a broken redirect. */
async function resolveSlug(guess: string, topic: string): Promise<string> {
  try {
    await proxyJson(`/experts/${encodeURIComponent(guess)}`);
    return guess;
  } catch {
    // Fall through to the scan.
  }

  try {
    const experts = await proxyJson<ExpertSummary[]>("/experts");
    const match = experts.find((expert) => expert.topic === topic);
    if (match) return match.name;
  } catch {
    // Nothing better to offer than the guess.
  }

  return guess;
}
