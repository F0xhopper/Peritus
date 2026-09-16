# Peritus TUI

A terminal client for the Peritus API, built with [ratatui](https://ratatui.rs). Sign in, build an
expert and watch the pipeline run live, then chat with it — entirely in the terminal, no browser.

For the system this is a client of, start at [`../docs/README.md`](../docs/README.md).

## Build and run

```bash
cargo build --release      # target/release/peritus
cargo run                  # or `just run-cli` from the repository root
```

Pre-built binaries are attached to
[releases](https://github.com/F0xhopper/Peritus/releases).

On first run the TUI shows a configuration screen: point it at a server (default
`http://localhost:8000`). If that server has auth enabled, a sign-in screen follows — enter your
email, then the six-digit code it sends you. The session is written to the client config with
`0600` permissions and refreshed automatically. Press `L` on the home screen to sign out, which
revokes the session server-side.

From the home screen: create an expert (topic plus tier) and watch the build log stream, or open a
ready expert and chat.

## Layout

```
src/
  main.rs          Entry point and the event loop
  events.rs        Terminal and async event plumbing
  api/
    client.rs      HTTP calls against the Peritus API
    sse.rs         Server-sent event parsing for build and chat streams
    types.rs       Wire types mirroring the API's schemas
  config/
    store.rs       On-disk config: server URL and the saved session
  tui/
    app.rs         Application state machine
    screens/       home · build · chat · config · login
    widgets/       expert card · log panel · stage bar · chat history ·
                   source list · avatar · input box · spinner
    markdown.rs    Markdown rendering for answers
    theme.rs       Colours and styles
```

## Two things to know

- **A closed SSE stream is not a finished build.** Only `done`, `error` or `cancelled` ends a
  build tail. Anything else means reconnect with `after=<lastSeq>`; the server replays from that
  cursor. Closing the TUI mid-build does not affect the build — it runs in a durable queue on the
  server.
- **Wire types are hand-written.** There is no codegen between the Python schemas and
  `api/types.rs`, so a schema change on the server needs a matching change here.

CI runs `cargo check --locked` on every pull request.
