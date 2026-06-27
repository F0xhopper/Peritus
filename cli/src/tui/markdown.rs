use pulldown_cmark::{Event, HeadingLevel, Options, Parser, Tag, TagEnd};
use ratatui::{
    style::Modifier,
    text::{Line, Span},
};

use crate::tui::theme::Theme;

/// Parse `md` into a list of styled ratatui [`Line`]s.
pub fn render(md: &str) -> Vec<Line<'static>> {
    let parser = Parser::new_ext(md, Options::all());

    let mut lines: Vec<Line<'static>> = Vec::new();
    let mut spans: Vec<Span<'static>> = Vec::new();

    let mut bold = false;
    let mut italic = false;
    let mut in_code_block = false;
    let mut heading: Option<HeadingLevel> = None;
    let mut list_depth: usize = 0;
    let mut link_dest: Option<String> = None;

    // Tables are buffered so we can compute column widths before rendering.
    let mut table_rows: Vec<Vec<String>> = Vec::new();
    let mut current_row: Vec<String> = Vec::new();
    let mut current_cell: Option<String> = None;

    macro_rules! flush {
        () => {
            lines.push(Line::from(std::mem::take(&mut spans)));
        };
    }

    for event in parser {
        match event {
            // ── Headings ──────────────────────────────────────────────────
            Event::Start(Tag::Heading { level, .. }) => {
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

            // ── Links ─────────────────────────────────────────────────────
            // Render the link text underlined, then append the destination so the
            // URL isn't silently lost in a terminal that can't make text clickable.
            Event::Start(Tag::Link { dest_url, .. }) => {
                link_dest = Some(dest_url.into_string());
            }
            Event::End(TagEnd::Link) => {
                if let Some(url) = link_dest.take() {
                    if !url.is_empty() && !url.starts_with('#') {
                        spans.push(Span::styled(format!(" ({})", url), Theme::dim()));
                    }
                }
            }

            // ── Inline code ───────────────────────────────────────────────
            Event::Code(text) => {
                if let Some(cell) = &mut current_cell {
                    cell.push_str(&text);
                } else {
                    spans.push(Span::styled(text.into_string(), Theme::code_inline()));
                }
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

            // ── Tables (buffered for aligned rendering) ───────────────────
            Event::Start(Tag::Table(_)) => {
                if !spans.is_empty() {
                    flush!();
                }
                table_rows.clear();
            }
            Event::End(TagEnd::Table) => {
                render_table(&mut lines, &table_rows);
                table_rows.clear();
                lines.push(Line::from(""));
            }
            Event::Start(Tag::TableHead) | Event::End(TagEnd::TableHead) => {}
            Event::Start(Tag::TableRow) => { current_row.clear(); }
            Event::End(TagEnd::TableRow) => {
                table_rows.push(std::mem::take(&mut current_row));
            }
            Event::Start(Tag::TableCell) => { current_cell = Some(String::new()); }
            Event::End(TagEnd::TableCell) => {
                if let Some(cell) = current_cell.take() {
                    current_row.push(cell);
                }
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
                if let Some(cell) = &mut current_cell {
                    // Inside a table cell — accumulate plain text for alignment.
                    cell.push_str(&text);
                } else if in_code_block {
                    let style = Theme::code_block();
                    let owned = text.into_string();
                    let mut iter = owned.lines().peekable();
                    while let Some(line_text) = iter.next() {
                        spans.push(Span::styled(line_text.to_string(), style));
                        if iter.peek().is_some() {
                            flush!();
                        }
                    }
                } else {
                    let style = if let Some(level) = heading {
                        match level {
                            HeadingLevel::H1 => Theme::heading1(),
                            HeadingLevel::H2 => Theme::heading2(),
                            _ => Theme::heading3(),
                        }
                    } else if link_dest.is_some() {
                        Theme::source().add_modifier(Modifier::UNDERLINED)
                    } else {
                        let mut s = Theme::normal();
                        if bold { s = s.add_modifier(Modifier::BOLD); }
                        if italic { s = s.add_modifier(Modifier::ITALIC); }
                        s
                    };
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

/// Render a buffered table with padded, aligned columns.
fn render_table(lines: &mut Vec<Line<'static>>, rows: &[Vec<String>]) {
    if rows.is_empty() { return; }

    let col_count = rows.iter().map(|r| r.len()).max().unwrap_or(0);
    if col_count == 0 { return; }

    // Compute the minimum width needed for each column.
    let mut col_widths = vec![0usize; col_count];
    for row in rows {
        for (i, cell) in row.iter().enumerate() {
            if i < col_count {
                col_widths[i] = col_widths[i].max(cell.len());
            }
        }
    }

    for (row_idx, row) in rows.iter().enumerate() {
        let mut row_spans: Vec<Span<'static>> = Vec::new();
        let cell_count = row.len().min(col_count);
        for (i, cell) in row.iter().enumerate().take(cell_count) {
            let padded = format!("{:<width$}", cell, width = col_widths[i]);
            let style = if row_idx == 0 {
                Theme::normal().add_modifier(Modifier::BOLD)
            } else {
                Theme::normal()
            };
            row_spans.push(Span::styled(padded, style));
            if i + 1 < cell_count {
                row_spans.push(Span::styled("  │  ", Theme::dim()));
            }
        }
        lines.push(Line::from(row_spans));

        // Divider between header and body.
        if row_idx == 0 {
            let sep_width: usize = col_widths.iter().take(col_count).sum::<usize>()
                + col_count.saturating_sub(1) * 5;
            lines.push(Line::from(Span::styled("─".repeat(sep_width), Theme::dim())));
        }
    }
}
