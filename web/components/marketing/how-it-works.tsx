import { SectionHeading } from "@/components/marketing/section-heading";

const STEPS = [
  {
    n: "01",
    title: "Plan the search",
    description:
      "Claude turns your topic into a tailored query for each source type, and names the five to eight concepts the corpus has to cover. That concept list is what the finished corpus gets checked against.",
  },
  {
    n: "02",
    title: "Search wide, screen with reasons",
    description:
      "Fetchers over-search in parallel, a triage pass ranks candidates before anything is downloaded, and the survivors are scored for quality and relevance. Each keep or drop is recorded with its score and, when dropped, its reason.",
  },
  {
    n: "03",
    title: "Close the gaps",
    description:
      "Accepted sources are tagged against the target concepts. Any concept still uncovered triggers another round of searching — so what you end up with is a corpus and an argument for why it is sufficient.",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="mx-auto max-w-5xl px-4 py-20">
      <SectionHeading eyebrow="The build" title="How it works">
        Afterwards the corpus is chunked, embedded and read again into a concept
        graph, so you can question it and get numbered citations back to the
        passages the answer actually came from.
      </SectionHeading>
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
