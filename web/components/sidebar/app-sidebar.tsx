"use client";

import * as React from "react";
import Link from "next/link";
import {
  UsersIcon,
  BarChart3Icon,
  SettingsIcon,
  SearchIcon,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { NavMain, type NavItem } from "@/components/nav-main";
import { NavBuildingExpert } from "@/components/sidebar/nav-building-expert";
import { NavNewChat } from "@/components/sidebar/nav-new-chat";
import { NavRecentChats } from "@/components/sidebar/nav-recent-chats";
import { CommandMenu } from "@/components/sidebar/command-menu";
import type { ConversationSummary, ExpertSummary } from "@/lib/api/types";

const NAV_ITEMS: NavItem[] = [
  { title: "Experts", url: "/experts", icon: UsersIcon },
  { title: "Analytics", url: "/analytics", icon: BarChart3Icon },
  { title: "Settings", url: "/settings", icon: SettingsIcon },
];

export function AppSidebar({
  experts,
  conversations,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  experts: ExpertSummary[];
  conversations: ConversationSummary[];
}) {
  const [commandOpen, setCommandOpen] = React.useState(false);
  // The palette doubles as the expert picker for "New chat"; closing it always
  // drops back to the full jump-to list so ⌘K is never stuck in chat mode.
  const [pickingChatExpert, setPickingChatExpert] = React.useState(false);

  const handleCommandOpenChange = React.useCallback((next: boolean) => {
    setCommandOpen(next);
    if (!next) setPickingChatExpert(false);
  }, []);

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              render={<Link href="/experts" />}
              className="font-medium"
            >
              <span className="text-primary" aria-hidden>
                {">"}
              </span>
              <span className="tracking-tight">peritus</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <SidebarGroup className="p-0">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                tooltip="Search"
                onClick={() => setCommandOpen(true)}
              >
                <SearchIcon />
                <span>Search</span>
                <kbd className="ml-auto text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
                  /
                </kbd>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <NavNewChat
              experts={experts}
              onPickExpert={() => {
                setPickingChatExpert(true);
                setCommandOpen(true);
              }}
            />
          </SidebarMenu>
        </SidebarGroup>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={NAV_ITEMS} />
        <NavBuildingExpert experts={experts} />
        <NavRecentChats conversations={conversations} />
      </SidebarContent>
      <SidebarRail />
      <CommandMenu
        experts={experts}
        open={commandOpen}
        onOpenChange={handleCommandOpenChange}
        chatOnly={pickingChatExpert}
      />
    </Sidebar>
  );
}
