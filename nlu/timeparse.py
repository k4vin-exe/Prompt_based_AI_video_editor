"""
nlu/timeparse.py
----------------
Deterministic time expression parser.  (R-TIME-05 through R-TIME-08)

Converts natural-language time expressions into integer microseconds.
NO LLM involved — this is pure deterministic regex + arithmetic.

Supported formats (R-TIME-05):
  "1:20"         -> 80 seconds
  "1:20:05"      -> 1h 20m 5s
  "80 seconds"   -> 80 seconds
  "80 s"         -> 80 seconds
  "2 minutes"    -> 120 seconds
  "2 mins"       -> 120 seconds
  "2 min"        -> 120 seconds
  "a minute twenty" -> 80 seconds
  "the last 10 seconds"  -> relative to current duration
  "the first 30 seconds" -> from t=0
  "last 10 s"    -> same as "the last 10 seconds"
  "first 30 s"   -> same as "the first 30 seconds"

Returns (microseconds: int, is_relative: bool, relative_anchor: str)
  is_relative=True means the value depends on current duration.
  relative_anchor: "end" | "start" | None
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple


SECONDS_PER_MINUTE = 60
MICROSECONDS_PER_SECOND = 1_000_000


class TimeParseError(ValueError):
    """Raised when a time expression cannot be parsed.  (R-REJECT: TIME_PARSE_ERROR)"""
    pass


@dataclass
class ParsedTime:
    """
    Result of parsing a time expression.

    value_us        : resolved microseconds (absolute, or offset if relative)
    is_relative     : True if this is "last N s" or "first N s"
    relative_anchor : "end" | "start" | None
    original        : the original string, for display
    """
    value_us: int
    is_relative: bool
    relative_anchor: Optional[str]   # "end" | "start" | None
    original: str

    def resolve(self, current_duration_us: int) -> int:
        """
        Resolve to an absolute microsecond position.
        For relative times, computes against current_duration_us.  (R-TIME-06)
        """
        if not self.is_relative:
            return self.value_us
        if self.relative_anchor == "end":
            return max(0, current_duration_us - self.value_us)
        else:  # "start"
            return min(self.value_us, current_duration_us)


# ── Regex patterns ────────────────────────────────────────────────────────────

# "the last N seconds/minutes" or "last N s"
_LAST_RE = re.compile(
    r"(?:the\s+)?last\s+"
    r"(?P<value>[\d.]+)\s*"
    r"(?P<unit>s(?:ec(?:ond)?s?)?|m(?:in(?:ute)?s?)?)",
    re.IGNORECASE,
)

# "the first N seconds/minutes" or "first N s"
_FIRST_RE = re.compile(
    r"(?:the\s+)?first\s+"
    r"(?P<value>[\d.]+)\s*"
    r"(?P<unit>s(?:ec(?:ond)?s?)?|m(?:in(?:ute)?s?)?)",
    re.IGNORECASE,
)

# H:MM:SS or M:SS
_COLON_RE = re.compile(
    r"(?:(?P<hours>\d+):)?(?P<minutes>\d+):(?P<seconds>\d{2})"
)

# "N seconds" / "N minutes" / "N mins" / "N s" / "N m"
_UNIT_RE = re.compile(
    r"(?P<value>[\d.]+)\s*"
    r"(?P<unit>s(?:ec(?:ond)?s?)?|m(?:in(?:ute)?s?)?)",
    re.IGNORECASE,
)

# Natural language: "a minute twenty" = 1:20 = 80 s
# "a minute" = 60 s, "two minutes thirty" etc.
_NATURAL_MINUTE_RE = re.compile(
    r"(?:a|one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
    r"\s+minute(?:s)?"
    r"(?:\s+(?:and\s+)?"
    r"(?P<extra_value>[\d.]+)\s*"
    r"(?P<extra_unit>s(?:ec(?:ond)?s?)?)?)?",
    re.IGNORECASE,
)

_WORD_TO_INT = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60,
}


def _unit_to_seconds(unit_str: str) -> float:
    u = unit_str.lower()
    if u.startswith("m"):
        return SECONDS_PER_MINUTE
    return 1.0


def parse_time(expr: str, current_duration_us: Optional[int] = None) -> ParsedTime:
    """
    Parse a time expression string to a ParsedTime.
    Raises TimeParseError if no pattern matches.  (R-TIME-08)
    If current_duration_us is provided, relative times ("last 10s") are resolved to absolute time.
    """
    expr = expr.strip()

    # 1. "last N seconds/minutes"
    m = _LAST_RE.search(expr)
    if m:
        value_s = float(m.group("value")) * _unit_to_seconds(m.group("unit"))
        raw_us = int(value_s * MICROSECONDS_PER_SECOND)
        resolved_us = (current_duration_us - raw_us) if current_duration_us is not None else raw_us
        return ParsedTime(
            value_us=resolved_us,
            is_relative=True,
            relative_anchor="end",
            original=expr,
        )

    # 2. "first N seconds/minutes"
    m = _FIRST_RE.search(expr)
    if m:
        value_s = float(m.group("value")) * _unit_to_seconds(m.group("unit"))
        return ParsedTime(
            value_us=int(value_s * MICROSECONDS_PER_SECOND),
            is_relative=True,
            relative_anchor="start",
            original=expr,
        )

    # 3. H:MM:SS or M:SS
    m = _COLON_RE.search(expr)
    if m:
        hours = int(m.group("hours") or 0)
        minutes = int(m.group("minutes"))
        seconds = int(m.group("seconds"))
        total_s = hours * 3600 + minutes * 60 + seconds
        return ParsedTime(
            value_us=total_s * MICROSECONDS_PER_SECOND,
            is_relative=False, relative_anchor=None,
            original=expr,
        )

    # 4. Natural language "a minute twenty" / "two minutes thirty"
    nat = _parse_natural_minutes(expr)
    if nat is not None:
        return nat

    # 5. "N seconds" / "N minutes"
    m = _UNIT_RE.search(expr)
    if m:
        value_s = float(m.group("value")) * _unit_to_seconds(m.group("unit"))
        return ParsedTime(
            value_us=int(value_s * MICROSECONDS_PER_SECOND),
            is_relative=False, relative_anchor=None,
            original=expr,
        )

    raise TimeParseError(f"Cannot parse time expression: {expr!r}")


def _parse_natural_minutes(expr: str) -> Optional[ParsedTime]:
    """
    Parse "a minute twenty", "two minutes thirty seconds", etc.
    Returns None if pattern doesn't match.

    "a minute twenty"      -> 60 + 20 = 80 seconds
    "two minutes thirty"   -> 120 + 30 = 150 seconds
    "one minute"           -> 60 seconds

    The trailing number (twenty/thirty/20/30) represents seconds;
    the unit word ("seconds") is optional.
    """
    # Match: <count_word_or_digit> minute(s) [<extra_digit_or_word> [seconds?]]
    pattern = re.compile(
        r"(?P<count>[a-z]+|\d+)\s+minute(?:s)?"
        r"(?:\s+(?:and\s+)?(?P<extra>[a-z]+|\d+)(?:\s+s(?:ec(?:ond)?s?)?)?)?",
        re.IGNORECASE,
    )
    m = pattern.search(expr)
    if not m:
        return None
    count_str = m.group("count").lower()
    count = _WORD_TO_INT.get(count_str)
    if count is None:
        try:
            count = int(count_str)
        except ValueError:
            return None

    extra_str = (m.group("extra") or "").lower()
    if extra_str:
        extra = _WORD_TO_INT.get(extra_str)
        if extra is None:
            try:
                extra = int(extra_str)
            except ValueError:
                extra = 0
    else:
        extra = 0

    total_s = count * 60 + extra
    return ParsedTime(
        value_us=total_s * MICROSECONDS_PER_SECOND,
        is_relative=False, relative_anchor=None,
        original=expr,
    )


def extract_time_expressions(text: str) -> list:
    """
    Extract all time expressions from a longer instruction string.
    Returns a list of (span_start, span_end, ParsedTime) tuples.
    Used by the NLU layer to pull times out of natural language.
    """
    # We try all patterns and collect non-overlapping matches.
    # Priority: last/first > colon > natural > unit
    results = []
    used_spans = set()

    def add_if_free(start, end, pt):
        for (s, e) in used_spans:
            if start < e and end > s:
                return False
        used_spans.add((start, end))
        results.append((start, end, pt))
        return True

    for m in _LAST_RE.finditer(text):
        value_s = float(m.group("value")) * _unit_to_seconds(m.group("unit"))
        pt = ParsedTime(
            value_us=int(value_s * MICROSECONDS_PER_SECOND),
            is_relative=True, relative_anchor="end", original=m.group(0),
        )
        add_if_free(m.start(), m.end(), pt)

    for m in _FIRST_RE.finditer(text):
        value_s = float(m.group("value")) * _unit_to_seconds(m.group("unit"))
        pt = ParsedTime(
            value_us=int(value_s * MICROSECONDS_PER_SECOND),
            is_relative=True, relative_anchor="start", original=m.group(0),
        )
        add_if_free(m.start(), m.end(), pt)

    for m in _COLON_RE.finditer(text):
        hours = int(m.group("hours") or 0)
        minutes = int(m.group("minutes"))
        seconds = int(m.group("seconds"))
        total_s = hours * 3600 + minutes * 60 + seconds
        pt = ParsedTime(
            value_us=total_s * MICROSECONDS_PER_SECOND,
            is_relative=False, relative_anchor=None, original=m.group(0),
        )
        add_if_free(m.start(), m.end(), pt)

    for m in _UNIT_RE.finditer(text):
        value_s = float(m.group("value")) * _unit_to_seconds(m.group("unit"))
        pt = ParsedTime(
            value_us=int(value_s * MICROSECONDS_PER_SECOND),
            is_relative=False, relative_anchor=None, original=m.group(0),
        )
        add_if_free(m.start(), m.end(), pt)

    results.sort(key=lambda x: x[0])
    return results
