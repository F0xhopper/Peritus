"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  MoreHorizontalIcon,
  PencilIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react";
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
import { Input } from "@/components/ui/input";

export function ConversationMenu({
  conversationId,
  title,
  expertSlug,
  onRenamed,
}: {
  conversationId: string;
  title: string | null;
  expertSlug: string;
  /** Lets the page update its heading immediately, before the refresh lands. */
  onRenamed?: (title: string) => void;
}) {
  const router = useRouter();
  const [renameOpen, setRenameOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [draft, setDraft] = React.useState(title ?? "");
  const [busy, setBusy] = React.useState(false);

  const rename = async () => {
    const next = draft.trim();
    if (!next || busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/conversations/${conversationId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: next }),
      });
      if (!res.ok) throw new Error((await res.json()).error ?? res.statusText);
      onRenamed?.(next);
      setRenameOpen(false);
      router.refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not rename the chat.");
    } finally {
      setBusy(false);
    }
  };

  // "Restart" starts a fresh thread with the same expert rather than emptying
  // this one. Nothing is destroyed: the transcript you were reading stays in
  // the recents list, which is what someone who restarts a chat by accident
  // needs. It is also the only shape the API supports — messages are
  // append-only, so there is no "clear this conversation" to call.
  const restart = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/experts/${expertSlug}/conversations`, {
        method: "POST",
      });
      if (!res.ok) throw new Error((await res.json()).error ?? res.statusText);
      const created = (await res.json()) as { id: string };
      // push, not replace: back should return to the conversation this was
      // started from, which is the whole reason it was left intact.
      router.push(`/chats/${created.id}`);
      router.refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Could not start a new chat.",
      );
      setBusy(false);
    }
  };

  const remove = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/conversations/${conversationId}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        throw new Error((await res.json()).error ?? res.statusText);
      }
      setDeleteOpen(false);
      // The conversation no longer exists, so land on the expert's chat page.
      // `refresh` drops it from the sidebar recents on the way.
      router.replace(`/experts/${expertSlug}/chat`);
      router.refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete the chat.");
      setBusy(false);
    }
  };

  return (
    <>
      {/* Promoted out of the menu: starting over is the one thing people reach
          for mid-conversation — when the thread has drifted, or the expert has
          latched onto a misreading of the first question — and hunting for it
          behind a "⋯" costs more than the pixel it saves. */}
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Restart — start a new chat with this expert"
        title="Restart chat"
        disabled={busy}
        onClick={restart}
      >
        <RotateCcwIcon />
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button variant="ghost" size="icon-sm" aria-label="Chat options" />
          }
        >
          <MoreHorizontalIcon />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={restart} disabled={busy}>
            <RotateCcwIcon />
            Restart chat
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              setDraft(title ?? "");
              setRenameOpen(true);
            }}
          >
            <PencilIcon />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onClick={() => setDeleteOpen(true)}>
            <Trash2Icon />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename chat</DialogTitle>
            <DialogDescription>
              Only affects how this chat is listed.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void rename();
              }
            }}
            maxLength={120}
            aria-label="Chat title"
            autoFocus
          />
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
            <Button onClick={rename} disabled={busy || !draft.trim()}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this chat?</DialogTitle>
            <DialogDescription>
              The whole transcript goes with it. This can&apos;t be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
            <Button variant="destructive" onClick={remove} disabled={busy}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
