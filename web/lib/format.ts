const MINUTE = 60;
const HOUR = MINUTE * 60;
const DAY = HOUR * 24;
const WEEK = DAY * 7;

/** Compact relative time ("2h ago") for chat lists. Falls back to an absolute
 * date past a month, where "5 weeks ago" stops being useful. */
export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";

  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < MINUTE) return "just now";
  if (seconds < HOUR) return `${Math.floor(seconds / MINUTE)}m ago`;
  if (seconds < DAY) return `${Math.floor(seconds / HOUR)}h ago`;
  if (seconds < WEEK) return `${Math.floor(seconds / DAY)}d ago`;
  if (seconds < DAY * 30) return `${Math.floor(seconds / WEEK)}w ago`;

  return new Date(then).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** Thousands-compacted counts ("1.2k") for the metric strips on expert cards,
 * where chunk and node counts run into five digits and the exact value is
 * never the point — the detail page carries the precise number. */
export function formatCompact(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) < 1000) return String(value);

  const thousands = value / 1000;
  // 1.2k below ten thousand, then 12k — a decimal past that is false precision.
  return Math.abs(thousands) < 10
    ? `${thousands.toFixed(1).replace(/\.0$/, "")}k`
    : `${Math.round(thousands)}k`;
}

/** Source quality is scored 0–10 by the validator (see
 * api/src/peritus/sources/validator.py), so the scale ships with the number —
 * a bare "8.4" reads like a fraction of 1. Matches the CLI's "x.x / 10". */
export function formatQuality(value: number | null): string {
  return value == null ? "—" : `${value.toFixed(1)}/10`;
}
