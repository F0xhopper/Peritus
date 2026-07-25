import { NextResponse } from "next/server";
import { proxyJson, proxyErrorResponse } from "@/lib/api/proxy";
import type { ExpertSummary } from "@/lib/api/types";

export async function GET() {
  try {
    const experts = await proxyJson<ExpertSummary[]>("/experts");
    return NextResponse.json(experts);
  } catch (err) {
    return proxyErrorResponse(err);
  }
}
