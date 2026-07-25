import { cn } from "@/lib/utils";

// The mark is the name, set in inscriptional capitals and widely tracked —
// nothing else. It had a boxed blackletter versal in front of it; that came
// off, and the blackletter face moved to the illuminated drop cap in
// globals.css, which is the job it was actually cut for. A logotype has to
// stay legible at 13px in a collapsed sidebar, and blackletter never is.
//
// Sizing is set by eye rather than inherited: `font-size-adjust` on the body
// normalizes x-height across faces, which is right for running text and wrong
// for a logotype that should render identically everywhere it appears.

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
