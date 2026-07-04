import { Card, CardContent } from "@/components/ui/card";

export function ComingSoon({
  phase,
  description,
}: {
  phase: string;
  description: string;
}) {
  return (
    <Card className="rounded-lg">
      <CardContent className="flex flex-col items-start gap-2 py-10">
        <span className="text-xs text-muted-foreground">[ {phase} ]</span>
        <p className="max-w-md text-sm text-muted-foreground">
          {description}
        </p>
      </CardContent>
    </Card>
  );
}
