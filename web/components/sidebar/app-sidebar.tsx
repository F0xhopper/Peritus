"use client";

import * as React from "react";
import Link from "next/link";
import {
  LayoutDashboardIcon,
  UsersIcon,
  BarChart3Icon,
  SettingsIcon,
  SearchIcon,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { NavMain, type NavItem } from "@/components/nav-main";
import { NavRecentExperts } from "@/components/sidebar/nav-recent-experts";
import { SidebarUsageCard } from "@/components/sidebar/sidebar-usage-card";
import { CommandMenu } from "@/components/sidebar/command-menu";
import type { ExpertSummary } from "@/lib/api/types";

const NAV_ITEMS: NavItem[] = [
  { title: "Dashboard", url: "/dashboard", icon: LayoutDashboardIcon },
  { title: "Experts", url: "/experts", icon: UsersIcon },
  { title: "Analytics", url: "/analytics", icon: BarChart3Icon },
  { title: "Settings", url: "/settings", icon: SettingsIcon },
];

export function AppSidebar({
  experts,
  ...props
}: React.ComponentProps<typeof Sidebar> & { experts: ExpertSummary[] }) {
  const [commandOpen, setCommandOpen] = React.useState(false);

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              render={<Link href="/dashboard" />}
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
          </SidebarMenu>
        </SidebarGroup>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={NAV_ITEMS} />
        <NavRecentExperts experts={experts} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarUsageCard experts={experts} />
      </SidebarFooter>
      <SidebarRail />
      <CommandMenu
        experts={experts}
        open={commandOpen}
        onOpenChange={setCommandOpen}
      />
    </Sidebar>
  );
}
