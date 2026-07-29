import { cn } from "@/lib/utils";
import { personaInitials } from "@/lib/persona";

// A monogram, not an image. There is no photograph of an expert that was
// assembled out of a corpus this morning, and a generated portrait would claim
// a person who does not exist — so the avatar is the initials of the name the
// build actually produced.
//
// Deliberately not <Avatar> from ui/avatar: that one exists to cross-fade a
// remote image into a fallback and pulls a client boundary in with it. There
// is no image here, so this stays a span the server can render.

export function PersonaAvatar({
  label,
  size = "default",
  className,
}: {
  /** The name being represented — titled persona or, failing that, the topic. */
  label: string;
  size?: "default" | "lg";
  className?: string;
}) {
  return (
    <span
      // The name is already printed beside it in every current placement, so
      // the monogram is decoration and repeating it would just make screen
      // readers say the name twice.
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-muted font-display font-medium tracking-[0.06em] text-muted-foreground ring-1 ring-border/70 select-none",
        size === "lg" ? "size-11 text-sm" : "size-9 text-xs",
        className,
      )}
    >
      {personaInitials(label)}
    </span>
  );
}
