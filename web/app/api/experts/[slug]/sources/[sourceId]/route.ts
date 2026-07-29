import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";

/** Remove a source and its chunks from the corpus.
 *
 * Works on any source, not only uploads: a build that pulled in something the
 * owner would rather their expert did not cite should be correctable without a
 * full rebuild. */
export async function DELETE(
  _req: NextRequest,
  ctx: RouteContext<"/api/experts/[slug]/sources/[sourceId]">,
) {
  const { slug, sourceId } = await ctx.params;
  try {
    await proxyJson(
      `/experts/${encodeURIComponent(slug)}/sources/${encodeURIComponent(sourceId)}`,
      { method: "DELETE" },
    );
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
