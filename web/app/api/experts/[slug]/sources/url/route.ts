import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import type { UploadAccepted } from "@/lib/api/types";

/** Queue a web page for ingestion. The page is fetched by the worker, not here,
 * so a slow site never holds this request open. */
export async function POST(
  req: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]/sources/url">,
) {
  const { slug } = await ctx.params;
  const body = await req.json().catch(() => null);
  const url = typeof body?.url === "string" ? body.url.trim() : "";
  if (!url) {
    return NextResponse.json({ error: "A URL is required." }, { status: 400 });
  }

  try {
    const accepted = await proxyJson<UploadAccepted>(
      `/experts/${encodeURIComponent(slug)}/sources/url`,
      {
        method: "POST",
        body: JSON.stringify({ url, title: body?.title, author: body?.author }),
      },
    );
    return NextResponse.json(accepted, { status: 202 });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
