import { Wordmark } from "@/components/brand/wordmark";

export function SiteFooter() {
  return (
    <footer className="border-t border-border/60">
      <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-4 px-4 py-8 text-sm text-muted-foreground sm:flex-row">
        <Wordmark />
        {/* The colophon line: what made the book, set quietly at the foot. */}
        <p>© 2026 Peritus. A record of how the evidence was assembled.</p>
      </div>
    </footer>
  );
}
