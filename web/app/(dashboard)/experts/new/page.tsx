import { PlusIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { NewExpertForm } from "@/components/experts/new-expert-form";

export const metadata = { title: "New expert — Peritus" };

export default function NewExpertPage() {
  return (
    <>
      <PageHeader icon={PlusIcon} title="New expert" />
      <NewExpertForm />
    </>
  );
}
