"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Date and time answer card service. Detects calendar and time queries,
    computes answers using stdlib datetime and calendar, and returns structured
    card dicts for the results template. NTP sync is optional via the
    NTP_SERVER env var; falls back to system clock when absent or ntplib
    is unavailable.
"""
# Imports
import calendar
import logging
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

try:
    import ntplib as _ntplib
except ImportError:
    _ntplib = None

try:
    from dateutil import parser as _dateutil_parser
    from dateutil.relativedelta import relativedelta as _relativedelta
except ImportError:
    _dateutil_parser = None
    _relativedelta = None

# Globals
logger = logging.getLogger(__name__)

_NTP_SERVER = os.environ.get("NTP_SERVER", "")

# Detection regexes
_RE_TODAY = re.compile(
    r"(what'?s?\s+today'?s?\s+date|"
    r"what\s+(is\s+)?today'?s?\s+date|"
    r"what\s+day\s+is\s+(it\s+)?today|"
    r"today'?s?\s+date|"
    r"current\s+date)",
    re.IGNORECASE,
)
_RE_TIME = re.compile(
    r"what\s+time\s+is\s+it|current\s+time",
    re.IGNORECASE,
)
_RE_DAY_WAS = re.compile(
    r"what\s+day\s+(?:of\s+the\s+week\s+)?was\s+(.+)",
    re.IGNORECASE,
)
_RE_DAYS_UNTIL = re.compile(
    r"how\s+many\s+days?\s+(until|till|to|before|since|ago)\s+(.+)",
    re.IGNORECASE,
)
_RE_WEEK_NUM = re.compile(
    r"what\s+week\s+(?:number\s+(?:is\s+it|are\s+we\s+in)|is\s+it)|"
    r"week\s+number",
    re.IGNORECASE,
)
_RE_LEAP_YEAR = re.compile(
    r"is\s+(\d{4})\s+a\s+leap\s+year",
    re.IGNORECASE,
)

_NAMED_DATES = {
    "christmas":       lambda y: date(y, 12, 25),
    "new year":        lambda y: date(y + 1, 1, 1),
    "new year's":      lambda y: date(y + 1, 1, 1),
    "new year's day":  lambda y: date(y, 1, 1),
    "halloween":       lambda y: date(y, 10, 31),
    "valentine's day": lambda y: date(y, 2, 14),
    "independence day":lambda y: date(y, 7, 4),
    "july 4th":        lambda y: date(y, 7, 4),
    "july fourth":     lambda y: date(y, 7, 4),
}


# Functions
def get_current_time(ntp_server: Optional[str] = None) -> datetime:
    """
    Input: ntp_server — optional NTP host string
    Output: current datetime in local timezone
    Details:
        If ntp_server is set and ntplib is available, queries NTP for accurate
        UTC time then converts to local. Falls back to datetime.now() silently.
    """
    server = ntp_server or _NTP_SERVER
    if server and _ntplib:
        try:
            client = _ntplib.NTPClient()
            response = client.request(server, version=3)
            utc_dt = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
            return utc_dt.astimezone()
        except Exception:
            logger.warning("NTP request failed for %s; falling back to system clock", server)
    return datetime.now().astimezone()


def _parse_date_string(text: str) -> Optional[date]:
    """
    Input: text — human-readable date string
    Output: date object or None
    Details:
        Tries dateutil.parser.parse first; falls back to named date resolution.
        Strips trailing punctuation and noise words before parsing.
    """
    text = text.strip().rstrip("?.")

    # Named date shortcuts
    lower = text.lower()
    today = date.today()
    for name, fn in _NAMED_DATES.items():
        if lower == name or lower.startswith(name):
            target = fn(today.year)
            if target < today:
                target = fn(today.year + 1)
            return target

    if _dateutil_parser is None:
        return None

    try:
        parsed = _dateutil_parser.parse(text, dayfirst=False, default=datetime(today.year, 1, 1))
        return parsed.date()
    except Exception:
        logger.warning("dateutil could not parse date string: %s", text)
        return None


def detect_date_query(q: str) -> Optional[dict]:
    """
    Input: q — raw search query string
    Output: dict {intent, date, label} or None
    Details:
        Matches date/time query patterns and returns a structured query dict.
        Returns None when the query does not match any supported pattern.
    """
    q = q.strip()

    m = _RE_LEAP_YEAR.search(q)
    if m:
        return {"intent": "leap_year", "year": int(m.group(1)), "label": f"Leap year: {m.group(1)}"}

    if _RE_WEEK_NUM.search(q):
        return {"intent": "week_number", "date": None, "label": "Week number"}

    m = _RE_DAY_WAS.search(q)
    if m:
        target = _parse_date_string(m.group(1))
        if target:
            return {"intent": "day_was", "date": target, "label": f"Day of the week: {m.group(1).strip()}"}

    m = _RE_DAYS_UNTIL.search(q)
    if m:
        direction = m.group(1).lower()
        target = _parse_date_string(m.group(2))
        if target:
            past = direction in ("since", "ago")
            return {
                "intent": "days_since" if past else "days_until",
                "date": target,
                "label": f"Days {'since' if past else 'until'} {m.group(2).strip()}",
            }

    if _RE_TIME.search(q):
        return {"intent": "current_time", "date": None, "label": "Current time"}

    if _RE_TODAY.search(q):
        return {"intent": "today", "date": None, "label": "Today's date"}

    return None


def resolve_date_query(query: dict) -> dict:
    """
    Input: query — dict from detect_date_query
    Output: dict {label, body, source}
    Details:
        Computes the answer for the matched intent and returns a human-readable
        body string along with the label and source tag.
    """
    intent = query.get("intent")
    now = get_current_time()
    today = now.date()

    if intent == "today":
        body = now.strftime("%A, %-d %B %Y")
        return {"label": "Today's Date", "body": body, "source": "System clock"}

    if intent == "current_time":
        tz_name = now.strftime("%Z")
        body = now.strftime(f"%-I:%M %p {tz_name}")
        return {"label": "Current Time", "body": body, "source": "System clock"}

    if intent == "day_was":
        target: date = query["date"]
        day_name = target.strftime("%A")
        formatted = target.strftime("%-d %B %Y")
        body = f"{formatted} was a {day_name}."
        return {"label": query.get("label", "Day of the week"), "body": body, "source": "Python datetime"}

    if intent == "days_until":
        target: date = query["date"]
        delta = (target - today).days
        if delta < 0:
            body = f"{abs(delta)} days ago ({target.strftime('%-d %B %Y')})"
        elif delta == 0:
            body = f"Today! ({target.strftime('%-d %B %Y')})"
        else:
            body = f"{delta} days"
        return {"label": query.get("label", "Days until"), "body": body, "source": "Python datetime"}

    if intent == "days_since":
        target: date = query["date"]
        delta = (today - target).days
        if delta < 0:
            body = f"In {abs(delta)} days ({target.strftime('%-d %B %Y')})"
        elif delta == 0:
            body = f"Today! ({target.strftime('%-d %B %Y')})"
        else:
            body = f"{delta} days"
        return {"label": query.get("label", "Days since"), "body": body, "source": "Python datetime"}

    if intent == "week_number":
        week = today.isocalendar()[1]
        year = today.isocalendar()[0]
        body = f"Week {week} of {year}"
        return {"label": "Week Number", "body": body, "source": "Python datetime"}

    if intent == "leap_year":
        year = query.get("year", today.year)
        is_leap = calendar.isleap(year)
        body = f"Yes, {year} is a leap year." if is_leap else f"No, {year} is not a leap year."
        return {"label": f"Leap Year: {year}", "body": body, "source": "Python calendar"}

    return {"label": "Date", "body": "Unknown date query.", "source": "Python datetime"}


def build_datetime_card(q: str) -> tuple:
    """
    Input: q — raw search query string
    Output: (answer_card dict, ai_context str) or (None, None)
    Details:
        Entry point for the inline dispatcher. Detects, resolves, and returns
        a structured answer_card and ai_context string.
    """
    query = detect_date_query(q)
    if not query:
        return None, None

    try:
        result = resolve_date_query(query)
    except Exception:
        logger.warning("resolve_date_query failed for intent %s", query.get("intent"), exc_info=True)
        return None, None

    answer_card = {
        "type":   "datetime",
        "label":  result["label"],
        "body":   result["body"],
        "source": result["source"],
    }
    ai_context = f"{result['label']}: {result['body']}"
    return answer_card, ai_context


if __name__ == "__main__":
    pass
