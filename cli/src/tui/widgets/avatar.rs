//! Per-expert identicon: an 8×3 block-character badge with the expert's
//! monogram, tinted a colour derived from the name.
//!
//! Mirrors the web app's `PersonaAvatar`: the same expert hashes to the same
//! tone everywhere it appears, so cards stop being a row of identical grey
//! gems and become tellable-apart at a glance. The hash is the same
//! `h*31 + codepoint` the web uses, so an expert keeps one identity across
//! both clients.

use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};

/// Avatar width in terminal cells, including the 1-char gap the caller leaves
/// after it. The drawn badge itself is 8 cells.
pub const WIDTH: u16 = 8;

/// Hues picked to sit alongside the night-blue theme (see theme.rs) while
/// staying distinguishable from the status colours next to them.
const TONES: &[Color] = &[
    Color::Rgb(90, 170, 255),  // Peritus blue
    Color::Rgb(160, 110, 255), // Peritus violet
    Color::Rgb(80, 200, 220),  // teal
    Color::Rgb(120, 210, 130), // leaf
    Color::Rgb(240, 170, 80),  // ochre
    Color::Rgb(240, 120, 150), // rose
];

/// The tone this label always maps to.
pub fn tone_for(label: &str) -> Color {
    let mut hash: i32 = 0;
    for ch in label.chars() {
        hash = hash.wrapping_mul(31).wrapping_add(ch as i32);
    }
    TONES[hash.unsigned_abs() as usize % TONES.len()]
}

/// 8×3 monogram badge. Unselected cards get the same hue dimmed, so selection
/// still reads as a brightness change without every card going grey.
pub fn lines(label: &str, is_selected: bool) -> Vec<Line<'static>> {
    let tone = tone_for(label);
    let (frame, letters) = if is_selected {
        (tone, Style::default().fg(Color::Rgb(235, 238, 250)).add_modifier(Modifier::BOLD))
    } else {
        (scale(tone, 0.55), Style::default().fg(scale(tone, 0.9)).add_modifier(Modifier::BOLD))
    };
    let frame_style = Style::default().fg(frame);

    vec![
        Line::from(Span::styled("░▒▓▓▓▓▒░", frame_style)),
        Line::from(vec![
            Span::styled("▒▓", frame_style),
            Span::styled(format!("{:^4}", initials(label)), letters),
            Span::styled("▓▒", frame_style),
        ]),
        Line::from(Span::styled("░▒▓▓▓▓▒░", frame_style)),
    ]
}

/// Up to two letters for the monogram.
///
/// The honorific is stripped first — every persona is a Dr., so a wall of
/// "DR" badges would identify nobody (same rule as the web's
/// `personaInitials`). Splits on hyphens too, because a persona-less expert
/// falls back to its slug ("stoic-philosophy" → "SP").
fn initials(label: &str) -> String {
    const HONORIFICS: &[&str] = &[
        "dr", "prof", "professor", "sir", "dame", "rev", "fr", "st", "mx",
        "mr", "mrs", "ms", "lord", "lady", "capt", "captain", "maj", "major",
        "col", "colonel", "gen", "general",
    ];

    let mut words: Vec<&str> = label
        .split(|c: char| c.is_whitespace() || c == '-' || c == '_')
        .filter(|w| w.chars().any(|c| c.is_alphanumeric()))
        .collect();

    if let Some(first) = words.first() {
        let bare = first.trim_end_matches('.').to_lowercase();
        if words.len() > 1 && HONORIFICS.contains(&bare.as_str()) {
            words.remove(0);
        }
    }

    let letters: String = words
        .iter()
        .take(2)
        .filter_map(|w| w.chars().find(|c| c.is_alphanumeric()))
        .flat_map(|c| c.to_uppercase())
        .collect();

    if letters.is_empty() { "?".to_string() } else { letters }
}

/// Darken an RGB colour by a factor. Non-RGB colours pass through unchanged
/// (only ever called with the RGB tones above).
fn scale(color: Color, factor: f32) -> Color {
    match color {
        Color::Rgb(r, g, b) => Color::Rgb(
            (r as f32 * factor) as u8,
            (g as f32 * factor) as u8,
            (b as f32 * factor) as u8,
        ),
        other => other,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn initials_strip_honorific_and_take_two_words() {
        assert_eq!(initials("Dr. Elena Vasquez"), "EV");
        assert_eq!(initials("Professor Ada Lovelace"), "AL");
    }

    #[test]
    fn initials_keep_a_name_that_merely_starts_like_an_honorific() {
        assert_eq!(initials("Drummond Field"), "DF");
        // A bare honorific with nothing after it is still a name.
        assert_eq!(initials("Dr"), "D");
    }

    #[test]
    fn initials_split_slugs_on_hyphens() {
        assert_eq!(initials("stoic-philosophy"), "SP");
        assert_eq!(initials(""), "?");
    }

    #[test]
    fn tone_is_deterministic() {
        assert_eq!(tone_for("Dr. Elena Vasquez"), tone_for("Dr. Elena Vasquez"));
    }
}
