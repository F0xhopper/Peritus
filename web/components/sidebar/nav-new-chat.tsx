"use client";

import Link from "next/link";
import { PencilLineIcon } from "lucide-react";
import {
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import type { ExpertSummary } from "@/lib/api/types";

// Starting a chat from the sidebar. Recent chats let you return to one; this
// is how you begin one without first navigating to an expert.
//
// With a single ready expert the choice is already made, so this links
// straight to its chat page. With several, it opens the command palette in
// chat mode rather than inventing a second picker UI.

export function NavNewChat({
  experts,
  onPickExpert,
}: {
  experts: ExpertSummary[];
  onPickExpert: () => void;
}) {
  const ready = experts.filter((expert) => expert.status === "ready");

  if (ready.length === 1) {
    return (
      <SidebarMenuItem>
        <SidebarMenuButton
          tooltip="New chat"
          render={<Link href={`/experts/${ready[0].name}/chat`} />}
        >
          <PencilLineIcon />
          <span>New chat</span>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  }

  if (ready.length === 0) {
    return (
      <SidebarMenuItem>
        <SidebarMenuButton
          tooltip="Build an expert first"
          disabled
          className="opacity-50"
        >
          <PencilLineIcon />
          <span>New chat</span>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  }

  return (
    <SidebarMenuItem>
      <SidebarMenuButton tooltip="New chat" onClick={onPickExpert}>
        <PencilLineIcon />
        <span>New chat</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
