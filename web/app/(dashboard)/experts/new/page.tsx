import { PlusIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { NewExpertForm } from "@/components/experts/new-expert-form";
import { getCreditState, safely } from "@/lib/api/data";

export const metadata = { title: "New expert — Peritus" };

export default async function NewExpertPage() {
  // What a build costs and which depths this plan allows. Fetched here rather
  // than in the form so the first paint already knows — a depth picker that
  // renders every option as available and only reveals the truth in the error
  // body after submit is a trap, and it was catching the default: the form
  // opened on Standard, which the Free plan does not include.
  //
  // Degrades to null rather than failing the page: without it the form falls
  // back to showing all three depths unannotated, which is where it started.
  const credits = await safely(() => getCreditState(), null);

  return (
    <>
      <PageHeader icon={PlusIcon} title="New expert" />
      <NewExpertForm credits={credits} />
    </>
  );
}
