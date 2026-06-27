// Spinner frame sets and helpers for Peritus animated UI elements.
// All spinners run against the app's 60fps tick counter and advance at their
// own cadence so different indicators never feel locked-together.

/// Braille dot spinner — smooth, 10-frame cycle, ideal for "working" states.
pub const BRAILLE: &[&str] = &["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

/// High-density braille — 8-frame, slightly faster feel for active streams.
pub const DOTS: &[&str] = &["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"];

/// Blinking block cursor — 2-frame, used for text input indicators.
pub const CURSOR: &[&str] = &["▌", " "];

/// Pulsing block — slow breathe for streaming text.
pub const PULSE: &[&str] = &["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█", "▉", "▊", "▋", "▌", "▍", "▎", "▏"];

/// Pick the frame for `frames` at the app tick, advancing at `fps` per second.
/// The global render loop is 60fps; this scales down to the desired cadence.
pub fn frame<'a>(frames: &'a [&'a str], fps: u64, tick: u64) -> &'a str {
    let step = (60 / fps.max(1)).max(1);
    frames[(tick / step) as usize % frames.len()]
}

/// Braille spinner at 12fps.
pub fn braille(tick: u64) -> &'static str { frame(BRAILLE, 12, tick) }

/// Dense-dot spinner at 10fps (slightly different feel from braille).
pub fn dots(tick: u64) -> &'static str { frame(DOTS, 10, tick) }

/// Blinking input cursor at 2fps.
pub fn cursor(tick: u64) -> &'static str { frame(CURSOR, 2, tick) }

/// Pulsing streaming indicator at 8fps.
pub fn pulse(tick: u64) -> &'static str { frame(PULSE, 8, tick) }
