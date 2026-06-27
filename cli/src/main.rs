mod api;
mod config;
mod events;
mod tui;

use anyhow::Result;
use tracing_appender::rolling;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<()> {
    // Log to file only — never stdout (ratatui owns the terminal)
    let log_dir = dirs::data_local_dir()
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("peritus");
    std::fs::create_dir_all(&log_dir)?;
    let file_appender = rolling::never(&log_dir, "peritus.log");
    let (non_blocking, _guard) = tracing_appender::non_blocking(file_appender);
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::new("info"))
        .with_writer(non_blocking)
        .init();

    let cfg = config::store::Config::load();
    tui::run(cfg).await
}
