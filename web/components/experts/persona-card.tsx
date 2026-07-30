import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// The bio, and nothing else.
//
// The expert's `style` field — its system prompt, hundreds of words of
// second-person instruction ("You open every hard idea with a fork in the
// road…") — used to render here as a collapsible "Voice" block. It came out at
// the user's request: it is generated configuration rather than something a
// reader of this page came for, and even clamped it pushed the concepts down the
// page. It is still stored on the expert and still what the expert answers
// under; it just isn't surfaced here.
//
// The bio is held to the book measure rather than the full page width — the card
// is as wide as the window, and a 1000px line of prose is unreadable at any size.

export function PersonaCard({
  name,
  bio,
}: {
  name: string | null;
  bio: string | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm text-muted-foreground">Persona</CardTitle>
      </CardHeader>
      <CardContent>
        {name ? (
          <Field label="Bio">
            <p className="max-w-measure text-sm text-pretty text-muted-foreground">
              {bio}
            </p>
          </Field>
        ) : (
          <p className="text-sm text-muted-foreground">
            Persona not generated yet — available once the build reaches
            &quot;ready&quot;.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-eyebrow text-muted-foreground">{label}</p>
      {children}
    </div>
  );
}
