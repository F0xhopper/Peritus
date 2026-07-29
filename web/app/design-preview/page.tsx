import { BookOpenIcon, NetworkIcon, QuoteIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Wordmark } from "@/components/brand/wordmark";
import { StatTile } from "@/components/experts/stat-tile";
import { StatusBadge } from "@/components/experts/status-badge";
import { TierBadge } from "@/components/experts/tier-badge";
import type { ExpertStatus, ExpertTier } from "@/lib/api/types";

// A specimen sheet, not a route the product links to. It exists so the type
// scale, the two faces and the monochrome ramp can be judged side by side —
// which is the only way to catch a face that has drifted or a step in the ramp
// that has stopped being distinguishable.

export const metadata = { title: "Design preview — Peritus" };

const STATUSES: ExpertStatus[] = ["queued", "building", "ready", "failed"];
const TIERS: ExpertTier[] = ["lite", "standard", "pro"];

const RAMP = [
  { name: "background", value: "#0a0a0a" },
  { name: "card", value: "#121212" },
  { name: "muted", value: "#1a1a1a" },
  { name: "chart-5", value: "#343434" },
  { name: "chart-4", value: "#4d4d4d" },
  { name: "chart-3", value: "#6f6f6f" },
  { name: "muted-foreground", value: "#9b9b9b" },
  { name: "chart-1", value: "#e0e0e0" },
  { name: "foreground", value: "#ededed" },
];

export default function DesignPreviewPage() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-16 px-6 py-16">
      <header className="flex flex-col gap-6">
        <Wordmark />
        <h1 className="font-display text-3xl font-semibold tracking-[0.04em]">
          Specimen
        </h1>
        <p className="max-w-measure text-[1.0625rem] leading-[1.7] text-muted-foreground">
          Two faces carry the whole interface. Literata sets everything that is
          read as language — body copy and anything that labels or names a
          thing; JetBrains Mono is left with the identifiers, counts and code it
          was always best at. Nothing else is permitted a typeface.
        </p>
      </header>

      <Section title="Faces">
        <Specimen
          label="Serif — Literata"
          note="Body, headings, titles, labels, quoted extracts. Proportional figures 1234567890."
          className="font-serif text-lg"
        />
        <Specimen
          label="Mono — JetBrains Mono"
          note="Slugs, counts, code, citations. Tabular figures 1234567890."
          className="font-mono text-base"
        />
      </Section>

      <Section title="Scale">
        <div className="flex flex-col gap-4">
          <p className="text-eyebrow text-muted-foreground">
            Eyebrow · running head · label
          </p>
          <h2 className="font-display text-2xl font-semibold tracking-[0.05em]">
            Chapter head
          </h2>
          <h3 className="font-display text-base font-semibold tracking-wide">
            Section head
          </h3>
          <h4 className="font-serif text-[0.9375rem] font-semibold italic">
            Minor head, run into the text
          </h4>
          <p className="max-w-measure text-[0.9375rem] leading-[1.7]">
            Body copy set at the reading size the chat surface uses, capped at
            the same measure. A line this long is about seventy characters,
            which is where a serif stops tiring the eye and a reader stops
            losing the return sweep.
          </p>
          <blockquote className="max-w-measure border-l border-border pl-4 text-[0.9375rem] leading-[1.7] italic text-muted-foreground">
            Quoted source material is set as an extract — italic, indented, and
            marked with a hairline rather than a heavy bar.
          </blockquote>
          <p className="font-mono text-sm text-muted-foreground">
            stoic-philosophy · 1,284 chunks · 96 sources
          </p>
        </div>
      </Section>

      <Section title="Marks">
        <div className="flex flex-wrap items-center gap-2">
          {STATUSES.map((status) => (
            <StatusBadge key={status} status={status} />
          ))}
          {TIERS.map((tier) => (
            <TierBadge key={tier} tier={tier} />
          ))}
          <Badge variant="outline" className="font-serif">
            virtue ethics
          </Badge>
          <Badge variant="secondary" className="font-serif">
            determinism
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button>Get started</Button>
          <Button variant="outline">How it works</Button>
          <Button variant="secondary">Details</Button>
          <Button variant="ghost">Cancel</Button>
          <Button size="sm">Small</Button>
        </div>
      </Section>

      <Section title="Plates">
        <div className="grid gap-4 sm:grid-cols-3">
          <StatTile icon={NetworkIcon} label="Sources" value="96" />
          <StatTile icon={QuoteIcon} label="Chunks" value="1,284" />
          <StatTile icon={BookOpenIcon} label="Concepts" value="42" />
        </div>
        <Card className="rounded-lg">
          <CardHeader>
            <CardTitle>Stoic Philosophy</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed text-muted-foreground">
              One face, two voices. The running head above, the eyebrow
              labels, and this card’s section title all name things and are
              styled apart from prose by weight and tracking, not typeface —
              everything, named or read, sets in Literata.
            </p>
          </CardContent>
        </Card>
      </Section>

      <Section title="Ramp">
        <p className="max-w-measure text-sm text-muted-foreground">
          A true neutral grayscale — no hue at all, at any step. Nothing here
          is allowed to carry meaning by colour, so every distinction the
          interface makes has to survive in lightness or in shape.
        </p>
        <div className="flex flex-wrap gap-3">
          {RAMP.map((step) => (
            <div key={step.name} className="flex flex-col gap-1.5">
              <div
                className="size-16 border border-border"
                style={{ backgroundColor: step.value }}
              />
              <span className="font-mono text-[0.6875rem] text-muted-foreground">
                {step.name}
              </span>
            </div>
          ))}
        </div>
      </Section>
    </main>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h2 className="text-eyebrow text-muted-foreground">{title}</h2>
        <div aria-hidden className="h-px w-full bg-border" />
      </div>
      {children}
    </section>
  );
}

function Specimen({
  label,
  note,
  className,
}: {
  label: string;
  note: string;
  className: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-eyebrow text-muted-foreground">{label}</p>
      <p className={className}>
        Whereof one cannot speak, thereof one must be silent.
      </p>
      <p className="text-sm text-muted-foreground">{note}</p>
    </div>
  );
}
