"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  FileTextIcon,
  LinkIcon,
  Trash2Icon,
  UploadIcon,
  UserPenIcon,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import type { CorpusSource, UploadAccepted } from "@/lib/api/types";

// Add your own material to an expert. Discovery only finds what is publicly
// indexable, which for most subjects excludes the books that matter — so this
// is the panel that lets someone hand over the copy they already own.
//
// Ingestion is queued upstream and runs in a worker, so nothing here waits for
// it. The panel reports "queued", then refreshes the list; the build-events
// stream carries detailed progress for anyone watching that page.

const ACCEPT = ".pdf,.txt,.md,.markdown,text/plain,text/markdown,application/pdf";
const MAX_MB = 20;

type Props = {
  slug: string;
  /** Fetched on the server, so the list is in the first paint — no loading
   * flash and no client waterfall behind the page's own request.
   *
   * Held as a prop rather than mirrored into state on purpose: `router.refresh()`
   * re-runs the server component and hands down a fresh array, which is the
   * single update path. Copying it into state would need an effect to re-sync,
   * and that effect is both a cascading render and a second source of truth. */
  sources: CorpusSource[];
  /** A build rewrites the corpus underneath an ingest, so the API refuses
   * uploads while one is running. Disable the controls rather than letting the
   * user discover that from a 409. */
  buildInProgress?: boolean;
};

export function SourceManager({
  slug,
  sources,
  buildInProgress = false,
}: Props) {
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);
  const [url, setUrl] = React.useState("");
  const [dragging, setDragging] = React.useState(false);
  const fileInput = React.useRef<HTMLInputElement>(null);

  const accepted = (result: UploadAccepted) => {
    toast.success(`“${result.title}” queued`, {
      description: "It will appear once the worker has read and indexed it.",
    });
    // Re-renders the server component: the list and the source/chunk tiles
    // above it both come back current.
    router.refresh();
  };

  const failed = async (res: Response, fallback: string) => {
    const body = await res.json().catch(() => null);
    toast.error(body?.error ?? fallback);
  };

  async function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(true);
    try {
      for (const file of list) {
        if (file.size > MAX_MB * 1024 * 1024) {
          toast.error(`“${file.name}” is over ${MAX_MB} MB.`);
          continue;
        }
        const form = new FormData();
        form.append("file", file);
        form.append("title", file.name.replace(/\.[^.]+$/, ""));
        const res = await fetch(`/api/experts/${slug}/sources/upload`, {
          method: "POST",
          body: form,
        });
        if (!res.ok) {
          await failed(res, `Could not upload “${file.name}”.`);
          continue;
        }
        accepted(await res.json());
      }
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function addUrl(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/experts/${slug}/sources/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) return void (await failed(res, "Could not add that page."));
      setUrl("");
      accepted(await res.json());
    } finally {
      setBusy(false);
    }
  }

  async function remove(source: CorpusSource) {
    const res = await fetch(`/api/experts/${slug}/sources/${source.id}`, {
      method: "DELETE",
    });
    if (!res.ok) return void (await failed(res, "Could not remove that source."));
    toast.success(`Removed “${source.title}”`);
    router.refresh();
  }

  const disabled = busy || buildInProgress;
  const uploads = sources.filter((s) => s.discovered_via === "upload");
  const found = sources.filter((s) => s.discovered_via !== "upload");

  return (
    <Card className="rounded-lg">
      <CardHeader>
        <CardTitle className="text-sm text-muted-foreground">
          Your sources
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">
          Add a book, paper, or page this expert should know. Anything you add
          here is trusted — it is never quality-filtered, and it survives a
          rebuild.
        </p>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            if (!disabled) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (!disabled) void uploadFiles(e.dataTransfer.files);
          }}
          className={[
            "flex flex-col items-center gap-2 rounded-lg border border-dashed p-6 text-center transition-colors",
            dragging ? "border-primary bg-primary/5" : "border-border",
            disabled ? "opacity-60" : "",
          ].join(" ")}
        >
          <UploadIcon className="size-5 text-muted-foreground" />
          <p className="text-sm">
            Drop a PDF, .txt or .md file here, or{" "}
            <button
              type="button"
              className="underline underline-offset-2 disabled:no-underline"
              disabled={disabled}
              onClick={() => fileInput.current?.click()}
            >
              choose a file
            </button>
            .
          </p>
          <p className="text-xs text-muted-foreground">Up to {MAX_MB} MB each.</p>
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            multiple
            hidden
            onChange={(e) => e.target.files && void uploadFiles(e.target.files)}
          />
        </div>

        <form onSubmit={addUrl} className="flex gap-2">
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://… — add a web page"
            disabled={disabled}
            aria-label="Web page URL"
          />
          <Button type="submit" variant="secondary" disabled={disabled || !url.trim()}>
            {busy ? <Spinner /> : <LinkIcon />}
            Add
          </Button>
        </form>

        {buildInProgress && (
          <p className="text-xs text-muted-foreground">
            This expert is building. You can add sources once it finishes.
          </p>
        )}

        <div className="flex flex-col gap-4">
          <SourceList
            title="Added by you"
            empty="Nothing yet."
            sources={uploads}
            onRemove={remove}
            highlight
          />
          <SourceList
            title={`Found by research (${found.length})`}
            empty="No sources yet."
            sources={found}
            onRemove={remove}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function SourceList({
  title,
  empty,
  sources,
  onRemove,
  highlight = false,
}: {
  title: string;
  empty: string;
  sources: CorpusSource[];
  onRemove: (s: CorpusSource) => void;
  highlight?: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-eyebrow text-muted-foreground">{title}</p>
      {sources.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {sources.map((s) => (
            <li
              key={s.id}
              className="group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted/50"
            >
              {highlight ? (
                <UserPenIcon className="size-4 shrink-0 text-primary" />
              ) : (
                <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
              )}
              <span className="min-w-0 flex-1 truncate" title={s.title}>
                {s.url ? (
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:underline"
                  >
                    {s.title}
                  </a>
                ) : (
                  s.title
                )}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {s.chunk_count} chunks
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${s.title}`}
                className="size-7 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                onClick={() => onRemove(s)}
              >
                <Trash2Icon className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
