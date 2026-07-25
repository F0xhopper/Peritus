import { NetworkIcon, QuoteIcon, LayersIcon, TerminalSquareIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { SectionHeading } from "@/components/marketing/section-heading";

const FEATURES = [
  {
    icon: NetworkIcon,
    title: "Graph-grounded, not chunk retrieval",
    description:
      "Every expert builds a property graph of concepts and relationships from its sources, so answers draw on structure — not just nearest-neighbor chunks.",
  },
  {
    icon: QuoteIcon,
    title: "Every answer is cited",
    description:
      "Chat responses carry numbered citations back to the exact source, every time — no unverifiable claims.",
  },
  {
    icon: LayersIcon,
    title: "Lite, standard, and pro tiers",
    description:
      "Pick the build depth per expert: fewer sources for a fast lite build, or a wider, deeper corpus for pro.",
  },
  {
    icon: TerminalSquareIcon,
    title: "CLI, TUI, and web — one session",
    description:
      "Build and chat from the terminal or the browser. Signing in once carries the same session everywhere.",
  },
];

export function FeatureGrid() {
  return (
    <section id="product" className="mx-auto max-w-5xl px-4 py-20">
      <SectionHeading eyebrow="Capabilities" title="What you get" />
      <div className="mt-10 grid gap-4 sm:grid-cols-2">
        {FEATURES.map((feature) => (
          <Card key={feature.title} className="rounded-lg">
            <CardContent className="flex flex-col gap-2.5">
              <feature.icon className="size-4 text-muted-foreground" />
              <h3 className="font-display text-[0.9375rem] font-semibold tracking-wide">
                {feature.title}
              </h3>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {feature.description}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
