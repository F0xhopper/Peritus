import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { ContradictionItem, ContradictionSide } from "@/lib/api/types";

// One disagreement, both sides shown together.
//
// The wording throughout is "judged to disagree", never "detects
// contradictions in the literature": this is an edge a language model
// extracted between two concept nodes in a ~40-source corpus. The passages are
// the evidence to check, not proof — so the passages are the main event and
// the model's assertion is the framing.

const KIND: Record<
  ContradictionItem["kind"],
  { label: string; hint: string; variant: "default" | "secondary" | "outline" }
> = {
  cross_source: {
    label: "Between sources",
    hint: "Two different sources in this corpus were judged to disagree.",
    variant: "default",
  },
  within_source: {
    label: "Within one source",
    hint: "A single source was judged to be in tension with itself — not a disagreement between authorities.",
    variant: "secondary",
  },
  undetermined: {
    label: "Undetermined",
    hint: "One side had no resolvable passage, so which sources disagree cannot be established.",
    variant: "outline",
  },
};

function Side({ side, label }: { side: ContradictionSide; label: string }) {
  return (
    <div className="flex flex-1 flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span className="text-eyebrow text-muted-foreground">{label}</span>
        <span className="font-medium">{side.node.label ?? "—"}</span>
      </div>

      {side.node.description ? (
        <p className="text-xs text-pretty text-muted-foreground">
          {side.node.description}
        </p>
      ) : null}

      {side.passages.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">
          No passage could be resolved for this side.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {side.passages.map((p) => (
            <li
              key={p.chunk_id}
              className="rounded-md border border-border/70 bg-muted/30 p-3"
            >
              <blockquote className="text-sm text-pretty">
                {p.excerpt}
                {p.truncated ? <span className="opacity-60">…</span> : null}
              </blockquote>
              <div className="mt-2 text-xs text-muted-foreground">
                {p.source_url ? (
                  <a
                    href={p.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                  >
                    {p.citation}
                  </a>
                ) : (
                  p.citation
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {side.passages_truncated ? (
        <span className="text-xs text-muted-foreground">
          Showing {side.passages.length} of {side.passage_count} passages.
        </span>
      ) : null}
    </div>
  );
}

export function ContradictionCard({ item }: { item: ContradictionItem }) {
  const kind = KIND[item.kind];
  return (
    <Card className="rounded-lg">
      <CardContent className="flex flex-col gap-4 pt-6">
        <div className="flex items-center gap-2">
          <Badge variant={kind.variant} className="font-normal">
            {kind.label}
          </Badge>
          <span className="text-xs text-muted-foreground">{kind.hint}</span>
        </div>

        <div className="flex flex-col gap-5 md:flex-row md:gap-8">
          <Side side={item.side_a} label="Claim" />
          {/* A rule rather than a word: "vs" would assert a verdict the corpus
              does not support. */}
          <div
            className="hidden w-px shrink-0 self-stretch bg-border md:block"
            aria-hidden
          />
          <Side side={item.side_b} label="Counter-claim" />
        </div>
      </CardContent>
    </Card>
  );
}
