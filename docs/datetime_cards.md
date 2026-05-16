# Date and Time Answer Cards

Inline answer cards for date and time queries. Computed locally using Python
stdlib — no external service required. Results appear above BM25 search results
and are also injected into `ai_context` so the LLM summary can reference them.

---

## Supported Query Patterns

| Pattern | Example | Answer |
|---|---|---|
| today's date / what day is today | `what's today's date` | Monday, 5 May 2025 |
| current date variants | `today's date`, `what is today's date`, `current date` | same |
| what time is it | `what time is it` | 2:30 PM BST |
| what day was `<date>` | `what day of the week was 1 January 1970` | Thursday |
| how many days until `<date>` | `how many days until christmas` | 234 days |
| how many days since `<date>` | `how many days since 1 january 2020` | 1950 days |
| what week number is it | `what week number is it` | Week 18 of 2025 |
| is `<year>` a leap year | `is 2024 a leap year` | Yes, 2024 is a leap year. |

Detection is case-insensitive. Queries that do not match any pattern pass
through to BM25 normally — the date card is never shown for general queries.

---

## NTP Configuration

By default the service uses the system clock (`datetime.now().astimezone()`).

Set `NTP_SERVER` in `.env` to sync with an NTP host before computing answers:

```env
NTP_SERVER=pool.ntp.org
```

If `ntplib` is not installed or the NTP request fails (timeout, network error),
the service falls back to the system clock and logs a `WARNING`. No card is
suppressed as a result of an NTP failure.

`ntplib` is an optional dependency. Install it with:

```bash
pip install ntplib
```

---

## Timezone Handling

All times are displayed in the **local timezone** of the server process. The
timezone abbreviation (e.g. `BST`, `UTC`, `EST`) is appended to time answers.

For `what day was <date>` and `how many days until/since <date>` queries, the
calculation is always relative to today's local date, not UTC.

---

## Named Dates

The following named dates are resolved without requiring `python-dateutil`:

| Name | Resolves to |
|---|---|
| `christmas` | 25 December (next occurrence) |
| `new year` | 1 January (next year) |
| `new year's day` | 1 January (this year) |
| `halloween` | 31 October |
| `valentine's day` | 14 February |
| `independence day` / `july 4th` | 4 July |

For all other date strings, `python-dateutil` is required. It is listed in
`requirements.txt` and will be present in any standard install.

---

## `ai_context` Injection

When a date card is shown, the answer is prepended to `ai_context` as a plain
string (e.g. `"Today's Date: Monday, 5 May 2025"`) so the LLM summary can
reference it without needing to parse HTML.

---

## Known Limitations

- Relative expressions like "next Tuesday", "in two weeks", or "last month"
  are not supported — `python-dateutil` requires an explicit date string.
- "Thanksgiving" is not in the named-date table because it falls on different
  dates in the US (4th Thursday of November) and Canada (2nd Monday of October).
- The service cannot answer questions requiring knowledge of future events
  (e.g. "when is Easter 2026") beyond fixed-calendar holidays.
