"use client";

import Link from "next/link";
import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import type { ExpertSummary } from "@/lib/api/types";

// The one moment an expert earns ambient sidebar presence: while it is being
// built. Disappears at ready/failed. No polling in v1 — it refreshes with
// normal navigation and router.refresh(); live SSE updates are a later step.

export function NavBuildingExpert({ experts }: { experts: ExpertSummary[] }) {
  const building = experts.filter(
    (expert) => expert.status === "queued" || expert.status === "building",
  );

  if (building.length === 0) return null;

  return (
    <SidebarGroup className="py-0 group-data-[collapsible=icon]:hidden">
      <SidebarMenu>
        {building.map((expert) => (
          <SidebarMenuItem key={expert.id}>
            <SidebarMenuButton render={<Link href={`/experts/${expert.name}/build`} />}>
              <span className="relative flex size-2 shrink-0" aria-hidden>
                {/* Was amber — the theme carries build state on lightness and
                    motion, never hue (see globals.css). */}
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-status-building/70" />
                <span className="relative inline-flex size-2 rounded-full bg-status-building" />
              </span>
              <span className="truncate font-mono text-[0.8125rem]">
                {expert.name}
              </span>
              <span className="text-eyebrow ml-auto text-muted-foreground">
                {expert.status === "queued" ? "queued" : "building"}
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}
