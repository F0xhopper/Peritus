import Link from "next/link";
import { Button } from "@/components/ui/button";

// Laid out as a title page: standing head, title in capitals, a ruled break,
// then the opening paragraph set to measure with an illuminated initial. The
// title stays centred the way a title page centres; the lead goes flush left,
// because a drop cap needs a straight left edge to sink into and centred body
// copy is unreadable past a couple of lines anyway.

export function Hero() {
  return (
    <section className="mx-auto flex max-w-2xl flex-col items-center gap-7 px-4 py-20 lg:py-28">
      <p className="text-eyebrow text-muted-foreground">Evidence synthesis</p>

      <h1 className="text-center font-display text-3xl leading-[1.2] font-semibold tracking-[0.04em] text-balance sm:text-4xl">
        A search
        <br />
        you can defend
      </h1>

      <div className="rule-ornament w-full max-w-xs">◆</div>

      <p className="dropcap max-w-measure text-[1.0625rem] leading-[1.7] text-muted-foreground">
        Peritus searches the literature a database export misses — reports,
        preprints, standards, conference talks, practitioner writing — and
        records every source it considered: what it scored for quality and
        relevance, the reason it was dropped, and which search turned it up.
      </p>

      <div className="flex items-center gap-3">
        <Button nativeButton={false} render={<Link href="/login" />}>
          Get started
        </Button>
        <Button
          variant="outline"
          nativeButton={false}
          render={<Link href="#how-it-works" />}
        >
          How it works
        </Button>
      </div>

      {/* The epigraph: set small and quiet under the call to action, because it
          is a caveat rather than a claim — but kept above the fold, since being
          straight about what this is not is most of the argument for it. */}
      <p className="max-w-measure text-center text-sm text-muted-foreground/80">
        A first pass that shows its working — for a human reviewer to check, not
        to replace.
      </p>
    </section>
  );
}
