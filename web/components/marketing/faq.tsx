import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { SectionHeading } from "@/components/marketing/section-heading";

// The first four answers are the ones that say no. They lead deliberately: the
// audience for this tool is trained to look for the overclaim, and the fastest
// way to lose them is to make them find it themselves.

const FAQS = [
  {
    q: "Is this PRISMA compliant?",
    a: "No — and no tool can be. PRISMA describes how you report a review, not which software produced it; compliance is a property of your write-up. What Peritus does is record the data those reports ask for as a byproduct of the build: how many records were identified, how many were screened, how many were excluded, and the reason for each exclusion.",
  },
  {
    q: "Does this replace a second reviewer?",
    a: "No. Screening decisions come from a single model pass against a versioned rubric. There is no second independent judgement, no inter-rater agreement statistic, and no published sensitivity or specificity — there is no calibration set to compute them from. Treat the output as triage you can audit, not as an independent review. The value is that every decision arrives with the score and reason attached, so checking it is an afternoon rather than a fortnight.",
  },
  {
    q: "How many sources does a build handle?",
    a: "Dozens, not thousands — roughly ten on lite, twenty on standard, forty on pro. Peritus is built to find and appraise material that never had a database record, not to screen a three-thousand-record export. If you have that export, keep screening it in the tool you already use; this is for the half of the search that tool never sees.",
  },
  {
    q: "Can I export the record?",
    a: "Yes — as CSV, or as RIS for your reference manager. The export carries the full record for every source considered: quality and relevance scores, drop reason, validator model, rubric version, discovery path and concept coverage. RIS matters because a grey-literature source has no bibliographic record to import from anywhere else, so this is usually the only way those findings reach Zotero or EndNote alongside your database records. You can export everything, or just the sources that were kept, or just the ones that were dropped.",
  },
  {
    q: "What does it actually search?",
    a: "Nine fetchers: the open web, arbitrary PDFs read by OCR, arXiv preprints, Wikipedia, public-domain books from Project Gutenberg, YouTube transcripts, Reddit, Exa neural search, and named thought-leaders. High-citation references from accepted arXiv papers are snowballed in via Semantic Scholar. You can restrict any build to a subset of those fetchers.",
  },
  {
    q: "What does it mean when you say sources disagree?",
    a: "When the concept graph is extracted, relationships between concepts are typed — including where one source contradicts another. Retrieval prefers those edges and the answer is asked to surface the tension rather than smooth it over. It is a pointer telling you where to go and look, not a finding: the edges are asserted by a model reading the text, not derived from a citation network. The judgement stays yours.",
  },
  {
    q: "What's a tier?",
    a: "Lite, standard and pro set the depth and cost of a build. A lite build searches narrowly and finishes quickly; a pro build searches wider, retrieves more, and reasons over more of the corpus when you question it. Builds cost real money in API calls, so the tier is the dial for how much of that you want to spend.",
  },
];

export function Faq() {
  return (
    <section id="faq" className="mx-auto max-w-5xl px-4 py-20">
      <SectionHeading eyebrow="Questions" title="What this is not" />
      <Accordion className="mt-8">
        {FAQS.map((item, i) => (
          <AccordionItem key={item.q} value={`item-${i}`}>
            <AccordionTrigger>{item.q}</AccordionTrigger>
            <AccordionContent className="max-w-measure leading-relaxed text-muted-foreground">
              {item.a}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </section>
  );
}
