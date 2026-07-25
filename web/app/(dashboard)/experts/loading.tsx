import { UsersIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ExpertsGridSkeleton } from "@/components/experts/expert-card-skeleton";

export default function ExpertsLoading() {
  return (
    <>
      <PageHeader icon={UsersIcon} title="Experts" />
      <ExpertsGridSkeleton />
    </>
  );
}
