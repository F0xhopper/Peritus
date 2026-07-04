import { PlusIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ComingSoon } from "@/components/coming-soon";

export default function NewExpertPage() {
  return (
    <>
      <PageHeader icon={PlusIcon} title="New expert" />
      <ComingSoon
        phase="phase 4"
        description="The build form (topic, tier picker, optional fetcher allowlist) submits to POST /experts/build and lands here — wired once the dashboard shell is reviewed."
      />
    </>
  );
}
