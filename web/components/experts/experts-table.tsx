import Link from "next/link";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatusBadge } from "@/components/experts/status-badge";
import { TierBadge } from "@/components/experts/tier-badge";
import type { ExpertSummary } from "@/lib/api/types";

export function ExpertsTable({ experts }: { experts: ExpertSummary[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Topic</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Tier</TableHead>
          <TableHead className="text-right">Sources</TableHead>
          <TableHead className="text-right">Quality</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {experts.map((expert) => (
          <TableRow key={expert.id}>
            <TableCell className="font-medium">
              <Link
                href={`/experts/${expert.name}`}
                className="hover:text-primary hover:underline"
              >
                {expert.name}
              </Link>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {expert.topic}
            </TableCell>
            <TableCell>
              <StatusBadge status={expert.status} />
            </TableCell>
            <TableCell>
              <TierBadge tier={expert.tier} />
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {expert.source_count}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {expert.avg_quality != null
                ? expert.avg_quality.toFixed(2)
                : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
