import { cn } from "@/lib/utils";

// The identity, in three pieces that can be used apart:
//
//   BrandMark  the glyph alone — the only form that survives the collapsed
//              sidebar rail, where there is ~24px of width and no room for
//              letters
//   Wordmark   the name alone, set in plain capitals and widely tracked
//   Logo       the lockup: mark + name, optionally over a descriptor line
//
// The mark is a solid tile carrying a single letter, deliberately squared
// against PersonaAvatar's round monogram: an expert is a person and gets a
// circle, the product is a thing and gets a block. Both are drawn from type
// rather than art, which is the whole visual argument of this app — it is set,
// not illustrated.
//
// Sizing is set by eye rather than inherited: `font-size-adjust` on the body
// normalizes x-height across faces, which is right for running text and wrong
// for a logotype that should render identically everywhere it appears.

export function BrandMark({
  className,
  size = "default",
}: {
  className?: string;
  size?: "sm" | "default" | "lg";
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-[0.3em] bg-foreground font-display font-semibold text-background select-none [font-size-adjust:none]",
        size === "sm"
          ? "size-5 text-[0.6875rem]"
          : size === "lg"
            ? "size-9 text-lg"
            : "size-7 text-sm",
        className,
      )}
    >
      P
    </span>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "font-display text-[0.9375rem] leading-none font-semibold tracking-[0.22em] uppercase [font-size-adjust:none]",
        className,
      )}
    >
      Peritus
    </span>
  );
}

/** Mark and name locked together, with an optional descriptor under the name.
 *
 * The descriptor is off by default: it earns its place in the sidebar, where
 * it is the only thing on screen saying what the app is, and gets in the way
 * on the marketing nav where the page below it already says so. */
export function Logo({
  className,
  tagline,
  markSize = "default",
}: {
  className?: string;
  tagline?: string;
  markSize?: "sm" | "default" | "lg";
}) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <BrandMark size={markSize} />
      <span className="flex min-w-0 flex-col gap-1">
        <Wordmark />
        {tagline ? (
          <span className="text-[0.625rem] leading-none tracking-[0.08em] text-muted-foreground">
            {tagline}
          </span>
        ) : null}
      </span>
    </span>
  );
}
