pub mod app;
pub mod screens;
pub mod theme;
pub mod widgets;

use anyhow::Result;
use crossterm::{
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use std::io::stdout;

use crate::config::store::Config;
use app::{run_app, App};

pub async fn run(config: Config) -> Result<()> {
    enable_raw_mode()?;
    execute!(stdout(), EnterAlternateScreen)?;
    let mut terminal = ratatui::init();
    let mut app = App::new(config);
    let result = run_app(&mut terminal, &mut app).await;
    ratatui::restore();
    execute!(stdout(), LeaveAlternateScreen)?;
    disable_raw_mode()?;
    result
}
