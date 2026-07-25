import type { ReactNode } from "react";

// A chapter head: standing line in capitals, the title in the display face,
// and a short rule under it. The rule is deliberately stub-length rather than
// full-bleed — a printer's mark closing the head, not a divider splitting the
// page in two.

export function SectionHeading({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-eyebrow text-muted-foreground">{eyebrow}</p>
      <h2 className="font-display text-xl font-semibold tracking-[0.06em]">
        {title}
      </h2>
      <div aria-hidden className="mt-1 h-px w-16 bg-foreground/30" />
      {children ? (
        <p className="mt-2 max-w-measure text-muted-foreground">{children}</p>
      ) : null}
    </div>
  );
}
