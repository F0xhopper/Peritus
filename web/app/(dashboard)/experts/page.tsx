import Link from "next/link";
import { UsersIcon, PlusIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ExpertsTable } from "@/components/experts/experts-table";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { MOCK_EXPERTS } from "@/lib/mock-data";

export default function ExpertsPage() {
  return (
    <>
      <PageHeader
        icon={UsersIcon}
        title="Experts"
        action={
          <Button size="sm" nativeButton={false} render={<Link href="/experts/new" />}>
            <PlusIcon />
            New expert
          </Button>
        }
      />
      <Card className="rounded-lg">
        <CardContent>
          <ExpertsTable experts={MOCK_EXPERTS} />
        </CardContent>
      </Card>
    </>
  );
}
