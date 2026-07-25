"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import type { ConversationSummary, ExpertSummary } from "@/lib/api/types";

// Derived from the pathname rather than set by each page, because the trail
// lives in the layout's header and a layout cannot read its child's params.
// The labels that matter are readable names, not slugs, so the layout hands
// down the two lists it already fetches for the sidebar and they are used as
// lookup tables. Anything that misses resolves to a still-correct fallback —
// a breadcrumb that says "Chat" is worse than one that names the chat, but it
// is never wrong, and it never blocks rendering on a second request.
//
// Segment→label rules, in full:
//   /experts                  Experts
//   /experts/new              Experts › New expert
//   /experts/{slug}           Experts › {topic}
//   /experts/{slug}/chat      Experts › {topic} › Chat
//   /experts/{slug}/build     Experts › {topic} › Build
//   /chats/{id}               Experts › {topic} › {conversation title}
//   /analytics                Analytics
//   /settings                 Settings

export interface Crumb {
  label: string;
  /** Absent on the final crumb — the page you are already on. */
  href?: string;
}

const SECTION_LABELS: Record<string, string> = {
  experts: "Experts",
  analytics: "Analytics",
  settings: "Settings",
};

export function AppBreadcrumbs({
  experts,
  conversations,
}: {
  experts: ExpertSummary[];
  conversations: ConversationSummary[];
}) {
  const pathname = usePathname();
  const trail = buildTrail(pathname, experts, conversations);

  // Top-level pages still render their single crumb. It duplicates the running
  // head below, but the two are doing different jobs — the trail states where
  // you are in the app, the header names the page and carries its actions —
  // and suppressing it left the header bar empty behind a dangling separator.
  if (trail.length === 0) return null;

  return (
    <Breadcrumb>
      <BreadcrumbList className="gap-1.5 text-[0.8125rem] sm:gap-2">
        {/* The separator is a sibling of the item, never a child: both render
            as <li>, and an <li> inside an <li> is invalid HTML that React
            rejects at hydration. */}
        {trail.map((crumb, i) => {
          const last = i === trail.length - 1;
          return (
            <React.Fragment key={`${crumb.label}-${i}`}>
              <BreadcrumbItem>
                {last || !crumb.href ? (
                  <BreadcrumbPage className="max-w-[16rem] truncate font-medium">
                    {crumb.label}
                  </BreadcrumbPage>
                ) : (
                  <BreadcrumbLink
                    className="max-w-[12rem] truncate underline-offset-4 hover:underline"
                    render={<Link href={crumb.href} />}
                  >
                    {crumb.label}
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {/* A printer's slash rather than a chevron — the arrow is a
                  file-manager idiom, and the rest of this chrome is set like
                  a running head. */}
              {last ? null : (
                <BreadcrumbSeparator className="text-muted-foreground/40 select-none">
                  /
                </BreadcrumbSeparator>
              )}
            </React.Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}

export function buildTrail(
  pathname: string,
  experts: ExpertSummary[],
  conversations: ConversationSummary[],
): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return [];

  const [section, ...rest] = segments;

  if (section === "chats") {
    return chatTrail(rest[0], conversations);
  }

  const label = SECTION_LABELS[section];
  if (!label) return [];

  const trail: Crumb[] = [{ label, href: `/${section}` }];
  if (section === "experts") trail.push(...expertsTrail(rest, experts));

  return collapseLast(trail);
}

/** `/experts/...` below the section root. */
function expertsTrail(rest: string[], experts: ExpertSummary[]): Crumb[] {
  const [slug, leaf] = rest;
  if (!slug) return [];

  if (slug === "new") return [{ label: "New expert" }];

  const expert = experts.find((candidate) => candidate.name === slug);
  // Falls back to the slug: it is what the URL says and what the detail page
  // titles itself with, so an expert missing from the sidebar list still gets
  // an accurate crumb rather than a blank one.
  const trail: Crumb[] = [
    { label: expert?.topic ?? slug, href: `/experts/${slug}` },
  ];

  if (leaf === "chat") trail.push({ label: "Chat" });
  if (leaf === "build") trail.push({ label: "Build" });

  return trail;
}

/** `/chats/{id}` — reparented under the expert it belongs to, since a chat has
 * no standalone index page to climb back to. */
function chatTrail(
  id: string | undefined,
  conversations: ConversationSummary[],
): Crumb[] {
  const conversation = id
    ? conversations.find((candidate) => candidate.id === id)
    : undefined;

  if (!conversation) {
    // Not in the recent list. Everything above it is unknowable from here, so
    // the trail states only what is certain.
    return [{ label: "Experts", href: "/experts" }, { label: "Chat" }];
  }

  return [
    { label: "Experts", href: "/experts" },
    {
      label: conversation.expert_topic,
      href: `/experts/${conversation.expert_slug}`,
    },
    {
      label: conversation.title ?? "Untitled chat",
    },
  ];
}

/** The last crumb is the current page and must not link to itself. */
function collapseLast(trail: Crumb[]): Crumb[] {
  if (trail.length === 0) return trail;
  return trail.map((crumb, i) =>
    i === trail.length - 1 ? { label: crumb.label } : crumb,
  );
}
