"use client";

import Link from "next/link";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { StatusDot } from "@/components/experts/status-dot";
import type { ExpertSummary } from "@/lib/api/types";

export function NavRecentExperts({ experts }: { experts: ExpertSummary[] }) {
  const recent = [...experts]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 5);

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>Recent experts</SidebarGroupLabel>
      <SidebarMenu>
        {recent.map((expert) => (
          <SidebarMenuItem key={expert.id}>
            <SidebarMenuButton
              render={<Link href={`/experts/${expert.name}`} />}
            >
              <StatusDot status={expert.status} />
              <span className="truncate">{expert.name}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}
