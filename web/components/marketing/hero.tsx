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
      <p className="text-eyebrow text-muted-foreground">
        Graph-grounded expert agents
      </p>

      <h1 className="text-center font-display text-3xl leading-[1.2] font-semibold tracking-[0.04em] text-balance sm:text-4xl">
        Build an expert
        <br />
        from your sources
      </h1>

      <div className="rule-ornament w-full max-w-xs">◆</div>

      <p className="dropcap max-w-measure text-[1.0625rem] leading-[1.7] text-muted-foreground">
        Peritus reads, validates, and graphs a corpus into a graph-grounded
        expert agent — then answers your questions from that graph, with a
        citation on every claim.
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
    </section>
  );
}
