"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { MoreHorizontalIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

// Per-expert management, mirroring ConversationMenu. Delete is the only entry
// today; the menu (rather than a bare trash icon on every card) is what makes
// room for rename/rebuild later, and keeps a destructive action off the card's
// surface where it would sit a few pixels from the link that opens the chat.

export function ExpertMenu({
  slug,
  topic,
  /** Where to go after deleting. Cards refresh in place; the detail and chat
   * pages are about to stop existing, so they hand over a destination. */
  redirectTo,
}: {
  slug: string;
  topic: string;
  redirectTo?: string;
}) {
  const router = useRouter();
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const remove = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/experts/${encodeURIComponent(slug)}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        throw new Error((await res.json()).error ?? res.statusText);
      }
      setDeleteOpen(false);
      if (redirectTo) router.replace(redirectTo);
      // Re-renders the server components that list experts — the grid, and the
      // sidebar's recents, which may name chats that just cascaded away.
      router.refresh();
      toast.success(`Deleted ${topic}.`);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Could not delete the expert.",
      );
      setBusy(false);
    }
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              // Named per expert: six cards otherwise expose six controls all
              // called "Expert options".
              aria-label={`Options for ${topic}`}
            />
          }
        >
          <MoreHorizontalIcon />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            variant="destructive"
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2Icon />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {topic}?</DialogTitle>
            <DialogDescription>
              The sources, chunks and knowledge graph go with it, along with
              every chat you&apos;ve had with this expert. Rebuilding takes a
              few minutes. This can&apos;t be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              Cancel
            </DialogClose>
            <Button variant="destructive" onClick={remove} disabled={busy}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
