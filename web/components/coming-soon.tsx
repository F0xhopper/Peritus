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
        {/* The `[ phase 6 ]` bracket notation was the last of the terminal
            shell conventions; a labelled eyebrow says the same thing in the
            voice the rest of the app uses. */}
        <span className="text-eyebrow text-muted-foreground">{phase}</span>
        <p className="max-w-md text-sm text-muted-foreground">
          {description}
        </p>
      </CardContent>
    </Card>
  );
}
