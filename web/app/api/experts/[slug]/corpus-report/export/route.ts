import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyFetch, proxyErrorResponse } from "@/lib/api/proxy";

// Streams the screening ledger back as a file download (CSV or RIS).
//
// Passed through rather than re-serialised: the backend owns the format, and
// RIS in particular has escaping rules that a second encoder here could only
// get wrong. The Content-Disposition filename is the backend's too.

const FORMATS = new Set(["csv", "ris"]);
const DECISIONS = new Set(["all", "accepted", "rejected"]);

export async function GET(
  request: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]/corpus-report/export">,
) {
  const { slug } = await ctx.params;

  // Validate here rather than forwarding junk: FastAPI would 422 on an unknown
  // enum value, which reaches the user as a broken download rather than a
  // fixable message.
  const format = request.nextUrl.searchParams.get("format") ?? "csv";
  const decision = request.nextUrl.searchParams.get("decision") ?? "all";
  if (!FORMATS.has(format) || !DECISIONS.has(decision)) {
    return NextResponse.json(
      { error: "Unsupported export format or decision filter." },
      { status: 400 },
    );
  }

  try {
    const upstream = await proxyFetch(
      `/experts/${encodeURIComponent(slug)}/corpus-report/export` +
        `?format=${format}&decision=${decision}`,
      { signal: request.signal },
    );

    if (!upstream.ok || !upstream.body) {
      const text = await upstream.text().catch(() => "");
      let message = text;
      try {
        message = JSON.parse(text).detail ?? text;
      } catch {
        // not JSON — use the raw body
      }
      // 507 is the export guard: the corpus is larger than the export ceiling
      // and a truncated ledger would misrepresent the search, so the backend
      // refuses rather than emitting a partial file.
      return NextResponse.json(
        { error: message || upstream.statusText },
        { status: upstream.status },
      );
    }

    const headers = new Headers();
    for (const header of [
      "content-type",
      "content-disposition",
      "x-peritus-export-rows",
    ]) {
      const value = upstream.headers.get(header);
      if (value) headers.set(header, value);
    }
    headers.set("Cache-Control", "no-store");

    return new NextResponse(upstream.body, { status: 200, headers });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
