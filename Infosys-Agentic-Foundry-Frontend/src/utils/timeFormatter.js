/**
 * Generic time parsing & formatting helpers.
 *
 * Supports the following input shapes:
 *  - Epoch milliseconds (e.g. 1759588911107)
 *  - Epoch seconds (10-digit) (e.g. 1712345678)
 *  - Plain numeric seconds or fractional seconds (e.g. 7.2323343, "9", "60.36784")
 *  - Date/time strings in common formats (ISO, '12-Dec-2025 19:26', '2025-12-12', '19:26', etc.)
 *  - A raw milliseconds value (>= 1000 and < 1e12) can be auto-detected if options.explicitUnit not provided.
 *
 * The core exported helper for immediate project use is formatDurationSeconds / formatResponseTime.
 */

/**Sample usages:
*  Duration from raw seconds or fractional string
*    formatDurationSeconds(7.2323343); // '7.23s'

*  Force treat as milliseconds
*    formatTime(1759588911107, { mode: "date", datePattern: "MMM Do, YYYY HH:mm" });

*  Auto-detect epoch vs duration
*    formatTime("12-Dec-2025 19:26", { mode: "auto", datePattern: "DD/MM HH:mm" }); // '12/12 19:26'

*  Ordinal style
*    formatDate(new Date(), "Do MMM"); // '4th Oct'
 */

// Month short names map for simple custom parsing like 12-Dec-2025 19:26
const MONTHS_SHORT = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

/**
 * Try to detect if a numeric value is epoch ms, epoch s, or just seconds.
 * @param {number} n
 * @returns {"epoch-ms"|"epoch-s"|"seconds"}
 */
function classifyNumeric(n) {
  if (n > 1e12) return "epoch-ms"; // ms epoch (far future) – defensive
  if (n > 1e11) return "epoch-ms"; // realistic current epoch ms (> 2001)
  if (n > 1e9) return "epoch-s"; // likely epoch seconds
  return "seconds"; // treat as duration seconds
}

/**
 * Attempt to parse a date/time string into a Date.
 * Returns Date or null if cannot parse.
 * @param {string} input
 */
export function parseToDate(input) {
  if (!input || typeof input !== "string") return null;
  const trimmed = input.trim();
  if (!trimmed) return null;

  // ISO / native parse first
  const native = Date.parse(trimmed);
  if (!Number.isNaN(native)) return new Date(native);

  // Custom format: 12-Dec-2025 19:26 or 12-Dec-2025
  const m = /^([0-3]?\d)-([A-Za-z]{3})-([0-9]{4})(?:\s+([0-2]?\d:[0-5]\d)(?::([0-5]\d))?)?$/.exec(trimmed);
  if (m) {
    const day = parseInt(m[1], 10);
    const monIdx = MONTHS_SHORT.indexOf(m[2].toLowerCase());
    const year = parseInt(m[3], 10);
    if (monIdx !== -1) {
      let hours = 0,
        minutes = 0,
        seconds = 0;
      if (m[4]) {
        [hours, minutes] = m[4].split(":").map((v) => parseInt(v, 10));
      }
      if (m[5]) seconds = parseInt(m[5], 10);
      const d = new Date(Date.UTC(year, monIdx, day, hours, minutes, seconds));
      return d;
    }
  }

  // Time only HH:mm(:ss)
  const t = /^([0-2]?\d):([0-5]\d)(?::([0-5]\d))?$/.exec(trimmed);
  if (t) {
    const now = new Date();
    const h = parseInt(t[1], 10),
      min = parseInt(t[2], 10),
      s = t[3] ? parseInt(t[3], 10) : 0;
    now.setHours(h, min, s, 0);
    return now;
  }

  return null;
}

/**
 * Format an ordinal day (12 -> 12th)
 */
export function ordinal(n) {
  const s = ["th", "st", "nd", "rd"],
    v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

/**
 * Format a Date using a tiny token subset.
 * Tokens supported: YYYY, MM, DD, DDD (short month), MMM (short month), Do (ordinal day), HH, mm, ss.
 * @param {Date} date
 * @param {string} pattern
 */
export function formatDate(date, pattern) {
  if (!(date instanceof Date) || isNaN(date)) return "";
  const pad = (n, l = 2) => String(n).padStart(l, "0");
  const monthShort = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][date.getMonth()];
  return pattern
    .replace(/YYYY/g, date.getFullYear())
    .replace(/MM/g, pad(date.getMonth() + 1))
    .replace(/DD/g, pad(date.getDate()))
    .replace(/Do/g, ordinal(date.getDate()))
    .replace(/MMM/g, monthShort)
    .replace(/HH/g, pad(date.getHours()))
    .replace(/mm/g, pad(date.getMinutes()))
    .replace(/ss/g, pad(date.getSeconds()));
}

/**
 * Format a numeric duration in seconds (may be fractional).
 * @param {number} seconds
 * @param {{decimals?:number, trimTrailingZeros?:boolean, suffix?:string, omitSuffixIfGE60?:boolean}} options
 */
export function formatDurationSeconds(seconds, options = {}) {
  if (seconds == null || seconds === "") return "";
  const { decimals = 2, trimTrailingZeros = true, suffix = "s", omitSuffixIfGE60 = false } = options;
  const num = typeof seconds === "number" ? seconds : parseFloat(seconds);
  if (Number.isNaN(num)) return "";
  const rounded = decimals >= 0 ? Number(num.toFixed(decimals)) : num;
  let str = decimals > 0 ? rounded.toFixed(decimals) : String(Math.round(rounded));
  if (trimTrailingZeros && str.includes(".")) {
    str = str.replace(/\.?(0+)$/, "");
  }
  const finalSuffix = omitSuffixIfGE60 && rounded >= 60 ? "" : suffix;
  return str + finalSuffix;
}

/**
 * General formatter. If the input resolves to a date and mode !== 'duration', formats the date. Otherwise treats as seconds duration.
 * @param {any} input
 * @param {{mode?:'auto'|'duration'|'date', datePattern?:string, duration?:Parameters<typeof formatDurationSeconds>[1], explicitUnit?:'ms'|'s'}} options
 */
export function formatTime(input, options = {}) {
  const { mode = "auto", datePattern = "MMM DD, YYYY HH:mm", duration = {}, explicitUnit } = options;

  // Numeric only path
  if (typeof input === "number" || (typeof input === "string" && /^\d+(?:\.\d+)?$/.test(input.trim()))) {
    const num = typeof input === "number" ? input : parseFloat(input);
    if (explicitUnit === "ms") return formatDurationSeconds(num / 1000, duration);
    if (explicitUnit === "s") return formatDurationSeconds(num, duration);

    const classification = classifyNumeric(num);
    if (classification === "epoch-ms") {
      return mode === "duration" ? formatDurationSeconds(num / 1000, duration) : formatDate(new Date(num), datePattern);
    }
    if (classification === "epoch-s") {
      return mode === "duration" ? formatDurationSeconds(num, duration) : formatDate(new Date(num * 1000), datePattern);
    }
    return formatDurationSeconds(num, duration);
  }

  // Non-numeric: try date parse
  const d = parseToDate(String(input));
  if (d && (mode === "auto" || mode === "date")) {
    return formatDate(d, datePattern);
  }

  // Fallback: attempt to parse float for duration
  const maybeNum = parseFloat(input);
  if (!Number.isNaN(maybeNum)) return formatDurationSeconds(maybeNum, duration);
  return "";
}

/** Specific helper for current requirement in MsgBox: round to 2 decimals, append 's' except when >= 60 seconds (per provided examples). */
export function formatResponseTimeSeconds(value) {
  return formatDurationSeconds(value, { decimals: 2, trimTrailingZeros: true, suffix: "s", omitSuffixIfGE60: true });
}

/**
 * Normalize a UTC timestamp string to ensure it ends with 'Z' for proper parsing.
 * @param {string} timestamp - The timestamp string to normalize
 * @returns {string|null} - The normalized timestamp or null if invalid input
 */
export function normalizeUTCTimestamp(timestamp) {
  if (!timestamp || typeof timestamp !== "string") return null;

  const trimmed = timestamp.trim();
  if (!trimmed) return null;

  // If the timestamp doesn't end with 'Z' and does not have an explicit timezone offset,
  // append 'Z' so that it is treated as UTC.
  const hasZulu = trimmed.endsWith("Z");
  // Detect timezone offsets like +05:00, -05:00, +0500, or -0500 at the end of the string.
  const hasOffset =
    /[+-]\d{2}:\d{2}$/.test(trimmed) ||
    /[+-]\d{2}$/.test(trimmed);

  if (!hasZulu && !hasOffset) {
    return trimmed + "Z";
  }

  return trimmed;
}

/**
 * Format a message timestamp with relative date display (Today, Yesterday, weekday, or date).
 * Returns both display text and full formatted time for tooltip.
 * 
 * @param {string} timestamp - UTC timestamp string
 * @returns {{displayText: string, fullTime: string}|null} - Formatted timestamps or null if invalid
 * 
 * @example
 * formatMessageTimestamp("2025-12-22T10:30:00Z");
 * // Returns: { displayText: "10:30 AM", fullTime: "Dec 22, 2025, 10:30:00 AM" }
 * 
 * formatMessageTimestamp("2025-12-21T14:45:00Z");
 * // Returns: { displayText: "Yesterday 2:45 PM", fullTime: "Dec 21, 2025, 2:45:00 PM" }
 */
export function formatMessageTimestamp(timestamp) {
  if (!timestamp) return null;

  // Normalize UTC timestamp
  const normalizedTimestamp = normalizeUTCTimestamp(timestamp);
  if (!normalizedTimestamp) return null;

  // Convert to Date object
  const utcDate = new Date(normalizedTimestamp);

  // Check if date is valid
  if (isNaN(utcDate.getTime())) return null;

  // Calculate relative date
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDate = new Date(utcDate.getFullYear(), utcDate.getMonth(), utcDate.getDate());
  const diffDays = Math.floor((today - msgDate) / (1000 * 60 * 60 * 24));

  // Determine date prefix based on how old the message is
  let datePrefix = "";
  if (diffDays === 0) {
    datePrefix = ""; // Don't show "Today" for today's messages
  } else if (diffDays === 1) {
    datePrefix = "Yesterday";
  } else if (diffDays < 7) {
    datePrefix = utcDate.toLocaleDateString([], { weekday: "long" });
  } else {
    datePrefix = utcDate.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  // Format time in 12-hour format with AM/PM
  const timeStr = utcDate.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });

  // Build display text
  const displayText = datePrefix ? `${datePrefix} ${timeStr}` : timeStr;

  // Full timestamp for tooltip
  const fullTime = utcDate.toLocaleString([], {
    month: "short",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });

  return { displayText, fullTime };
}

export default {
  parseToDate,
  formatDate,
  ordinal,
  formatDurationSeconds,
  formatTime,
  formatResponseTimeSeconds,
  normalizeUTCTimestamp,
  formatMessageTimestamp,
};
