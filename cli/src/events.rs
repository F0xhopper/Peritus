#[derive(Debug, Clone)]
pub enum AppAction {
    Up,
    Down,
    Left,
    Right,
    Back,
    Quit,
    NewExpert,
    DeleteExpert,
    Help,
    Char(char),
    Backspace,
    Delete,
    Home,
    End,
    CtrlW,
    CtrlU,
    Submit,
    Save,
    Tab,
}

pub fn key_to_action(key: crossterm::event::KeyEvent, in_text_input: bool) -> Option<AppAction> {
    use crossterm::event::{KeyCode, KeyModifiers};

    // While a text input is focused, printable chars always flow through as Char(c)
    // so that keys like n, q, d, j, k can be typed. Esc exits the input (Back).
    if in_text_input {
        return match (key.code, key.modifiers) {
            (KeyCode::Char('c'), KeyModifiers::CONTROL) => Some(AppAction::Quit),
            (KeyCode::Char('s'), KeyModifiers::CONTROL) => Some(AppAction::Save),
            (KeyCode::Char('w'), KeyModifiers::CONTROL) => Some(AppAction::CtrlW),
            (KeyCode::Char('u'), KeyModifiers::CONTROL) => Some(AppAction::CtrlU),
            (KeyCode::Enter, _) => Some(AppAction::Submit),
            (KeyCode::Esc, _) => Some(AppAction::Back),
            (KeyCode::Backspace, _) => Some(AppAction::Backspace),
            (KeyCode::Delete, _) => Some(AppAction::Delete),
            (KeyCode::Home, _) => Some(AppAction::Home),
            (KeyCode::End, _) => Some(AppAction::End),
            (KeyCode::Tab, _) => Some(AppAction::Tab),
            (KeyCode::Char(c), KeyModifiers::NONE) | (KeyCode::Char(c), KeyModifiers::SHIFT) => {
                Some(AppAction::Char(c))
            }
            _ => None,
        };
    }

    match (key.code, key.modifiers) {
        (KeyCode::Char('c'), KeyModifiers::CONTROL) => Some(AppAction::Quit),
        (KeyCode::Char('q'), KeyModifiers::NONE) => Some(AppAction::Quit),
        (KeyCode::Char('s'), KeyModifiers::CONTROL) => Some(AppAction::Save),
        (KeyCode::Char('w'), KeyModifiers::CONTROL) => Some(AppAction::CtrlW),
        (KeyCode::Char('u'), KeyModifiers::CONTROL) => Some(AppAction::CtrlU),
        (KeyCode::Up, _) | (KeyCode::Char('k'), KeyModifiers::NONE) => Some(AppAction::Up),
        (KeyCode::Down, _) | (KeyCode::Char('j'), KeyModifiers::NONE) => Some(AppAction::Down),
        (KeyCode::Left, _) => Some(AppAction::Left),
        (KeyCode::Right, _) => Some(AppAction::Right),
        (KeyCode::Enter, _) => Some(AppAction::Submit),
        (KeyCode::Esc, _) => Some(AppAction::Back),
        (KeyCode::Char('n'), KeyModifiers::NONE) => Some(AppAction::NewExpert),
        (KeyCode::Char('d'), KeyModifiers::NONE) => Some(AppAction::DeleteExpert),
        (KeyCode::Char('?'), _) => Some(AppAction::Help),
        (KeyCode::Backspace, _) => Some(AppAction::Backspace),
        (KeyCode::Delete, _) => Some(AppAction::Delete),
        (KeyCode::Home, _) => Some(AppAction::Home),
        (KeyCode::End, _) => Some(AppAction::End),
        (KeyCode::Tab, _) => Some(AppAction::Tab),
        (KeyCode::Char(c), KeyModifiers::NONE) | (KeyCode::Char(c), KeyModifiers::SHIFT) => {
            Some(AppAction::Char(c))
        }
        _ => None,
    }
}
