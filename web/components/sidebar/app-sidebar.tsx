"use client";

import * as React from "react";
import Link from "next/link";
import { UsersIcon, SettingsIcon, SearchIcon } from "lucide-react";
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
import { NavUser } from "@/components/sidebar/nav-user";
import { CommandMenu } from "@/components/sidebar/command-menu";
import { BrandMark, Logo } from "@/components/brand/wordmark";
import type { ConversationSummary, ExpertSummary, User } from "@/lib/api/types";

const NAV_ITEMS: NavItem[] = [
  { title: "Experts", url: "/experts", icon: UsersIcon },
  { title: "Settings", url: "/settings", icon: SettingsIcon },
];

export function AppSidebar({
  experts,
  conversations,
  user,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  experts: ExpertSummary[];
  conversations: ConversationSummary[];
  user: User | null;
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
        {/* Not a SidebarMenuButton: the identity is not a nav row, and giving
            it the hover/active treatment made it read as a fourth destination
            above the real ones. It links home and gets out of the way.
            The rail used to hide it entirely when collapsed, because a clipped
            "PER" is worse than nothing — now the mark is its collapsed form,
            so the app keeps a face at every width. */}
        <Link
          href="/experts"
          aria-label="Peritus — home"
          className="flex items-center rounded-lg px-2 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
        >
          <Logo
            tagline="Experts built from sources"
            className="group-data-[collapsible=icon]:hidden"
          />
          <BrandMark className="hidden group-data-[collapsible=icon]:flex" />
        </Link>
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
      {user ? <NavUser user={user} /> : null}
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
