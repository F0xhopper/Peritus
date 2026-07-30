import { FileTextIcon, LayersIcon, NetworkIcon, type LucideIcon } from "lucide-react";
import { Card, CardTitle, CardDescription } from "@/components/ui/card";
import { StatusBadge } from "@/components/experts/status-badge";
import { TierBadge } from "@/components/experts/tier-badge";
import { ExpertMenu } from "@/components/experts/expert-menu";
import { ChatButton } from "@/components/chat/chat-button";
import { PersonaAvatar } from "@/components/experts/persona-avatar";
import { formatCompact } from "@/lib/format";
import { personaLabel } from "@/lib/persona";
import type { ExpertDetail } from "@/lib/api/types";

// The identity bar shared by every audit tab (Overview/Sources/Coverage): who
// this is, its build status, and the one action (chat) you came here for. A
// header rather than a side rail, so it never eats width from the tables and
// reports that sit under it.

export function ExpertProfileHeader({ expert }: { expert: ExpertDetail }) {
  const persona = personaLabel(expert.persona_name);
  const heading = persona ?? expert.topic;

  return (
    <Card className="flex-row flex-wrap items-center gap-4 p-4">
      <PersonaAvatar label={heading} size="xl" />

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {/* Name (+ status/tier) on the left, stats pushed to the top-right of
            the same row — the description sits underneath on its own line
            rather than crowding this row. */}
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{heading}</CardTitle>
            <StatusBadge status={expert.status} />
            <TierBadge tier={expert.tier} />
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-muted-foreground">
            <Stat icon={FileTextIcon} value={formatCompact(expert.source_count)} label="sources" />
            <Stat icon={LayersIcon} value={formatCompact(expert.chunk_count)} label="chunks" />
            <Stat icon={NetworkIcon} value={formatCompact(expert.node_count)} label="graph nodes" />
          </div>
        </div>
        {/* Only shown once there's a persona name to distinguish from the
            topic — otherwise the topic would repeat right under itself. */}
        {persona ? (
          <CardDescription className="text-xs">{expert.topic}</CardDescription>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        <ChatButton slug={expert.name} status={expert.status} />
        <ExpertMenu slug={expert.name} topic={expert.topic} redirectTo="/experts" />
      </div>
    </Card>
  );
}

function Stat({
  icon: Icon,
  value,
  label,
}: {
  icon: LucideIcon;
  value: string;
  label: string;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground/70" />
      <span className="font-medium text-foreground tabular-nums lining-nums">
        {value}
      </span>
      {label}
    </span>
  );
}
