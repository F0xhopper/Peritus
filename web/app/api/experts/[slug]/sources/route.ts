import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import type { CorpusSource } from "@/lib/api/types";

/** Every source in this expert's corpus, newest first. Owner-only upstream —
 * this is the management view the delete button acts on, not the public audit
 * surface. */
export async function GET(
  _req: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]/sources">,
) {
  const { slug } = await ctx.params;
  try {
    const sources = await proxyJson<CorpusSource[]>(
      `/experts/${encodeURIComponent(slug)}/sources`,
    );
    return NextResponse.json(sources);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
