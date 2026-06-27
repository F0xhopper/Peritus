use pulldown_cmark::{Event, HeadingLevel, Options, Parser, Tag, TagEnd};
use ratatui::{
    style::Modifier,
    text::{Line, Span},
};

use crate::tui::theme::Theme;

/// Parse `md` into a list of styled ratatui [`Line`]s.
///
/// pulldown-cmark strips all marker characters (`#`, `**`, `` ` ``, etc.)
/// before emitting `Event::Text`, so this renderer never shows raw syntax.
pub fn render(md: &str) -> Vec<Line<'static>> {
    let parser = Parser::new_ext(md, Options::all());

    let mut lines: Vec<Line<'static>> = Vec::new();
    let mut spans: Vec<Span<'static>> = Vec::new();

    let mut bold = false;
    let mut italic = false;
    let mut in_code_block = false;
    let mut in_table_head = false;
    let mut heading: Option<HeadingLevel> = None;
    let mut list_depth: usize = 0;

    macro_rules! flush {
        () => {
            lines.push(Line::from(std::mem::take(&mut spans)));
        };
    }

    for event in parser {
        match event {
            // ── Headings ──────────────────────────────────────────────────
            Event::Start(Tag::Heading { level, .. }) => {
                // Always start a heading on a fresh line.
                if !spans.is_empty() {
                    flush!();
                }
                heading = Some(level);
                let (prefix, style) = match level {
                    HeadingLevel::H1 => ("▌ ", Theme::heading1()),
                    HeadingLevel::H2 => ("▏ ", Theme::heading2()),
                    _ => ("  ", Theme::heading3()),
                };
                spans.push(Span::styled(prefix, style));
            }
            Event::End(TagEnd::Heading(level)) => {
                flush!();
                if level == HeadingLevel::H1 {
                    lines.push(Line::from(Span::styled(
                        "─".repeat(48),
                        Theme::dim(),
                    )));
                }
                lines.push(Line::from(""));
                heading = None;
            }

            // ── Paragraphs ────────────────────────────────────────────────
            Event::Start(Tag::Paragraph) => {}
            Event::End(TagEnd::Paragraph) => {
                if !spans.is_empty() {
                    flush!();
                }
                lines.push(Line::from(""));
            }

            // ── Inline emphasis ───────────────────────────────────────────
            Event::Start(Tag::Strong) => { bold = true; }
            Event::End(TagEnd::Strong) => { bold = false; }
            Event::Start(Tag::Emphasis) => { italic = true; }
            Event::End(TagEnd::Emphasis) => { italic = false; }

            // ── Inline code ───────────────────────────────────────────────
            Event::Code(text) => {
                spans.push(Span::styled(text.into_string(), Theme::code_inline()));
            }

            // ── Fenced / indented code blocks ─────────────────────────────
            Event::Start(Tag::CodeBlock(_)) => { in_code_block = true; }
            Event::End(TagEnd::CodeBlock) => {
                if !spans.is_empty() {
                    flush!();
                }
                lines.push(Line::from(""));
                in_code_block = false;
            }

            // ── Tables ────────────────────────────────────────────────────
            Event::Start(Tag::Table(_)) => {
                if !spans.is_empty() {
                    flush!();
                }
            }
            Event::End(TagEnd::Table) => {
                lines.push(Line::from(""));
            }
            Event::Start(Tag::TableHead) => { in_table_head = true; }
            Event::End(TagEnd::TableHead) => {
                in_table_head = false;
                lines.push(Line::from(Span::styled("─".repeat(48), Theme::dim())));
            }
            Event::Start(Tag::TableRow) => {}
            Event::End(TagEnd::TableRow) => {
                if !spans.is_empty() {
                    flush!();
                }
            }
            Event::Start(Tag::TableCell) => {}
            Event::End(TagEnd::TableCell) => {
                spans.push(Span::styled("  │  ", Theme::dim()));
            }

            // ── Lists ─────────────────────────────────────────────────────
            Event::Start(Tag::List(_)) => { list_depth += 1; }
            Event::End(TagEnd::List(_)) => {
                list_depth = list_depth.saturating_sub(1);
                if list_depth == 0 {
                    lines.push(Line::from(""));
                }
            }
            Event::Start(Tag::Item) => {
                let indent = "  ".repeat(list_depth.saturating_sub(1));
                spans.push(Span::styled(
                    format!("{}• ", indent),
                    Theme::accent(),
                ));
            }
            Event::End(TagEnd::Item) => {
                if !spans.is_empty() {
                    flush!();
                }
            }

            // ── Text ──────────────────────────────────────────────────────
            Event::Text(text) => {
                let style = if let Some(level) = heading {
                    match level {
                        HeadingLevel::H1 => Theme::heading1(),
                        HeadingLevel::H2 => Theme::heading2(),
                        _ => Theme::heading3(),
                    }
                } else if in_code_block {
                    Theme::code_block()
                } else if in_table_head {
                    Theme::normal().add_modifier(Modifier::BOLD)
                } else {
                    let mut s = Theme::normal();
                    if bold { s = s.add_modifier(Modifier::BOLD); }
                    if italic { s = s.add_modifier(Modifier::ITALIC); }
                    s
                };

                if in_code_block {
                    // Code block text may span multiple internal lines.
                    let owned = text.into_string();
                    let mut iter = owned.lines().peekable();
                    while let Some(line_text) = iter.next() {
                        spans.push(Span::styled(line_text.to_string(), style));
                        if iter.peek().is_some() {
                            flush!();
                        }
                    }
                } else {
                    spans.push(Span::styled(text.into_string(), style));
                }
            }

            // ── Breaks ───────────────────────────────────────────────────
            Event::SoftBreak => { spans.push(Span::raw(" ")); }
            Event::HardBreak => { flush!(); }

            // ── Horizontal rule ───────────────────────────────────────────
            Event::Rule => {
                lines.push(Line::from(Span::styled("─".repeat(60), Theme::dim())));
                lines.push(Line::from(""));
            }

            _ => {}
        }
    }

    if !spans.is_empty() {
        lines.push(Line::from(spans));
    }

    lines
}
