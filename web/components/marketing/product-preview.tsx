import { UsersIcon, PlusIcon } from "lucide-react";
import { ExpertsGrid } from "@/components/experts/experts-grid";
import { MOCK_EXPERTS } from "@/lib/mock-data";

export function ProductPreview() {
  // Two cards, not three: the preview frame is capped at max-w-5xl while the
  // grid's breakpoints track the viewport, so a third column would render
  // cramped inside the mock browser chrome.
  const preview = MOCK_EXPERTS.slice(0, 2);

  return (
    <section className="mx-auto max-w-5xl px-4 py-20">
      <h2 className="text-lg font-medium">Your experts</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        Every expert you build, with the persona it speaks as and the concepts
        it actually covers — not just a row of build counters.
      </p>
      <div className="mt-8 overflow-hidden rounded-lg bg-card ring-1 ring-foreground/10">
        <div className="flex items-center gap-1.5 border-b border-border/60 px-3 py-2">
          <span className="size-2 rounded-full bg-foreground/20" />
          <span className="size-2 rounded-full bg-foreground/35" />
          <span className="size-2 rounded-full bg-foreground/50" />
          <span className="ml-2 text-xs text-muted-foreground">
            peritus.app/experts
          </span>
        </div>
        {/* `inert` rather than aria-hidden: these cards contain real links, and
            a focusable element inside an aria-hidden subtree is reachable by
            keyboard while invisible to a screen reader. inert removes both. */}
        <div className="flex select-none flex-col gap-4 p-4 sm:p-6" inert>
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-muted-foreground">
              <UsersIcon className="size-4" />
              <span className="text-base font-medium text-foreground">
                Experts
              </span>
            </div>
            <span className="flex h-7 items-center gap-1 rounded-lg bg-primary px-2.5 text-[0.8rem] font-medium text-primary-foreground">
              <PlusIcon className="size-3.5" />
              New expert
            </span>
          </div>
          <ExpertsGrid experts={preview} />
        </div>
      </div>
    </section>
  );
}
