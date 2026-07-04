import { BarChart3Icon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ComingSoon } from "@/components/coming-soon";

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader icon={BarChart3Icon} title="Analytics" />
      <ComingSoon
        phase="phase 8, stretch"
        description="Cross-expert builds-over-time, source-type breakdown, and quality distribution — built once the per-expert views it aggregates already exist."
      />
    </>
  );
}
