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
//
// Each label gets a distinct tint pulled from the grayscale chart ramp
// (globals.css --chart-1..5 — the same no-hue palette charts use, so this
// doesn't invent a second scale). The hash is deterministic, so the same
// expert gets the same tone everywhere it's rendered — card, detail page,
// chat header — without threading a color through props.
function hashTone(label: string): number {
  let hash = 0;
  for (const char of label) {
    hash = (hash * 31 + char.codePointAt(0)!) | 0;
  }
  return Math.abs(hash) % TONES.length;
}

const TONES = [
  "bg-chart-1 text-background",
  "bg-chart-2 text-background",
  "bg-chart-3 text-foreground",
  "bg-chart-4 text-foreground",
  "bg-chart-5 text-foreground",
];

export function PersonaAvatar({
  label,
  size = "default",
  className,
}: {
  /** The name being represented — titled persona or, failing that, the topic. */
  label: string;
  size?: "default" | "lg" | "xl";
  className?: string;
}) {
  return (
    <span
      // The name is already printed beside it in every current placement, so
      // the monogram is decoration and repeating it would just make screen
      // readers say the name twice.
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-display font-medium tracking-[0.06em] select-none",
        TONES[hashTone(label)],
        size === "xl"
          ? "size-16 text-lg ring-2 ring-border"
          : size === "lg"
            ? "size-11 text-sm ring-1 ring-border/70"
            : "size-9 text-xs ring-1 ring-border/70",
        className,
      )}
    >
      {personaInitials(label)}
    </span>
  );
}
