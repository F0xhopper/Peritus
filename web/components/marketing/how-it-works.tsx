import { SectionHeading } from "@/components/marketing/section-heading";

const STEPS = [
  {
    n: "01",
    title: "Plan",
    description:
      "Claude drafts a research brief — per-source search queries and the key concepts the corpus must cover.",
  },
  {
    n: "02",
    title: "Discover, validate, graph",
    description:
      "Sources are fetched, scored against the brief, chunked and embedded, then read again to extract a concept graph.",
  },
  {
    n: "03",
    title: "Chat with citations",
    description:
      "A named persona answers from the graph and its sources, with a numbered citation on every claim.",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="mx-auto max-w-5xl px-4 py-20">
      <SectionHeading eyebrow="The build" title="How it works" />
      <div className="mt-10 grid gap-8 sm:grid-cols-3">
        {STEPS.map((step) => (
          // Each step is numbered like a folio: the figure large and quiet in
          // the display face, with a hairline under it, then the head.
          <div key={step.n} className="flex flex-col gap-2">
            <span className="font-display text-2xl leading-none font-semibold text-muted-foreground/60 lining-nums">
              {step.n}
            </span>
            <div aria-hidden className="h-px w-8 bg-border" />
            <h3 className="mt-1 font-display text-[0.9375rem] font-semibold tracking-wide">
              {step.title}
            </h3>
            <p className="text-sm leading-relaxed text-muted-foreground">
              {step.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
