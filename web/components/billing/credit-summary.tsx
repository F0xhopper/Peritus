import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { CreditState } from "@/lib/api/types";

// Credits gate builds; chat never touches them. `held` is shown separately
// because a balance that silently drops during a build reads as a bug.

export function CreditSummary({ state }: { state: CreditState }) {
  if (!state.credits_enforced) {
    // Deployments with gating off should not advertise an "unlimited" balance
    // that means nothing — say what is actually true.
    return (
      <Card className="rounded-lg">
        <CardContent className="py-6 text-sm text-muted-foreground">
          Build credits are not enforced on this deployment.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="rounded-lg">
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle className="text-sm text-muted-foreground">
          Build credits
        </CardTitle>
        <Badge variant="outline" className="font-normal">
          {state.plan.display_name}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3">
          <div className="flex flex-col">
            <span className="text-eyebrow text-muted-foreground">Available</span>
            <span className="font-display text-2xl tabular-nums lining-nums">
              {state.balance}
            </span>
          </div>
          {state.held > 0 ? (
            <div className="flex flex-col">
              <span className="text-eyebrow text-muted-foreground">
                Held by a running build
              </span>
              <span className="font-display text-2xl tabular-nums lining-nums text-muted-foreground">
                {state.held}
              </span>
            </div>
          ) : null}
          <div className="flex flex-col">
            <span className="text-eyebrow text-muted-foreground">Used</span>
            <span className="font-display text-2xl tabular-nums lining-nums text-muted-foreground">
              {state.consumed}
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-eyebrow text-muted-foreground">
            What a build costs
          </span>
          <ul className="flex flex-col divide-y divide-border text-sm">
            {state.tiers.map((t) => (
              <li
                key={t.tier}
                className="flex items-center justify-between gap-4 py-2 first:pt-0 last:pb-0"
              >
                <span
                  className={
                    t.included_in_plan ? "" : "text-muted-foreground italic"
                  }
                >
                  {t.tier}
                  {!t.included_in_plan ? " — not on your plan" : ""}
                </span>
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                  {t.credit_cost} credit{t.credit_cost === 1 ? "" : "s"}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-pretty text-muted-foreground">
          Questioning an expert is free and never uses credits. Credits are spent
          only when you build one.
        </p>
      </CardContent>
    </Card>
  );
}
