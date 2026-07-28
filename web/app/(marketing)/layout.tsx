import type { Metadata } from "next";
import { SiteNav } from "@/components/marketing/site-nav";
import { SiteFooter } from "@/components/marketing/site-footer";

// Overrides the root layout's title/description for the marketing route group
// only; the dashboard keeps the root metadata. Static export, per
// node_modules/next/dist/docs/01-app/03-api-reference/04-functions/generate-metadata.md.
export const metadata: Metadata = {
  title: "Peritus — a search you can defend",
  description:
    "Search the literature a database export misses, and keep a record of every source considered: what it scored, why it was dropped, and which search found it.",
};

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteNav />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
