"use client";

import { LogOutIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSignOut } from "@/components/auth/use-sign-out";
import type { User } from "@/lib/api/types";

export function AccountCard({ user }: { user: User }) {
  const { signOut, busy } = useSignOut();

  return (
    <Card className="rounded-lg">
      <CardHeader>
        <CardTitle className="text-sm text-muted-foreground">Account</CardTitle>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <span className="truncate text-sm">
            {user.email ?? "No email on file"}
          </span>
          {user.is_admin ? (
            <Badge variant="secondary" className="w-fit">
              Admin
            </Badge>
          ) : null}
        </div>
        <Button
          variant="outline"
          onClick={() => void signOut()}
          disabled={busy}
        >
          <LogOutIcon />
          Sign out
        </Button>
      </CardContent>
    </Card>
  );
}
