import { SettingsIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ComingSoon } from "@/components/coming-soon";
import { CreditSummary } from "@/components/billing/credit-summary";
import { getCreditState, getCreditLedger } from "@/lib/api/data";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default async function SettingsPage() {
  const [state, ledger] = await Promise.all([
    getCreditState(),
    getCreditLedger(),
  ]);

  return (
    <>
      <PageHeader icon={SettingsIcon} title="Settings" />

      <CreditSummary state={state} />

      {ledger.length > 0 ? (
        <Card className="rounded-lg">
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              Credit history
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col divide-y divide-border text-sm">
              {ledger.map((e) => (
                <li
                  key={e.id}
                  className="flex items-center justify-between gap-4 py-2 first:pt-0 last:pb-0"
                >
                  <div className="flex min-w-0 flex-col">
                    <span>
                      {e.entry_type}
                      {e.tier ? ` · ${e.tier}` : ""}
                    </span>
                    {e.reason ? (
                      <span className="text-xs text-muted-foreground">
                        {e.reason}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-4">
                    {/* What the build actually cost to run — the metered
                        figure, not an estimate. */}
                    {e.cost_usd != null ? (
                      <span className="text-xs tabular-nums text-muted-foreground">
                        ${e.cost_usd.toFixed(2)}
                      </span>
                    ) : null}
                    <span
                      className={`tabular-nums ${
                        e.delta < 0 ? "text-muted-foreground" : "text-foreground"
                      }`}
                    >
                      {e.delta > 0 ? `+${e.delta}` : e.delta}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <ComingSoon
        phase="phase 6"
        description="Account email, sign out, and session info once auth (GET /auth/me) is wired up."
      />
    </>
  );
}
