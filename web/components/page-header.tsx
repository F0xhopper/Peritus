import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

// Set as a running head: the title small and wide in capitals. A book names
// the page at the top of the leaf in a voice quieter than the text it
// introduces — which is also the honest hierarchy here, since "Experts" is a
// location, not a headline. The rule that used to sit under the whole row is
// gone: the size and tracking already separate this from body text, and the
// gap to the content below carries the rest.

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
    <div className="flex items-center justify-between gap-4">
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
