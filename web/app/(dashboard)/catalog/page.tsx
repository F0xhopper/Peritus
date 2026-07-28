import Link from "next/link";
import { LibraryIcon, MessageSquareIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getCatalog } from "@/lib/api/data";
import type { CatalogEntry } from "@/lib/api/types";

// The first-90-seconds page: finished experts a new account can question
// immediately, instead of waiting on a build it has not paid for. Chat here is
// free and ungated — builds are the capex, this is the shop window.

export const metadata = {
  title: "Catalog · Peritus",
};

function ReadinessNote({ entry }: { entry: CatalogEntry }) {
  if (entry.readiness === "chat_ready") {
    return (
      <span className="text-xs text-muted-foreground">
        Answering now · concept graph still building
      </span>
    );
  }
  return null;
}

export default async function CatalogPage() {
  const entries = await getCatalog();

  return (
    <>
      <PageHeader icon={LibraryIcon} title="Catalog" />

      {entries.length === 0 ? (
        <Card className="rounded-lg border-dashed">
          <CardContent className="py-12 text-center">
            <p className="font-medium">Nothing published yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Published experts appear here for anyone to question.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {entries.map((e) => (
            <Card key={e.name} className="rounded-lg">
              <CardContent className="flex h-full flex-col gap-3 pt-6">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="font-display text-lg">
                      {e.persona_name ?? e.topic}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {e.topic}
                    </span>
                  </div>
                  {e.is_featured ? (
                    <Badge className="shrink-0 font-normal">Featured</Badge>
                  ) : null}
                </div>

                {e.blurb ? (
                  <p className="text-sm text-pretty text-muted-foreground">
                    {e.blurb}
                  </p>
                ) : null}

                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>
                    <span className="tabular-nums text-foreground">
                      {e.source_count}
                    </span>{" "}
                    sources
                  </span>
                  {e.avg_quality != null ? (
                    <span>
                      mean quality{" "}
                      <span className="tabular-nums text-foreground">
                        {e.avg_quality.toFixed(1)}
                      </span>
                    </span>
                  ) : null}
                  {e.category ? <span>{e.category}</span> : null}
                </div>

                <div className="mt-auto flex items-center justify-between gap-2 pt-2">
                  <ReadinessNote entry={e} />
                  <div className="ml-auto flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      render={<Link href={`/experts/${e.name}/ledger`} />}
                    >
                      Ledger
                    </Button>
                    <Button
                      size="sm"
                      render={<Link href={`/experts/${e.name}/chat`} />}
                    >
                      <MessageSquareIcon className="size-3.5" />
                      Ask
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
