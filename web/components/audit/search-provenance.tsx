import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MethodNote } from "@/components/audit/method-note";
import type { SearchProvenanceRow } from "@/lib/api/types";

// The corpus grouped by which search produced it — a primary view, not a
// filter. Every incumbent evidence tool begins from a database export, so this
// dimension does not exist for them: there, all records arrived one way.

function Bar({ accepted, rejected }: { accepted: number; rejected: number }) {
  const total = accepted + rejected;
  if (total === 0) return null;
  const pct = (accepted / total) * 100;
  return (
    <div
      className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted"
      role="img"
      aria-label={`${accepted} kept, ${rejected} dropped`}
    >
      <div className="bg-foreground/70" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function SearchProvenance({
  searches,
  note,
}: {
  searches: SearchProvenanceRow[];
  note: string;
}) {
  if (searches.length === 0) return null;

  return (
    <Card className="rounded-lg">
      <CardHeader>
        <CardTitle className="text-sm text-muted-foreground">
          Which search found what
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <ul className="flex flex-col gap-4">
          {searches.map((s) => (
            <li key={s.discovered_via} className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium">
                  {s.method === "gapfill" && s.concept ? (
                    <>
                      Gap-fill:{" "}
                      <span className="text-muted-foreground">{s.concept}</span>
                    </>
                  ) : (
                    (s.discovered_via ?? "not recorded")
                  )}
                </span>
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                  {s.accepted} kept / {s.considered} considered
                </span>
              </div>
              <Bar accepted={s.accepted} rejected={s.rejected} />
              {s.source_types.length > 0 ? (
                <span className="text-xs text-muted-foreground">
                  {s.source_types.join(", ")}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        <MethodNote>{note}</MethodNote>
      </CardContent>
    </Card>
  );
}
