import { DownloadIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { SourceDecision } from "@/lib/api/types";

// RIS is the one that matters operationally: it is what Covidence, Zotero and
// EndNote import, so it is how a grey-literature source Peritus found reaches
// the review the user is actually running. CSV is for reading in a spreadsheet.

export function ExportMenu({
  slug,
  decision,
}: {
  slug: string;
  decision: SourceDecision;
}) {
  const href = (format: "csv" | "ris") =>
    `/api/experts/${encodeURIComponent(slug)}/corpus-report/export?format=${format}&decision=${decision}`;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button size="sm" variant="outline" />}>
        <DownloadIcon className="size-3.5" />
        Export
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Includes dropped sources, their exclusion reason, and the search that
          found each one.
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<a href={href("ris")} download />}>
          RIS
          <span className="ml-auto text-xs text-muted-foreground">
            Covidence, Zotero
          </span>
        </DropdownMenuItem>
        <DropdownMenuItem render={<a href={href("csv")} download />}>
          CSV
          <span className="ml-auto text-xs text-muted-foreground">
            spreadsheet
          </span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
