import { SettingsIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ComingSoon } from "@/components/coming-soon";

export default function SettingsPage() {
  return (
    <>
      <PageHeader icon={SettingsIcon} title="Settings" />
      <ComingSoon
        phase="phase 6"
        description="Account email, sign out, and session info once auth (GET /auth/me) is wired up."
      />
    </>
  );
}
