import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

// Set as a running head: the title small and wide in capitals, with a rule
// under the whole row. A book names the page at the top of the leaf in a voice
// quieter than the text it introduces — which is also the honest hierarchy
// here, since "Experts" is a location, not a headline.

export function PageHeader({
  icon: Icon,
  title,
  action,
}: {
  icon: LucideIcon;
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border pb-3">
      <div className="flex min-w-0 items-center gap-2.5 text-muted-foreground">
        <Icon className="size-3.5 shrink-0" />
        <h1 className="truncate font-display text-sm font-semibold tracking-[0.18em] text-foreground uppercase">
          {title}
        </h1>
      </div>
      {action}
    </div>
  );
}
