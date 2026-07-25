"use client";

import * as React from "react";
import { ArrowUpIcon, SquareIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

const MAX_QUESTION_CHARS = 4000; // matches SendMessageRequest in the API

export function Composer({
  onSend,
  onStop,
  streaming,
  disabled,
  placeholder = "Ask the expert…",
  autoFocus,
}: {
  onSend: (question: string) => void;
  onStop?: () => void;
  streaming: boolean;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [value, setValue] = React.useState("");
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  // Return focus to the composer once an answer settles, so a follow-up
  // question can be typed without reaching for the mouse.
  const wasStreaming = React.useRef(streaming);
  React.useEffect(() => {
    if (wasStreaming.current && !streaming) textareaRef.current?.focus();
    wasStreaming.current = streaming;
  }, [streaming]);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || streaming || disabled) return;
    setValue("");
    onSend(trimmed);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift+Enter breaks the line. IME composition must not send
    // — during composition Enter is confirming a candidate, not submitting.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const overLimit = value.length > MAX_QUESTION_CHARS;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        className="relative flex items-end gap-2 rounded-lg border border-input bg-background p-2 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50"
      >
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus={autoFocus}
          rows={1}
          aria-label="Message"
          // field-sizing-content on the base Textarea grows it with the text;
          // the max-height keeps a long draft from eating the transcript.
          className="max-h-48 min-h-8 resize-none border-0 bg-transparent px-1 py-1 focus-visible:border-0 focus-visible:ring-0 disabled:bg-transparent dark:bg-transparent"
        />
        {streaming ? (
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            onClick={onStop}
            aria-label="Stop generating"
          >
            <SquareIcon />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon-sm"
            disabled={disabled || !value.trim() || overLimit}
            aria-label="Send message"
          >
            <ArrowUpIcon />
          </Button>
        )}
      </form>
      <div className="flex justify-between px-1 pt-1">
        <p className="text-[0.7rem] text-muted-foreground">
          <kbd className="font-mono">Enter</kbd> to send,{" "}
          <kbd className="font-mono">Shift+Enter</kbd> for a new line
        </p>
        {overLimit && (
          <p className="text-[0.7rem] text-destructive">
            {value.length.toLocaleString()} / {MAX_QUESTION_CHARS.toLocaleString()}
          </p>
        )}
      </div>
    </div>
  );
}
