"use client";

import { useEffect, useRef, useState, KeyboardEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface ExpertSummary {
  slug: string;
  topic: string;
  status: string;
}

export default function ChatPage() {
  const params = useParams();
  const slug = params.slug as string;

  const [expert, setExpert] = useState<ExpertSummary | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`/api/experts/${slug}`)
      .then((r) => r.json())
      .then(setExpert)
      .catch(() => setError("Could not load expert."));
  }, [slug]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setError(null);

    const userMsg: Message = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setStreaming(true);

    // Append empty assistant message to stream into
    const assistantIdx = messages.length + 1; // index after user msg
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const res = await fetch(`/api/chat/${slug}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, use_graph: true }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if (!reader) throw new Error("No stream.");

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.replace(/^data: /, "");
            if (data === "[DONE]") break;
            if (data.startsWith("[ERROR]")) {
              setError(data.replace("[ERROR] ", ""));
              break;
            }
            buffer += data;
            setMessages((prev) => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: "assistant",
                content: buffer,
              };
              return updated;
            });
          }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setMessages((prev) => prev.slice(0, -1)); // remove empty assistant msg
    } finally {
      setStreaming(false);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  async function clearHistory() {
    await fetch(`/api/chat/${slug}/history`, { method: "DELETE" });
    setMessages([]);
    setError(null);
  }

  return (
    <main style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 8rem)" }}>
      {/* Header */}
      <div style={{ marginBottom: "1rem" }}>
        <p className="small muted">
          <Link href={`/experts/${slug}`}>← {expert?.topic || slug}</Link>
        </p>
        <div className="row" style={{ marginTop: "0.5rem", justifyContent: "space-between" }}>
          <h1 style={{ marginTop: 0, fontSize: "1.2rem" }}>
            {expert?.topic ? `${expert.topic} Expert` : slug}
          </h1>
          <button
            onClick={clearHistory}
            disabled={streaming || messages.length === 0}
            style={{ fontSize: "0.8rem" }}
          >
            Clear history
          </button>
        </div>
      </div>

      {error && <div className="error-box mb-2">{error}</div>}

      {/* Messages */}
      <div
        className="chat-messages"
        style={{ flex: 1, overflowY: "auto", paddingRight: "0.5rem" }}
      >
        {messages.length === 0 && !streaming && (
          <p className="muted small" style={{ padding: "1rem 0" }}>
            No messages yet. Ask your expert anything about{" "}
            <em>{expert?.topic || slug}</em>.
          </p>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`chat-message ${msg.role === "user" ? "user-message" : "assistant-message"}`}
          >
            {msg.role === "user" ? (
              <>
                <span className="msg-prefix">&gt; </span>
                <span className="msg-body">{msg.content}</span>
              </>
            ) : (
              <>
                <div>
                  <span className="msg-prefix">
                    {expert?.topic ? `${expert.topic} Expert` : "Expert"}:{" "}
                  </span>
                </div>
                <div className="prose" style={{ marginTop: "0.5rem" }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content || (streaming && i === messages.length - 1 ? "▋" : "")}
                  </ReactMarkdown>
                </div>
              </>
            )}
          </div>
        ))}

        {streaming && messages[messages.length - 1]?.role !== "assistant" && (
          <div className="chat-message assistant-message">
            <span className="msg-prefix">Expert: </span>
            <span className="msg-body muted">thinking...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="chat-input-row">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask your expert a question... (Enter to send)"
          disabled={streaming}
          autoFocus
        />
        <button
          onClick={sendMessage}
          disabled={streaming || !input.trim()}
          className="primary"
          style={{ whiteSpace: "nowrap" }}
        >
          {streaming ? "Thinking..." : "Send →"}
        </button>
      </div>
      <p className="small muted mt-1">
        Responses are grounded in the expert&apos;s knowledge graph &middot; Enter to send
      </p>
    </main>
  );
}
