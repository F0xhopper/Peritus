"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

// Shared by the sidebar account menu and the settings page — both need the
// same clear-cookies-then-redirect dance, so it lives once as a hook rather
// than being copy-pasted with its own busy/error handling twice.

export function useSignOut() {
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);

  const signOut = React.useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch("/api/auth/logout", { method: "POST" });
      if (!res.ok && res.status !== 204) {
        throw new Error("Could not sign out.");
      }
      router.replace("/login");
      router.refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not sign out.");
      setBusy(false);
    }
  }, [busy, router]);

  return { signOut, busy };
}
