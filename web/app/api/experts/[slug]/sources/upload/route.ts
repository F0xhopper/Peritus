import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyFetch, proxyErrorResponse } from "@/lib/api/proxy";
import { ApiError } from "@/lib/api/server";
import type { UploadAccepted } from "@/lib/api/types";

// Matches MAX_UPLOAD_BYTES in api/src/peritus/api/schemas/sources.py. Checked
// here as well as upstream so an oversized file is rejected before it is pushed
// across the network a second time.
const MAX_BYTES = 20 * 1024 * 1024;

/** Forward a multipart upload to the API.
 *
 * The body is **buffered**, not streamed. `proxyFetch` retries once on a 401
 * after refreshing the session, and a stream that was already consumed by the
 * first attempt cannot be replayed — the retry would silently send an empty
 * body. Buffering costs one copy of a file that is capped at 20 MB anyway.
 *
 * The original `content-type` is forwarded verbatim because it carries the
 * multipart boundary; it also has to override the `application/json` default
 * that `proxyFetch` applies to every other call.
 */
export async function POST(
  req: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]/sources/upload">,
) {
  const { slug } = await ctx.params;
  const contentType = req.headers.get("content-type");
  if (!contentType?.includes("multipart/form-data")) {
    return NextResponse.json(
      { error: "Expected a multipart form upload." },
      { status: 400 },
    );
  }

  const body = await req.arrayBuffer();
  if (body.byteLength === 0) {
    return NextResponse.json({ error: "The upload was empty." }, { status: 400 });
  }
  if (body.byteLength > MAX_BYTES) {
    return NextResponse.json(
      { error: `Files must be under ${MAX_BYTES / (1024 * 1024)} MB.` },
      { status: 413 },
    );
  }

  try {
    const res = await proxyFetch(
      `/experts/${encodeURIComponent(slug)}/sources/upload`,
      { method: "POST", body, headers: { "Content-Type": contentType } },
    );
    const payload = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = payload?.detail;
      throw new ApiError(
        res.status,
        typeof detail === "string" ? detail : (detail?.message ?? res.statusText),
      );
    }
    return NextResponse.json(payload as UploadAccepted, { status: 202 });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
