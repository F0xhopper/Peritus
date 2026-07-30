"use client";

import { RotateCwIcon, TriangleAlertIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";

// Shared body for every error boundary, so a failure looks like part of the app
// rather than a stack trace. The audience is a researcher mid-audit: the useful
// information is whether to retry and what to quote if they report it, not the
// exception.
//
// `digest` is the only handle on the real cause — server-component errors reach
// the client as a generic message by design, and the digest is what matches the
// server log. Showing it is the difference between a bug report we can act on
// and "it broke".

export function ErrorState({
  title = "Something went wrong",
  description,
  digest,
  onRetry,
}: {
  title?: string;
  description: string;
  digest?: string;
  onRetry: () => void;
}) {
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <TriangleAlertIcon />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCwIcon />
          Try again
        </Button>
        {digest ? (
          <p className="mt-3 font-mono text-xs text-muted-foreground">
            Reference {digest}
          </p>
        ) : null}
      </EmptyContent>
    </Empty>
  );
}
