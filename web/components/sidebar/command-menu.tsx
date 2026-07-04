"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  LayoutDashboardIcon,
  UsersIcon,
  SettingsIcon,
  BarChart3Icon,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { StatusDot } from "@/components/experts/status-dot";
import type { ExpertSummary } from "@/lib/api/types";

export function CommandMenu({
  experts,
  open,
  onOpenChange,
}: {
  experts: ExpertSummary[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();

  React.useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;

      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        onOpenChange(!open);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  function go(url: string) {
    onOpenChange(false);
    router.push(url);
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Jump to"
      description="Jump to a page or expert"
    >
      <CommandInput placeholder="Jump to a page or expert…" />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Pages">
          <CommandItem onSelect={() => go("/dashboard")}>
            <LayoutDashboardIcon />
            Dashboard
          </CommandItem>
          <CommandItem onSelect={() => go("/experts")}>
            <UsersIcon />
            Experts
          </CommandItem>
          <CommandItem onSelect={() => go("/analytics")}>
            <BarChart3Icon />
            Analytics
          </CommandItem>
          <CommandItem onSelect={() => go("/settings")}>
            <SettingsIcon />
            Settings
          </CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Experts">
          {experts.map((expert) => (
            <CommandItem
              key={expert.id}
              value={`${expert.name} ${expert.topic}`}
              onSelect={() => go(`/experts/${expert.name}`)}
            >
              <StatusDot status={expert.status} />
              {expert.name}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
