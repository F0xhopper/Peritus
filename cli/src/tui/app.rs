use std::sync::Arc;
use anyhow::Result;
use crossterm::event::{self, Event, KeyEventKind};
use ratatui::DefaultTerminal;

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
    pub status_msg: Option<(String, std::time::Instant)>,
    pub tick: u64, // increments every render frame (~60fps)
    last_expert_poll: std::time::Instant,
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
            status_msg: None,
            tick: 0,
            last_expert_poll: std::time::Instant::now(),
        }
    }

    pub fn set_status(&mut self, msg: impl Into<String>) {
        self.status_msg = Some((msg.into(), std::time::Instant::now()));
    }
}

pub async fn run_app(terminal: &mut DefaultTerminal, app: &mut App) -> Result<()> {
    match app.api.list_experts().await {
        Ok(experts) => {
            app.experts = experts.clone();
            app.home.update_experts(experts);
        }
        Err(e) => app.set_status(format!("Failed to load experts: {}", e)),
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
                        let done = chat.handle_raw(key).await;
                        if done {
                            app.chat = None;
                            app.screen = Screen::Home;
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
    match app.screen {
        Screen::Config => {
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
                match app.api.list_experts().await {
                    Ok(experts) => { app.experts = experts.clone(); app.home.update_experts(experts); }
                    Err(e) => app.set_status(format!("Error: {}", e)),
                }
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
                            match app.api.delete_expert(&slug).await {
                                Ok(()) => {
                                    match app.api.list_experts().await {
                                        Ok(experts) => { app.experts = experts.clone(); app.home.update_experts(experts); }
                                        Err(e) => app.set_status(format!("Error: {}", e)),
                                    }
                                }
                                Err(e) => app.set_status(format!("Delete failed: {}", e)),
                            }
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
                    if app.build.is_some() {
                        app.set_status("A build is already running — press [b] to watch it");
                    } else {
                        let build = BuildScreen::new(topic, tier, app.api.clone());
                        app.build = Some(build);
                        app.screen = Screen::Build;
                    }
                }
                return;
            }

            match action {
                AppAction::Quit => app.should_quit = true,
                AppAction::Up | AppAction::Left  => {
                    if app.home.input_active { /* ignore nav in input mode */ } else { app.home.prev(); }
                }
                AppAction::Down | AppAction::Right => {
                    if app.home.input_active { /* ignore nav in input mode */ } else { app.home.next(); }
                }
                AppAction::Submit => {
                    if app.home.input_active {
                        app.home.handle_enter();
                    } else if let Some(expert) = app.home.selected_expert() {
                        match expert.status.as_str() {
                            "ready" => {
                                let chat = ChatScreen::new(expert.clone(), app.api.clone());
                                app.chat = Some(chat);
                                app.screen = Screen::Chat;
                            }
                            "building" => app.set_status("Expert is still building — please wait"),
                            _          => app.set_status("Expert build failed — try rebuilding with [d] delete then [n] new"),
                        }
                    }
                }
                AppAction::NewExpert => {
                    if !app.home.input_active { app.home.start_new_expert_input(); }
                }
                AppAction::DeleteExpert => {
                    if !app.home.input_active && app.home.selected_expert().is_some() {
                        // First press arms the confirmation; second press (handled above) confirms.
                        app.home.confirm_delete = true;
                    }
                }
                AppAction::Char('b') if !app.home.input_active && app.build.is_some() => {
                    app.screen = Screen::Build;
                }
                AppAction::Char(c) => {
                    if app.home.input_active { app.home.input_push(c); }
                }
                AppAction::Backspace => {
                    if app.home.input_active { app.home.input_pop(); }
                }
                AppAction::Back => {
                    if app.home.input_active {
                        app.home.cancel_input();
                    } else {
                        app.should_quit = true;
                    }
                }
                _ => {}
            }

            if let Some((topic, tier)) = app.home.take_submitted_build() {
                if app.build.is_some() {
                    app.set_status("A build is already running — press [b] to watch it");
                } else {
                    let build = BuildScreen::new(topic, tier, app.api.clone());
                    app.build = Some(build);
                    app.screen = Screen::Build;
                }
            }
        }

        Screen::Build => {
            if let AppAction::Back = action {
                // Navigate home without cancelling — the build keeps running in the background.
                app.screen = Screen::Home;
                match app.api.list_experts().await {
                    Ok(experts) => { app.experts = experts.clone(); app.home.update_experts(experts); }
                    Err(_) => {}
                }
            }
        }

        // Chat is handled via handle_raw in the event loop; nothing reaches here.
        Screen::Chat => {}
    }
}

async fn tick_screens(app: &mut App) {
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
        match app.api.list_experts().await {
            Ok(experts) => {
                app.experts = experts.clone();
                app.home.update_experts(experts);
                if let Some(topic) = built_topic {
                    app.home.select_by_topic(&topic);
                    app.set_status("Ready to chat — press Enter");
                }
            }
            Err(_) => {}
        }
        app.last_expert_poll = std::time::Instant::now();
    }

    // Auto-refresh the expert list while any expert is still building.
    if app.screen == Screen::Home
        && app.experts.iter().any(|e| e.status == "building")
        && app.last_expert_poll.elapsed().as_secs() >= 5
    {
        app.last_expert_poll = std::time::Instant::now();
        if let Ok(experts) = app.api.list_experts().await {
            app.experts = experts.clone();
            app.home.update_experts(experts);
        }
    }

    if let Some(chat) = &mut app.chat {
        chat.tick().await;
    }
}
