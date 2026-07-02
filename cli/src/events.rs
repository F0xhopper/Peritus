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
    // Text-input editing (readline-style)
    CursorLeft,
    CursorRight,
    WordLeft,
    WordRight,
    KillToEnd,   // Ctrl+K
    CtrlW,       // delete word before cursor
    CtrlU,       // kill to line start
    Submit,
    Save,
    Tab,
}

pub fn key_to_action(key: crossterm::event::KeyEvent, in_text_input: bool) -> Option<AppAction> {
    use crossterm::event::{KeyCode, KeyModifiers};

    const ALT: KeyModifiers = KeyModifiers::ALT;
    const CTRL: KeyModifiers = KeyModifiers::CONTROL;

    // While a text input is focused, printable chars always flow through as Char(c)
    // so that keys like n, q, d, j, k can be typed. Esc exits the input (Back).
    // Editing follows readline: arrows/Home/End move, Ctrl/Alt+arrows jump words,
    // Ctrl+W/U/K kill, Delete removes forward.
    if in_text_input {
        return match (key.code, key.modifiers) {
            (KeyCode::Char('c'), CTRL) => Some(AppAction::Quit),
            (KeyCode::Char('s'), CTRL) => Some(AppAction::Save),
            (KeyCode::Char('w'), CTRL) => Some(AppAction::CtrlW),
            (KeyCode::Char('u'), CTRL) => Some(AppAction::CtrlU),
            (KeyCode::Char('k'), CTRL) => Some(AppAction::KillToEnd),
            (KeyCode::Char('a'), CTRL) => Some(AppAction::Home),
            (KeyCode::Char('e'), CTRL) => Some(AppAction::End),
            (KeyCode::Left, CTRL) | (KeyCode::Left, ALT) | (KeyCode::Char('b'), ALT) => {
                Some(AppAction::WordLeft)
            }
            (KeyCode::Right, CTRL) | (KeyCode::Right, ALT) | (KeyCode::Char('f'), ALT) => {
                Some(AppAction::WordRight)
            }
            (KeyCode::Backspace, ALT) => Some(AppAction::CtrlW),
            (KeyCode::Left, _) => Some(AppAction::CursorLeft),
            (KeyCode::Right, _) => Some(AppAction::CursorRight),
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
        (KeyCode::Char('c'), CTRL) => Some(AppAction::Quit),
        (KeyCode::Char('q'), KeyModifiers::NONE) => Some(AppAction::Quit),
        (KeyCode::Char('s'), CTRL) => Some(AppAction::Save),
        // Vim-style navigation alongside the arrows.
        (KeyCode::Up, _) | (KeyCode::Char('k'), KeyModifiers::NONE) => Some(AppAction::Up),
        (KeyCode::Down, _) | (KeyCode::Char('j'), KeyModifiers::NONE) => Some(AppAction::Down),
        (KeyCode::Left, _) | (KeyCode::Char('h'), KeyModifiers::NONE) => Some(AppAction::Left),
        (KeyCode::Right, _) | (KeyCode::Char('l'), KeyModifiers::NONE) => Some(AppAction::Right),
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
