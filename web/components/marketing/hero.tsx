import Link from "next/link";
import { Button } from "@/components/ui/button";

export function Hero() {
  return (
    <section className="mx-auto flex max-w-2xl flex-col items-center gap-6 px-4 py-20 text-center lg:py-28">
      <h1 className="text-3xl font-medium tracking-tight sm:text-4xl">
        Build an expert from your sources.
        <br />
        Chat with it — every answer cited.
      </h1>
      <p className="max-w-md text-muted-foreground">
        Peritus reads, validates, and graphs a corpus into a
        graph-grounded expert agent — then answers your questions from
        that graph, with a citation on every claim.
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
