import {
  TelescopeIcon,
  ClipboardCheckIcon,
  RouteIcon,
  SplitIcon,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { SectionHeading } from "@/components/marketing/section-heading";

// Every claim below is a description of something the build pipeline actually
// records. Nothing here describes a planned feature: the fetcher list is the
// one in sources/fetchers, the scores and drop reasons are columns on the
// `sources` table, and `discovered_via` is the provenance stamp written in
// experts/builder.py. If a claim can't be pointed at a column, it doesn't ship.

const FEATURES = [
  {
    icon: TelescopeIcon,
    title: "The sources an export misses",
    description:
      "Nine fetchers run in parallel: the open web, PDFs read by OCR, preprints, public-domain books, conference talks by transcript, and practitioner discussion. The grey literature that never had a database record.",
  },
  {
    icon: ClipboardCheckIcon,
    title: "Every source scored, every rejection reasoned",
    description:
      "Claude scores each source for quality and relevance against a versioned rubric. Anything below threshold is dropped with its reason recorded — alongside the model that judged it and the rubric version it was judged under.",
  },
  {
    icon: RouteIcon,
    title: "A record of which search found what",
    description:
      "Each source is stamped with how it entered the corpus: the planned search, a citation snowball from a paper already accepted, or a gap-fill round aimed at a concept the corpus was still missing.",
  },
  {
    icon: SplitIcon,
    title: "Gaps and disagreements, surfaced",
    description:
      "The plan names the concepts the corpus has to cover, and uncovered ones trigger another round of searching. Where sources contradict each other, the concept graph records the edge and answers are asked to surface the tension.",
  },
];

export function FeatureGrid() {
  return (
    <section id="product" className="mx-auto max-w-5xl px-4 py-20">
      <SectionHeading eyebrow="Capabilities" title="What gets recorded">
        A reviewer who asks how you assembled this evidence should get an answer
        with a shape to it — not a sentence saying you also searched the web.
      </SectionHeading>
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
