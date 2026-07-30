"use client";

// Last resort: catches failures in the root layout itself, which no error.tsx
// can reach. It replaces the root layout when active, so it has to bring its own
// <html> and <body> — and it cannot rely on the fonts or providers that layout
// normally installs, which is why this is styled with plain inline rules rather
// than the design tokens used everywhere else.

export default function GlobalError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          margin: 0,
          padding: "2rem",
          background: "#0a0a0a",
          color: "#fafafa",
          fontFamily: "ui-serif, Georgia, serif",
          textAlign: "center",
        }}
      >
        <title>Peritus — something went wrong</title>
        <div style={{ maxWidth: "32rem" }}>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 600, margin: "0 0 0.75rem" }}>
            Peritus could not start
          </h1>
          <p style={{ margin: "0 0 1.5rem", color: "#a1a1aa", lineHeight: 1.6 }}>
            Something failed while loading the application shell. Nothing in your
            account has been changed.
          </p>
          <button
            onClick={() => unstable_retry()}
            style={{
              padding: "0.5rem 1rem",
              borderRadius: "0.5rem",
              border: "1px solid #3f3f46",
              background: "transparent",
              color: "inherit",
              font: "inherit",
              cursor: "pointer",
            }}
          >
            Try again
          </button>
          {error.digest ? (
            <p
              style={{
                marginTop: "1.5rem",
                fontFamily: "ui-monospace, monospace",
                fontSize: "0.75rem",
                color: "#71717a",
              }}
            >
              Reference {error.digest}
            </p>
          ) : null}
        </div>
      </body>
    </html>
  );
}
