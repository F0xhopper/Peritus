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
      <h2 className="text-lg font-medium">How it works</h2>
      <div className="mt-8 grid gap-6 sm:grid-cols-3">
        {STEPS.map((step) => (
          <div key={step.n} className="flex flex-col gap-2">
            <span className="font-mono text-sm text-muted-foreground">
              {step.n}
            </span>
            <h3 className="font-medium">{step.title}</h3>
            <p className="text-sm text-muted-foreground">
              {step.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
