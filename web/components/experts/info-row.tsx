import type { LucideIcon } from "lucide-react";

// One line of a contact-style info list: icon, label, value pinned right.
// Shared by the experts grid card and the expert detail profile panel so the
// same "person, not a record" list reads identically in both places.

export function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground/70" />
      <span className="text-muted-foreground">{label}</span>
      <span className="ml-auto font-medium text-foreground tabular-nums lining-nums capitalize">
        {value}
      </span>
    </div>
  );
}
