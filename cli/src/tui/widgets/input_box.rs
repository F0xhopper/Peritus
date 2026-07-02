//! Shared single-line text input with full cursor editing.
//!
//! Used by the chat input, the new-expert topic popup, and the config fields so
//! all three behave identically: arrow/word movement, Home/End, forward delete,
//! readline-style kills (Ctrl+U/K/W), and a scrolling viewport for long text.

use ratatui::style::{Modifier, Style};
use ratatui::text::Span;

#[derive(Debug, Clone, Default)]
pub struct TextInput {
    chars: Vec<char>,
    cursor: usize, // char index in 0..=chars.len(); == len() means "at end"
}

impl TextInput {
    pub fn new() -> Self { Self::default() }

    pub fn from(s: &str) -> Self {
        let chars: Vec<char> = s.chars().collect();
        let cursor = chars.len();
        Self { chars, cursor }
    }

    pub fn text(&self) -> String { self.chars.iter().collect() }
    pub fn is_empty(&self) -> bool { self.chars.is_empty() }

    pub fn clear(&mut self) {
        self.chars.clear();
        self.cursor = 0;
    }

    /// Take the trimmed contents and reset the input.
    pub fn take_trimmed(&mut self) -> String {
        let out = self.text().trim().to_string();
        self.clear();
        out
    }

    // ── editing ─────────────────────────────────────────────────────────────

    pub fn insert(&mut self, c: char) {
        self.chars.insert(self.cursor, c);
        self.cursor += 1;
    }

    pub fn backspace(&mut self) {
        if self.cursor > 0 {
            self.cursor -= 1;
            self.chars.remove(self.cursor);
        }
    }

    pub fn delete(&mut self) {
        if self.cursor < self.chars.len() {
            self.chars.remove(self.cursor);
        }
    }

    /// Ctrl+W / Alt+Backspace: delete the word before the cursor.
    pub fn delete_word_back(&mut self) {
        let start = self.prev_word_boundary();
        self.chars.drain(start..self.cursor);
        self.cursor = start;
    }

    /// Ctrl+U: kill from the start of the line to the cursor.
    pub fn kill_to_start(&mut self) {
        self.chars.drain(..self.cursor);
        self.cursor = 0;
    }

    /// Ctrl+K: kill from the cursor to the end of the line.
    pub fn kill_to_end(&mut self) {
        self.chars.truncate(self.cursor);
    }

    // ── movement ────────────────────────────────────────────────────────────

    pub fn left(&mut self)  { self.cursor = self.cursor.saturating_sub(1); }
    pub fn right(&mut self) { self.cursor = (self.cursor + 1).min(self.chars.len()); }
    pub fn home(&mut self)  { self.cursor = 0; }
    pub fn end(&mut self)   { self.cursor = self.chars.len(); }

    pub fn word_left(&mut self)  { self.cursor = self.prev_word_boundary(); }
    pub fn word_right(&mut self) { self.cursor = self.next_word_boundary(); }

    fn prev_word_boundary(&self) -> usize {
        let mut i = self.cursor;
        while i > 0 && self.chars[i - 1].is_whitespace() { i -= 1; }
        while i > 0 && !self.chars[i - 1].is_whitespace() { i -= 1; }
        i
    }

    fn next_word_boundary(&self) -> usize {
        let n = self.chars.len();
        let mut i = self.cursor;
        while i < n && self.chars[i].is_whitespace() { i += 1; }
        while i < n && !self.chars[i].is_whitespace() { i += 1; }
        i
    }

    // ── rendering ───────────────────────────────────────────────────────────

    /// Render as spans with a block cursor, windowed so the cursor stays visible
    /// when the text is wider than `width` columns. `show_cursor` disables the
    /// cursor for read-only display (e.g. while a response is streaming).
    pub fn spans(&self, width: usize, base: Style, show_cursor: bool) -> Vec<Span<'static>> {
        let cursor_style = base.add_modifier(Modifier::REVERSED);
        let n = self.chars.len();

        // Window [start, end) of at most `width` chars keeping the cursor in view
        // (cursor may sit one past the last char, so reserve a cell for it).
        let width = width.max(4);
        let start = (self.cursor + 1).saturating_sub(width);
        let end = (start + width.saturating_sub(1)).min(n);

        let before: String = self.chars[start..self.cursor.min(end)].iter().collect();
        let mut spans = Vec::with_capacity(4);
        if start > 0 {
            spans.push(Span::styled("…", base.add_modifier(Modifier::DIM)));
        }
        spans.push(Span::styled(before, base));
        if show_cursor {
            if self.cursor < n {
                spans.push(Span::styled(self.chars[self.cursor].to_string(), cursor_style));
                let after: String = self.chars[self.cursor + 1..end].iter().collect();
                spans.push(Span::styled(after, base));
            } else {
                spans.push(Span::styled(" ", cursor_style));
            }
        } else if self.cursor < end {
            let after: String = self.chars[self.cursor..end].iter().collect();
            spans.push(Span::styled(after, base));
        }
        if end < n {
            spans.push(Span::styled("…", base.add_modifier(Modifier::DIM)));
        }
        spans
    }
}
