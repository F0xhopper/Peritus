use std::sync::Arc;
use anyhow::Result;
use crossterm::event::{self, Event, KeyEventKind};
use ratatui::DefaultTerminal;

use crate::api::client::{is_unauthorized, ApiClient};
use crate::api::types::{ExpertSummary, Session};
use crate::config::store::{now_unix, Config};
use crate::events::{key_to_action, AppAction};
use crate::tui::screens::{
    build::BuildScreen, chat::ChatScreen, config::ConfigScreen, home::HomeScreen,
    login::{LoginPhase, LoginScreen},
};

#[derive(Debug, Clone, PartialEq)]
pub enum Screen {
    Home,
    Build,
    Chat,
    Config,
    Login,
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
    pub login: LoginScreen,
    pub should_quit: bool,
    pub show_help: bool,
    pub status_msg: Option<(String, std::time::Instant)>,
    pub tick: u64, // increments every render frame (~60fps)
    last_expert_poll: std::time::Instant,
}

impl App {
    pub fn new(config: Config) -> Self {
        let api = Arc::new(ApiClient::new(config.server_url.clone(), config.bearer()));
        Self {
            screen: if config.is_configured() { Screen::Home } else { Screen::Config },
            api: api.clone(),
            config: config.clone(),
            experts: vec![],
            home: HomeScreen::new(),
            build: None,
            chat: None,
            login: LoginScreen::new(config.email.clone()),
            config_screen: ConfigScreen::new(config),
            should_quit: false,
            show_help: false,
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

    // Once a server is configured, refresh an expiring session and load experts.
    // A 401 means the server requires login and we have no valid session.
    if app.screen != Screen::Config {
        ensure_session(app).await;
        startup_load(app).await;
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
                Screen::Login  => app.login.render(f, f.area()),
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
                        let done = chat.handle_raw(key).await;
                        if done {
                            // Return Home but KEEP the conversation so re-entering the
                            // same expert resumes it instead of starting over.
                            app.screen = Screen::Home;
                        }
                    }
                } else {
                    let in_text_input = match app.screen {
                        Screen::Home   => app.home.input_active && !app.home.tier_select_active,
                        Screen::Config => app.config_screen.editing,
                        Screen::Login  => true, // both login fields are always text entry
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
                    app.config.bearer(),
                ));
                app.screen = Screen::Home;
                app.config_screen.saved = false;
                ensure_session(app).await;
                startup_load(app).await;
            }
        }

        Screen::Login => {
            match action {
                AppAction::Back => {
                    if app.login.phase == LoginPhase::Code {
                        app.login.back_to_email();
                    } else {
                        app.should_quit = true;
                    }
                }
                AppAction::Submit if !app.login.busy => {
                    handle_login_submit(app).await;
                }
                AppAction::Char(c) => app.login.input_push(c),
                AppAction::Backspace => app.login.input_pop(),
                _ => {}
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
                    } else if let Some(expert) = app.home.selected_expert().cloned() {
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
                AppAction::Char('c') if !app.home.input_active => {
                    app.config_screen = ConfigScreen::new(app.config.clone());
                    app.screen = Screen::Config;
                }
                AppAction::Char('L') if !app.home.input_active => {
                    app.config.clear_session();
                    let _ = app.config.save();
                    app.api = Arc::new(ApiClient::new(
                        app.config.server_url.clone(),
                        app.config.bearer(),
                    ));
                    app.login = LoginScreen::new(String::new());
                    app.screen = Screen::Login;
                    app.set_status("Signed out");
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
                // A failed build is cleared on the way out so Home doesn't keep a dead
                // card; a running build is left alone and keeps streaming in the
                // background (re-enter with [b]).
                let errored = app.build.as_ref().map(|b| b.error.is_some()).unwrap_or(false);
                if errored {
                    app.build = None;
                    app.set_status("Build failed — try a different topic or check your keys");
                }
                app.screen = Screen::Home;
                if let Ok(experts) = app.api.list_experts().await {
                    app.experts = experts.clone();
                    app.home.update_experts(experts);
                }
            }
        }

        // Chat is handled via handle_raw in the event loop; nothing reaches here.
        Screen::Chat => {}
    }
}

/// Refresh a session whose access token is missing or about to expire. On failure
/// the stored session is cleared so the next API call routes the user to Login.
async fn ensure_session(app: &mut App) {
    if app.config.has_session() && app.config.access_expiring(60) {
        match app.api.refresh(&app.config.refresh_token).await {
            Ok(session) => apply_session(app, session),
            Err(_) => {
                app.config.clear_session();
                let _ = app.config.save();
                app.api = Arc::new(ApiClient::new(
                    app.config.server_url.clone(),
                    app.config.bearer(),
                ));
            }
        }
    }
}

/// Persist a fresh session and rebuild the API client to use the new access token.
fn apply_session(app: &mut App, session: Session) {
    let expires_at = session
        .expires_at
        .unwrap_or_else(|| now_unix() + session.expires_in);
    let email = session.user.email.clone().unwrap_or_default();
    app.config
        .set_session(session.access_token, session.refresh_token, expires_at, email);
    let _ = app.config.save();
    app.api = Arc::new(ApiClient::new(
        app.config.server_url.clone(),
        app.config.bearer(),
    ));
}

/// Load experts at startup, routing to the Login screen on 401.
async fn startup_load(app: &mut App) {
    match app.api.list_experts().await {
        Ok(experts) => {
            app.experts = experts.clone();
            app.home.update_experts(experts);
        }
        Err(e) if is_unauthorized(&e) => {
            app.login = LoginScreen::new(app.config.email.clone());
            app.screen = Screen::Login;
        }
        Err(e) => app.set_status(format!(
            "Cannot reach server at {} — press [c] to change settings ({})",
            app.config.server_url, e
        )),
    }
}

/// Drive the email-OTP login flow: request a code, then verify it for a session.
async fn handle_login_submit(app: &mut App) {
    match app.login.phase {
        LoginPhase::Email => {
            let email = app.login.email.trim().to_string();
            if !email.contains('@') {
                app.login.error = Some("Enter a valid email address".into());
                return;
            }
            app.login.busy = true;
            app.login.error = None;
            app.login.status = Some("Sending code…".into());
            match app.api.otp_request(&email).await {
                Ok(()) => {
                    app.login.phase = LoginPhase::Code;
                    app.login.status = Some(format!("Code sent to {email}"));
                }
                Err(e) => {
                    app.login.status = None;
                    app.login.error = Some(format!("{e}"));
                }
            }
            app.login.busy = false;
        }
        LoginPhase::Code => {
            let email = app.login.email.trim().to_string();
            let code = app.login.code.trim().to_string();
            if code.is_empty() {
                app.login.error = Some("Enter the code from your email".into());
                return;
            }
            app.login.busy = true;
            app.login.error = None;
            app.login.status = Some("Verifying…".into());
            match app.api.otp_verify(&email, &code).await {
                Ok(session) => {
                    apply_session(app, session);
                    app.screen = Screen::Home;
                    let who = if app.config.email.is_empty() { email } else { app.config.email.clone() };
                    app.set_status(format!("Signed in as {who}"));
                    startup_load(app).await;
                }
                Err(e) => {
                    app.login.status = None;
                    app.login.error = Some(format!("{e}"));
                    app.login.code.clear();
                }
            }
            app.login.busy = false;
        }
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

fn render_help_overlay(f: &mut ratatui::Frame) {
    use ratatui::{
        layout::Rect,
        text::{Line, Span},
        widgets::{Block, BorderType, Borders, Clear, Paragraph},
    };
    use crate::tui::theme::Theme;

    let area = f.area();
    let w = 58u16.min(area.width.saturating_sub(4));
    let h = 17u16.min(area.height.saturating_sub(2));
    let x = area.width.saturating_sub(w) / 2;
    let y = area.height.saturating_sub(h) / 2;
    let rect = Rect::new(x, y, w, h);

    let key = |k: &'static str, d: &'static str| {
        Line::from(vec![
            Span::styled(format!("  {:<11}", k), Theme::accent()),
            Span::styled(d, Theme::normal()),
        ])
    };

    let lines = vec![
        Line::from(Span::styled("Home", Theme::title())),
        key("↑↓ / j k", "Navigate experts"),
        key("Enter", "Chat with the selected expert"),
        key("n", "Build a new expert"),
        key("d", "Delete (press again to confirm)"),
        key("b", "Watch the running build"),
        key("c", "Settings"),
        key("L", "Sign out"),
        key("q / Esc", "Quit"),
        Line::from(""),
        Line::from(Span::styled("Chat", Theme::title())),
        key("Enter", "Send message"),
        key("Esc", "Back (conversation is kept)"),
        key("↑↓ PgUp/Dn", "Scroll · End jumps to bottom"),
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
