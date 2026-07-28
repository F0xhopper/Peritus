import { ExternalLinkIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { LedgerSource } from "@/lib/api/types";
import { DiscoveryBadge } from "@/components/audit/discovery-badge";

// The ledger itself: what was kept, what was dropped, and why.
//
// Rejected rows are not a debug view — they are the evidence that the accepted
// ones were selected — so they render at full fidelity alongside the accepted
// ones rather than behind a toggle.

function Score({ value, min }: { value: number | null; min: number }) {
  if (value === null) {
    return <span className="text-muted-foreground/70 italic">&mdash;</span>;
  }
  const below = value < min;
  return (
    <span
      className={
        below ? "tabular-nums text-muted-foreground" : "tabular-nums text-foreground"
      }
      title={below ? `Below the ${min} threshold` : undefined}
    >
      {value.toFixed(1)}
    </span>
  );
}

export function LedgerTable({
  sources,
  qualityMin,
  relevanceMin,
}: {
  sources: LedgerSource[];
  qualityMin: number;
  relevanceMin: number;
}) {
  if (sources.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No sources match this filter.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-20">Decision</TableHead>
            <TableHead className="min-w-[18rem]">Source</TableHead>
            <TableHead className="w-28">Found by</TableHead>
            <TableHead className="w-14 text-right">Q</TableHead>
            <TableHead className="w-14 text-right">R</TableHead>
            <TableHead className="min-w-[14rem]">Reason dropped</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((s) => (
            <TableRow key={s.id} className="align-top">
              <TableCell>
                <Badge
                  variant={s.decision === "accepted" ? "secondary" : "outline"}
                  className={
                    s.decision === "rejected"
                      ? "text-muted-foreground"
                      : undefined
                  }
                >
                  {s.decision === "accepted" ? "Kept" : "Dropped"}
                </Badge>
              </TableCell>

              <TableCell>
                <div className="flex flex-col gap-0.5">
                  {s.url ? (
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-start gap-1 font-medium text-foreground hover:underline"
                    >
                      <span className="line-clamp-2">{s.title ?? s.url}</span>
                      <ExternalLinkIcon className="mt-0.5 size-3 shrink-0 opacity-60" />
                    </a>
                  ) : (
                    <span className="line-clamp-2 font-medium">
                      {s.title ?? "Untitled"}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {[s.source_type, s.author].filter(Boolean).join(" · ")}
                    {s.passage_count > 0
                      ? ` · ${s.passage_count} passage${s.passage_count === 1 ? "" : "s"}`
                      : ""}
                  </span>
                </div>
              </TableCell>

              <TableCell>
                <DiscoveryBadge
                  method={s.discovery_method}
                  concept={s.gap_filled_for_concept}
                  raw={s.discovered_via}
                />
              </TableCell>

              <TableCell className="text-right">
                <Score value={s.quality_score} min={qualityMin} />
              </TableCell>
              <TableCell className="text-right">
                <Score value={s.relevance_score} min={relevanceMin} />
              </TableCell>

              <TableCell className="text-xs text-pretty text-muted-foreground">
                {s.decision === "rejected" ? (
                  (s.drop_reason ?? (
                    <span className="italic opacity-70">no reason recorded</span>
                  ))
                ) : (
                  <span aria-hidden>&mdash;</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
