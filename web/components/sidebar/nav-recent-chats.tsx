"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import type { ConversationSummary } from "@/lib/api/types";

// Replaces the old "Recent experts" list. Access frequency is what earns
// sidebar space, and after a chat the thing worth re-opening is the
// conversation, not the expert — each row names its expert anyway, and ⌘K
// still jumps straight to any expert by name.

export function NavRecentChats({
  conversations,
}: {
  conversations: ConversationSummary[];
}) {
  const pathname = usePathname();

  // No placeholder for the empty case: a new user's sidebar stays quiet until
  // they have something to come back to.
  if (conversations.length === 0) return null;

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>Recent chats</SidebarGroupLabel>
      <SidebarMenu>
        {conversations.map((conversation) => (
          <SidebarMenuItem key={conversation.id}>
            <SidebarMenuButton
              isActive={pathname === `/chats/${conversation.id}`}
              className="h-auto py-1.5"
              render={<Link href={`/chats/${conversation.id}`} />}
            >
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-sm">
                  {conversation.title ?? "Untitled chat"}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {conversation.expert_persona_name ?? conversation.expert_topic}
                </span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}
