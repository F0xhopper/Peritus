import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Wordmark } from "@/components/brand/wordmark";

const LINKS = [
  { href: "#product", label: "Capabilities" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#faq", label: "FAQ" },
];

export function SiteNav() {
  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <Link href="/">
          <Wordmark />
        </Link>
        {/* Navigation is something you scan and click, so it stays in the
            reading face alongside the buttons — only the wordmark beside it
            speaks in the display voice. */}
        <nav className="hidden items-center gap-7 text-sm text-muted-foreground sm:flex">
          {LINKS.map((link) => (
            <a key={link.href} href={link.href} className="hover:text-foreground">
              {link.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            nativeButton={false}
            render={<Link href="/login" />}
          >
            Sign in
          </Button>
          <Button size="sm" nativeButton={false} render={<Link href="/login" />}>
            Get started
          </Button>
        </div>
      </div>
    </header>
  );
}
