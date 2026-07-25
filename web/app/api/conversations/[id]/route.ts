import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import type { ConversationDetail, ConversationSummary } from "@/lib/api/types";

export async function GET(
  _req: NextRequest,
  ctx: RouteContext<"/api/conversations/[id]">,
) {
  const { id } = await ctx.params;
  try {
    const conversation = await proxyJson<ConversationDetail>(
      `/conversations/${encodeURIComponent(id)}`,
    );
    return NextResponse.json(conversation);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}

export async function PATCH(
  request: NextRequest,
  ctx: RouteContext<"/api/conversations/[id]">,
) {
  const { id } = await ctx.params;

  let title: unknown;
  try {
    title = (await request.json())?.title;
  } catch {
    return NextResponse.json({ error: "Malformed request body." }, { status: 400 });
  }
  if (typeof title !== "string" || !title.trim()) {
    return NextResponse.json({ error: "A title is required." }, { status: 400 });
  }

  try {
    const conversation = await proxyJson<ConversationSummary>(
      `/conversations/${encodeURIComponent(id)}`,
      { method: "PATCH", body: JSON.stringify({ title }) },
    );
    return NextResponse.json(conversation);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}

export async function DELETE(
  _req: NextRequest,
  ctx: RouteContext<"/api/conversations/[id]">,
) {
  const { id } = await ctx.params;
  try {
    await proxyJson(`/conversations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
