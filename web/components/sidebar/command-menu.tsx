"use client";

import * as React from "react";
import { useRouter, usePathname } from "next/navigation";
import { UsersIcon, SettingsIcon, MessageSquareIcon } from "lucide-react";
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
  /** Chat mode: the sidebar's "New chat" opens this as an expert picker, so
   * pages and plain expert links would only be noise. */
  chatOnly = false,
}: {
  experts: ExpertSummary[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  chatOnly?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  // Only ready experts can be chatted with, so an unbuilt one is not offered.
  const readyExperts = experts.filter((expert) => expert.status === "ready");

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
    // Re-selecting the page you're already on shouldn't stack a duplicate
    // history entry — that's what made "back" sometimes take two presses to
    // move anywhere, landing on what looked like the same page again.
    if (url !== pathname) router.push(url);
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title={chatOnly ? "New chat" : "Jump to"}
      description={
        chatOnly ? "Pick an expert to chat with" : "Jump to a page or expert"
      }
    >
      <CommandInput
        placeholder={
          chatOnly ? "Chat with which expert?" : "Jump to a page or expert…"
        }
      />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        {!chatOnly && (
          <>
            <CommandGroup heading="Pages">
              <CommandItem onSelect={() => go("/experts")}>
                <UsersIcon />
                Experts
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
          </>
        )}
        {readyExperts.length > 0 && (
          <>
            {!chatOnly && <CommandSeparator />}
            <CommandGroup heading="Chat">
              {readyExperts.map((expert) => (
                <CommandItem
                  key={`chat-${expert.id}`}
                  value={`chat ${expert.name} ${expert.topic}`}
                  onSelect={() => go(`/experts/${expert.name}/chat`)}
                >
                  <MessageSquareIcon />
                  {chatOnly ? expert.name : `Chat with ${expert.name}`}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
