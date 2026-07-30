"use client";

import { useEffect } from "react";
import { ErrorState } from "@/components/error-state";

// Catches throws from any dashboard page. Every one of them is an async server
// component reading the FastAPI backend, so "the API is down, slow, or returned
// something unexpected" is a routine outcome, not an exotic one — without this
// boundary each of those renders Next's default error screen.
//
// The sidebar shell survives, because error.tsx replaces the page beneath the
// layout rather than the layout itself.

export default function DashboardError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error("Dashboard route error:", error);
  }, [error]);

  return (
    <ErrorState
      description="This page could not be loaded. The Peritus API may be unreachable — your experts and corpora are unaffected."
      digest={error.digest}
      onRetry={unstable_retry}
    />
  );
}
