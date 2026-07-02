use std::sync::Arc;
use anyhow::Result;
use crossterm::event::{self, Event, KeyEventKind};
use ratatui::DefaultTerminal;
use tokio::sync::oneshot;

use crate::api::client::ApiClient;
use crate::api::types::ExpertSummary;
use crate::config::store::Config;
use crate::events::{key_to_action, AppAction};
use crate::tui::screens::{
    build::BuildScreen, chat::ChatScreen, config::ConfigScreen, home::HomeScreen,
};

#[derive(Debug, Clone, PartialEq)]
pub enum Screen {
    Home,
    Build,
    Chat,
    Config,
}

/// Result of a background expert-list refresh (optionally preceded by a delete).
type RefreshResult = Result<Vec<ExpertSummary>, String>;

pub struct App {
    pub screen: Screen,
    pub api: Arc<ApiClient>,
    pub config: Config,
    pub experts: Vec<ExpertSummary>,
    pub home: HomeScreen,
    pub build: Option<BuildScreen>,
    pub chat: Option<ChatScreen>,
    pub config_screen: ConfigScreen,
    pub should_quit: bool,
    pub show_help: bool,
    pub status_msg: Option<(String, std::time::Instant)>,
    pub tick: u64, // increments every render frame (~60fps)
    last_expert_poll: std::time::Instant,
    // In-flight background refresh; API calls never block the render loop.
    refresh_rx: Option<oneshot::Receiver<RefreshResult>>,
    // Topic to select once the next refresh lands (e.g. after a build finishes).
    pending_select_topic: Option<String>,
}

impl App {
    pub fn new(config: Config) -> Self {
        let api = Arc::new(ApiClient::new(config.server_url.clone(), config.api_key.clone()));
        Self {
            screen: if config.is_configured() { Screen::Home } else { Screen::Config },
            api: api.clone(),
            config: config.clone(),
            experts: vec![],
            home: HomeScreen::new(),
            build: None,
            chat: None,
            config_screen: ConfigScreen::new(config),
            should_quit: false,
            show_help: false,
            status_msg: None,
            tick: 0,
            last_expert_poll: std::time::Instant::now(),
            refresh_rx: None,
            pending_select_topic: None,
        }
    }

    pub fn set_status(&mut self, msg: impl Into<String>) {
        self.status_msg = Some((msg.into(), std::time::Instant::now()));
    }

    /// Kick off a non-blocking expert-list refresh; the result lands in
    /// `tick_screens` so the UI keeps rendering while the request is in flight.
    fn request_refresh(&mut self) {
        let api = self.api.clone();
        let (tx, rx) = oneshot::channel();
        self.refresh_rx = Some(rx);
        tokio::spawn(async move {
            let _ = tx.send(api.list_experts().await.map_err(|e| e.to_string()));
        });
    }

    /// Delete an expert in the background, then refresh the list.
    fn request_delete(&mut self, slug: String) {
        let api = self.api.clone();
        let (tx, rx) = oneshot::channel();
        self.refresh_rx = Some(rx);
        self.set_status("Deleting…");
        tokio::spawn(async move {
            let result = match api.delete_expert(&slug).await {
                Ok(()) => api.list_experts().await.map_err(|e| e.to_string()),
                Err(e) => Err(format!("Delete failed: {}", e)),
            };
            let _ = tx.send(result);
        });
    }

    /// Open the build screen for `expert`: reuse the live screen if it's the same
    /// build, otherwise attach to the server-side build (survives TUI restarts).
    fn open_build_for(&mut self, topic: String, tier: String) {
        let same = self.build.as_ref().map(|b| b.topic() == topic).unwrap_or(false);
        if !same {
            if self.build.is_some() {
                self.set_status("Another build is on screen — it keeps running server-side");
            }
            self.build = Some(BuildScreen::attach(topic, tier, self.api.clone()));
        }
        self.screen = Screen::Build;
    }

    fn start_build(&mut self, topic: String, tier: String) {
        if self.build.is_some() {
            self.set_status("A build is already running — press [b] to watch it");
            return;
        }
        self.build = Some(BuildScreen::new(topic, tier, self.api.clone()));
        self.screen = Screen::Build;
    }
}

pub async fn run_app(terminal: &mut DefaultTerminal, app: &mut App) -> Result<()> {
    // Paint a frame before the first (blocking) request so an unreachable backend
    // shows "connecting", not an indefinite blank screen.
    terminal.draw(|f| {
        use ratatui::widgets::Paragraph;
        use crate::tui::theme::Theme;
        f.render_widget(
            Paragraph::new("  Connecting to Peritus server…").style(Theme::dim()),
            f.area(),
        );
    })?;

    match app.api.list_experts().await {
        Ok(experts) => {
            app.experts = experts.clone();
            app.home.update_experts(experts);
        }
        Err(e) => app.set_status(format!(
            "Cannot reach server at {} — press [c] to change settings ({})",
            app.config.server_url, e
        )),
    }

    loop {
        let tick = app.tick;
        terminal.draw(|f| {
            match app.screen {
                Screen::Home   => {
                    let build_info = app.build.as_ref().map(|b| b.card_info());
                    app.home.render(f, f.area(), tick, build_info.as_ref());
                }
                Screen::Build  => {
                    if let Some(build) = &mut app.build { build.render(f, f.area(), tick); }
                }
                Screen::Chat   => {
                    if let Some(chat) = &mut app.chat { chat.render(f, f.area(), tick); }
                }
                Screen::Config => app.config_screen.render(f, f.area()),
            }

            // Status toast
            if let Some((msg, when)) = &app.status_msg {
                if when.elapsed().as_secs() < 3 {
                    use ratatui::{layout::Rect, widgets::Paragraph};
                    use crate::tui::theme::Theme;
                    let area = f.area();
                    let w = (msg.len() as u16 + 4).min(area.width);
                    let toast = Rect::new(
                        area.width.saturating_sub(w),
                        area.height.saturating_sub(2),
                        w, 1,
                    );
                    f.render_widget(
                        Paragraph::new(format!(" {} ", msg)).style(Theme::warning()),
                        toast,
                    );
                }
            }

            if app.show_help {
                render_help_overlay(f);
            }
        })?;

        app.tick = app.tick.wrapping_add(1);

        if let Some((_, when)) = &app.status_msg {
            if when.elapsed().as_secs() >= 3 { app.status_msg = None; }
        }

        if app.should_quit { break; }

        // Poll at 16ms (~60fps) — gives the spinner animation a smooth cadence.
        if event::poll(std::time::Duration::from_millis(16))? {
            if let Event::Key(key) = event::read()? {
                if key.kind != KeyEventKind::Press { continue; }

                // Chat owns its own key mapping so that j/k/q/n/d reach the input buffer.
                if app.screen == Screen::Chat {
                    if let Some(chat) = &mut app.chat {
                        match chat.handle_raw(key).await {
                            // Return Home but KEEP the conversation so re-entering the
                            // same expert resumes it instead of starting over.
                            crate::tui::screens::chat::ChatExit::Back => app.screen = Screen::Home,
                            crate::tui::screens::chat::ChatExit::Quit => app.should_quit = true,
                            crate::tui::screens::chat::ChatExit::Stay => {}
                        }
                    }
                } else {
                    let in_text_input = match app.screen {
                        Screen::Home   => app.home.input_active && !app.home.tier_select_active,
                        Screen::Config => app.config_screen.editing,
                        _              => false,
                    };
                    if let Some(action) = key_to_action(key, in_text_input) {
                        handle_action(app, action).await;
                    }
                }
            }
        }

        tick_screens(app).await;
    }

    Ok(())
}

async fn handle_action(app: &mut App, action: AppAction) {
    // Help overlay swallows the next key to dismiss; `?` opens it from any screen.
    if app.show_help {
        app.show_help = false;
        return;
    }
    if let AppAction::Help = action {
        app.show_help = true;
        return;
    }

    match app.screen {
        Screen::Config => {
            // Ctrl+C (and q outside editing) quits from here too.
            if let AppAction::Quit = action {
                app.should_quit = true;
                return;
            }
            // Esc leaves config when there's nothing to cancel and setup is done.
            if let AppAction::Back = action {
                if !app.config_screen.editing && app.config.is_configured() {
                    app.screen = Screen::Home;
                    return;
                }
            }
            app.config_screen.handle(action.clone());
            if app.config_screen.saved {
                app.config = app.config_screen.config.clone();
                let _ = app.config.save();
                app.api = Arc::new(ApiClient::new(
                    app.config.server_url.clone(),
                    app.config.api_key.clone(),
                ));
                app.screen = Screen::Home;
                app.config_screen.saved = false;
                app.request_refresh();
            }
        }

        Screen::Home => {
            // Confirm-delete intercepts D/Esc before normal navigation.
            if app.home.confirm_delete {
                match action {
                    // Capital D (Shift+d) confirms; lowercase d also works for ergonomics.
                    AppAction::DeleteExpert | AppAction::Char('D') | AppAction::Char('d') => {
                        app.home.confirm_delete = false;
                        if let Some(expert) = app.home.selected_expert() {
                            let slug = expert.name.clone();
                            // Deleting the expert whose build is on screen? Drop the screen.
                            if app.build.as_ref().map(|b| b.topic() == expert.topic).unwrap_or(false) {
                                if let Some(b) = &app.build { b.cancel(); }
                                app.build = None;
                            }
                            app.request_delete(slug);
                        }
                    }
                    AppAction::Back | AppAction::Quit => { app.home.confirm_delete = false; }
                    _ => {}
                }
                return;
            }

            // Tier picker intercepts navigation before normal home handling.
            if app.home.tier_select_active {
                match action {
                    AppAction::Left  => { app.home.tier_prev(); }
                    AppAction::Right => { app.home.tier_next(); }
                    AppAction::Submit => { app.home.tier_confirm(); }
                    AppAction::Back  => { app.home.tier_cancel(); }
                    _ => {}
                }
                if let Some((topic, tier)) = app.home.take_submitted_build() {
                    app.start_build(topic, tier);
                }
                return;
            }

            // While the topic input is focused, every key is either submit/cancel
            // or an edit routed to the shared TextInput.
            if app.home.input_active {
                match action {
                    AppAction::Quit => app.should_quit = true, // Ctrl+C
                    AppAction::Submit => app.home.handle_enter(),
                    AppAction::Back => app.home.cancel_input(),
                    other => app.home.input_edit(&other),
                }
                if let Some((topic, tier)) = app.home.take_submitted_build() {
                    app.start_build(topic, tier);
                }
                return;
            }

            match action {
                AppAction::Quit => app.should_quit = true,
                AppAction::Up | AppAction::Left  => app.home.prev(),
                AppAction::Down | AppAction::Right => app.home.next(),
                AppAction::Submit => {
                    if let Some(expert) = app.home.selected_expert().cloned() {
                        match expert.status.as_str() {
                            "ready" => {
                                let resume = app.chat.as_ref()
                                    .map(|c| c.expert_slug() == expert.name)
                                    .unwrap_or(false);
                                if !resume {
                                    app.chat = Some(ChatScreen::new(expert.clone(), app.api.clone()));
                                }
                                app.screen = Screen::Chat;
                            }
                            "building" | "queued" => {
                                app.open_build_for(expert.topic.clone(), expert.tier.clone());
                            }
                            _ => {
                                // Failed: Enter rebuilds in place (same topic + tier).
                                app.start_build(expert.topic.clone(), expert.tier.clone());
                            }
                        }
                    }
                }
                AppAction::NewExpert => {
                    app.home.start_new_expert_input();
                }
                AppAction::DeleteExpert => {
                    if app.home.selected_expert().is_some() {
                        // First press arms the confirmation; second press (handled above) confirms.
                        app.home.confirm_delete = true;
                    }
                }
                AppAction::Char('b') => {
                    if app.build.is_some() {
                        app.screen = Screen::Build;
                    } else if let Some(expert) = app.home.selected_expert().cloned() {
                        if expert.status == "building" || expert.status == "queued" {
                            app.open_build_for(expert.topic, expert.tier);
                        }
                    }
                }
                AppAction::Char('c') => {
                    app.config_screen = ConfigScreen::new(app.config.clone());
                    app.screen = Screen::Config;
                }
                AppAction::Back => {
                    app.should_quit = true;
                }
                _ => {}
            }

            if let Some((topic, tier)) = app.home.take_submitted_build() {
                app.start_build(topic, tier);
            }
        }

        Screen::Build => {
            match action {
                // Quitting the TUI never kills the build — it runs server-side.
                AppAction::Quit => app.should_quit = true,
                // [x] arms cancel; a second [x] confirms and asks the server to stop.
                AppAction::Char('x') => {
                    if let Some(build) = &mut app.build {
                        if build.done || build.error.is_some() {
                            // Nothing to cancel.
                        } else if build.confirm_cancel {
                            build.request_server_cancel();
                        } else {
                            build.confirm_cancel = true;
                        }
                    }
                }
                AppAction::Back => {
                    // Esc first un-arms a pending cancel confirmation.
                    if let Some(build) = &mut app.build {
                        if build.confirm_cancel {
                            build.confirm_cancel = false;
                            return;
                        }
                    }
                    // A finished (failed/cancelled) build is cleared on the way out so
                    // Home doesn't keep a dead card; a running build is left alone and
                    // keeps streaming in the background (re-enter with [b]).
                    let errored = app.build.as_ref().map(|b| b.error.is_some()).unwrap_or(false);
                    if errored {
                        if let Some(b) = &app.build { b.cancel(); }
                        app.build = None;
                    }
                    app.screen = Screen::Home;
                    app.request_refresh();
                }
                _ => {}
            }
        }

        // Chat is handled via handle_raw in the event loop; nothing reaches here.
        Screen::Chat => {}
    }
}

async fn tick_screens(app: &mut App) {
    // Collect any finished background refresh (list / delete-then-list).
    if let Some(rx) = &mut app.refresh_rx {
        match rx.try_recv() {
            Ok(Ok(experts)) => {
                app.refresh_rx = None;
                app.experts = experts.clone();
                app.home.update_experts(experts);
                if let Some(topic) = app.pending_select_topic.take() {
                    app.home.select_by_topic(&topic);
                    app.set_status("Ready to chat — press Enter");
                }
            }
            Ok(Err(e)) => {
                app.refresh_rx = None;
                app.set_status(e);
            }
            Err(oneshot::error::TryRecvError::Empty) => {}
            Err(oneshot::error::TryRecvError::Closed) => { app.refresh_rx = None; }
        }
    }

    // Tick the build stream; capture done state before dropping the borrow.
    let build_done = if let Some(build) = &mut app.build {
        build.tick().await
    } else {
        false
    };

    if build_done {
        let built_topic = app.build.as_ref().map(|b| b.topic().to_string());
        app.build = None;
        app.screen = Screen::Home;
        app.pending_select_topic = built_topic;
        app.request_refresh();
        app.last_expert_poll = std::time::Instant::now();
    }

    // Auto-refresh the expert list while any expert is still queued or building.
    if app.screen == Screen::Home
        && app.refresh_rx.is_none()
        && app.experts.iter().any(|e| e.status == "building" || e.status == "queued")
        && app.last_expert_poll.elapsed().as_secs() >= 5
    {
        app.last_expert_poll = std::time::Instant::now();
        app.request_refresh();
    }

    if let Some(chat) = &mut app.chat {
        chat.tick().await;
    }
}

fn render_help_overlay(f: &mut ratatui::Frame) {
    use ratatui::{
        layout::Rect,
        text::{Line, Span},
        widgets::{Block, BorderType, Borders, Clear, Paragraph},
    };
    use crate::tui::theme::Theme;

    let area = f.area();
    let w = 62u16.min(area.width.saturating_sub(4));
    let h = 24u16.min(area.height.saturating_sub(2));
    let x = area.width.saturating_sub(w) / 2;
    let y = area.height.saturating_sub(h) / 2;
    let rect = Rect::new(x, y, w, h);

    let key = |k: &'static str, d: &'static str| {
        Line::from(vec![
            Span::styled(format!("  {:<13}", k), Theme::accent()),
            Span::styled(d, Theme::normal()),
        ])
    };

    let lines = vec![
        Line::from(Span::styled("Home", Theme::title())),
        key("↑↓←→ hjkl", "Navigate experts"),
        key("Enter", "Chat · watch build · rebuild failed"),
        key("n", "Build a new expert"),
        key("d", "Delete (press again to confirm)"),
        key("b", "Watch the running build"),
        key("c", "Settings"),
        key("q / Esc", "Quit"),
        Line::from(""),
        Line::from(Span::styled("Build", Theme::title())),
        key("x", "Cancel build (press again to confirm)"),
        key("Esc", "Home — build keeps running"),
        Line::from(""),
        Line::from(Span::styled("Chat", Theme::title())),
        key("Enter", "Send message"),
        key("Esc", "Back (conversation is kept)"),
        key("↑↓ PgUp/Dn", "Scroll · End jumps to bottom"),
        Line::from(""),
        Line::from(Span::styled("Text editing (all inputs)", Theme::title())),
        key("←→ Home/End", "Move cursor (Ctrl+A/E too)"),
        key("Ctrl/Alt+←→", "Jump by word (Alt+B/F too)"),
        key("Ctrl+U/K", "Kill to start / end of line"),
        key("Ctrl+W", "Delete word (Alt+Backspace too)"),
        Line::from(""),
        Line::from(Span::styled("  Press any key to close", Theme::dim())),
    ];

    f.render_widget(Clear, rect);
    f.render_widget(
        Paragraph::new(lines).block(
            Block::default()
                .title(" Help ")
                .title_style(Theme::title())
                .borders(Borders::ALL)
                .border_type(BorderType::Rounded)
                .border_style(Theme::accent())
                .style(Theme::normal()),
        ),
        rect,
    );
}
