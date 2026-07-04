export function SiteFooter() {
  return (
    <footer className="border-t border-border/60">
      <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-4 px-4 py-8 text-sm text-muted-foreground sm:flex-row">
        <div className="flex items-center gap-1">
          <span className="text-primary" aria-hidden>
            {">"}
          </span>
          <span>peritus</span>
        </div>
        <p>© 2026 Peritus. Graph-grounded experts, built from your sources.</p>
      </div>
    </footer>
  );
}
