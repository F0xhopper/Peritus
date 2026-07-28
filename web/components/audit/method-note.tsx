import type { ReactNode } from "react";

// The backend attaches a `method_statement` (and per-block `note`) to almost
// every audit response, describing how the record was produced and where it
// stops being trustworthy. Those notes are the difference between a number and
// a defensible number, so they are rendered next to the data rather than
// tucked into a help page.

export function MethodNote({ children }: { children: ReactNode }) {
  return (
    <p className="border-l-2 border-border/70 py-0.5 pl-3 text-xs leading-relaxed text-pretty text-muted-foreground">
      {children}
    </p>
  );
}
