use std::sync::Arc;
use anyhow::Result;
use crossterm::event::{self, Event, KeyEventKind};
use ratatui::DefaultTerminal;

use crate::api::client::ApiClient;
use crate::api::types::ExpertSummary;
use crate::config::store::Config;
use crate::events::{key_to_action, AppAction};
use crate::tui::screens::{build::BuildScreen, chat::ChatScreen, config::ConfigScreen, home::HomeScreen};

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
    pub selected_idx: usize,
    pub home: HomeScreen,
    pub build: Option<BuildScreen>,
    pub chat: Option<ChatScreen>,
    pub config_screen: ConfigScreen,
    pub should_quit: bool,
    pub status_msg: Option<(String, std::time::Instant)>,
}

impl App {
    pub fn new(config: Config) -> Self {
        let api = Arc::new(ApiClient::new(config.server_url.clone(), config.api_key.clone()));
        Self {
            screen: if config.is_configured() { Screen::Home } else { Screen::Config },
            api: api.clone(),
            config: config.clone(),
            experts: vec![],
            selected_idx: 0,
            home: HomeScreen::new(),
            build: None,
            chat: None,
            config_screen: ConfigScreen::new(config),
            should_quit: false,
            status_msg: None,
        }
    }

    pub fn set_status(&mut self, msg: impl Into<String>) {
        self.status_msg = Some((msg.into(), std::time::Instant::now()));
    }
}

pub async fn run_app(terminal: &mut DefaultTerminal, app: &mut App) -> Result<()> {
    // Initial expert load
    match app.api.list_experts().await {
        Ok(experts) => {
            app.experts = experts.clone();
            app.home.update_experts(experts);
        }
        Err(e) => app.set_status(format!("Failed to load experts: {}", e)),
    }

    loop {
        terminal.draw(|f| {
            match app.screen {
                Screen::Home => app.home.render(f, f.area()),
                Screen::Build => {
                    if let Some(build) = &mut app.build {
                        build.render(f, f.area());
                    }
                }
                Screen::Chat => {
                    if let Some(chat) = &mut app.chat {
                        chat.render(f, f.area());
                    }
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
                    let toast_area = Rect::new(area.width.saturating_sub(w), area.height.saturating_sub(2), w, 1);
                    f.render_widget(Paragraph::new(format!(" {} ", msg)).style(Theme::warning()), toast_area);
                }
            }
        })?;

        // Clear stale toast
        if let Some((_, when)) = &app.status_msg {
            if when.elapsed().as_secs() >= 3 {
                app.status_msg = None;
            }
        }

        if app.should_quit {
            break;
        }

        // Poll events with 16ms timeout (≈60fps)
        if event::poll(std::time::Duration::from_millis(16))? {
            match event::read()? {
                Event::Key(key) if key.kind == KeyEventKind::Press => {
                    if let Some(action) = key_to_action(key) {
                        handle_action(app, action).await;
                    }
                }
                _ => {}
            }
        }

        // Tick background tasks
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
                app.api = Arc::new(ApiClient::new(app.config.server_url.clone(), app.config.api_key.clone()));
                app.screen = Screen::Home;
                app.config_screen.saved = false;
                match app.api.list_experts().await {
                    Ok(experts) => { app.experts = experts.clone(); app.home.update_experts(experts); }
                    Err(e) => app.set_status(format!("Error: {}", e)),
                }
            }
        }
        Screen::Home => {
            match action {
                AppAction::Quit => app.should_quit = true,
                AppAction::Up => app.home.prev(),
                AppAction::Down => app.home.next(),
                AppAction::Left => app.home.prev(),
                AppAction::Right => app.home.next(),
                AppAction::Submit => {
                    if app.home.input_active {
                        app.home.handle_enter();
                    } else if let Some(expert) = app.home.selected_expert() {
                        if expert.status == "ready" {
                            let chat = ChatScreen::new(expert.clone(), app.api.clone());
                            app.chat = Some(chat);
                            app.screen = Screen::Chat;
                        }
                    }
                }
                AppAction::NewExpert => {
                    app.home.start_new_expert_input();
                }
                AppAction::DeleteExpert => {
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
                AppAction::Char(c) => {
                    if app.home.input_active {
                        app.home.input_push(c);
                    }
                }
                AppAction::Backspace => {
                    if app.home.input_active {
                        app.home.input_pop();
                    }
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

            // Check if user submitted new expert topic
            if let Some(topic) = app.home.take_submitted_topic() {
                let build = BuildScreen::new(topic.clone(), app.api.clone());
                app.build = Some(build);
                app.screen = Screen::Build;
            }
        }
        Screen::Build => {
            if let AppAction::Back = action {
                app.build = None;
                app.screen = Screen::Home;
                match app.api.list_experts().await {
                    Ok(experts) => { app.experts = experts.clone(); app.home.update_experts(experts); }
                    Err(_) => {}
                }
            }
        }
        Screen::Chat => {
            let done = if let Some(chat) = &mut app.chat {
                chat.handle(action).await
            } else { false };
            if done {
                app.chat = None;
                app.screen = Screen::Home;
            }
        }
    }
}

async fn tick_screens(app: &mut App) {
    if let Some(build) = &mut app.build {
        let done = build.tick().await;
        if done {
            app.screen = Screen::Home;
            app.build = None;
            match app.api.list_experts().await {
                Ok(experts) => { app.experts = experts.clone(); app.home.update_experts(experts); }
                Err(_) => {}
            }
        }
    }
    if let Some(chat) = &mut app.chat {
        chat.tick().await;
    }
}
