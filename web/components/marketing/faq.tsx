import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

const FAQS = [
  {
    q: "What's a tier?",
    a: "Lite, standard, and pro control how much of the build budget goes into discovering and validating sources — a lite expert is fast and narrow, a pro expert is slower but pulls from a wider, deeper corpus.",
  },
  {
    q: "How do citations work?",
    a: "Every chat response carries numbered citations back to the exact source chunk it drew from — the same sources that were validated and graphed when the expert was built.",
  },
  {
    q: "What data sources are used?",
    a: "Whatever the build's fetcher allowlist covers — the plan stage decides which sources to search, and every candidate is scored and validated before it's used, no unvetted content included.",
  },
  {
    q: "Is a property graph really different from chunk retrieval?",
    a: "Yes — after sources are chunked and embedded, a separate pass reads them again to extract concepts and relationships into a graph, so an answer can follow a relationship, not just similarity.",
  },
];

export function Faq() {
  return (
    <section id="faq" className="mx-auto max-w-5xl px-4 py-20">
      <h2 className="text-lg font-medium">FAQ</h2>
      <Accordion className="mt-6">
        {FAQS.map((item, i) => (
          <AccordionItem key={item.q} value={`item-${i}`}>
            <AccordionTrigger>{item.q}</AccordionTrigger>
            <AccordionContent className="text-muted-foreground">
              {item.a}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </section>
  );
}
