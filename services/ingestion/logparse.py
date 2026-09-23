"""Local log analysis: timestamps, severity, templates, grouping. No vectorization of raw lines."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

TS_PATTERNS = [
    (re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)(Z|[+-]\d{2}:?\d{2})?"), None),
    (re.compile(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})"), "%d/%m/%Y %H:%M:%S"),
    (re.compile(r"([A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2})"), "%b %d %H:%M:%S"),  # syslog, no year
]
SEV = re.compile(r"\b(TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|CRIT(?:ICAL)?|FATAL|PANIC|EMERG)\b", re.I)
SEV_NORM = {"WARNING": "WARN", "ERR": "ERROR", "CRITICAL": "CRITICAL", "CRIT": "CRITICAL", "PANIC": "FATAL", "EMERG": "FATAL"}
SECRETISH = re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|authorization)\s*[=:]\s*\S+|bearer\s+[a-z0-9._-]{8,}|sk-[a-z0-9_-]{16,}")


@dataclass
class LogEvent:
    line_no: int
    ts: str | None
    ts_has_tz: bool
    severity: str | None
    template: str
    message: str


def redact(line: str) -> str:
    return SECRETISH.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=<REDACTED>", line)


def template_of(msg: str) -> str:
    t = re.sub(r"0x[0-9a-fA-F]+", "<HEX>", msg)
    t = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<UUID>", t)
    t = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b", "<IP>", t)
    t = re.sub(r"\b\d+(?:\.\d+)?\b", "<N>", t)
    t = re.sub(r"'[^']*'|\"[^\"]*\"", "<STR>", t)
    return re.sub(r"\s+", " ", t).strip()[:300]


def parse_line(no: int, raw: str) -> LogEvent | None:
    line = redact(raw.rstrip("\r\n"))
    if not line.strip():
        return None
    ts, has_tz, rest = None, False, line
    for rx, fmt in TS_PATTERNS:
        m = rx.search(line)
        if m:
            try:
                if fmt is None:
                    ts = datetime.fromisoformat(m.group(1).replace(",", ".").replace(" ", "T")).isoformat()
                    has_tz = bool(m.group(2))
                    if has_tz:
                        ts += m.group(2) if ":" in m.group(2) or m.group(2) == "Z" else m.group(2)[:3] + ":" + m.group(2)[3:]
                else:
                    ts = datetime.strptime(m.group(1), fmt).isoformat()
                rest = line[m.end():]
            except ValueError:
                ts = None
            break
    sm = SEV.search(rest)
    sev = None
    if sm:
        s = sm.group(1).upper()
        sev = SEV_NORM.get(s, s)
        rest = rest[sm.end():]
    msg = rest.strip(" -:[]|")
    return LogEvent(no, ts, has_tz, sev, template_of(msg), msg[:1000])


def parse(text: str) -> list[LogEvent]:
    return [e for i, l in enumerate(text.splitlines(), start=1) if (e := parse_line(i, l))]


def summarize(events: list[dict], top: int = 5) -> dict:
    sev = Counter(e["severity"] or "UNKNOWN" for e in events)
    errs = [e for e in events if e["severity"] in ("ERROR", "CRITICAL", "FATAL")]
    groups = Counter(e["template"] for e in errs)
    tss = sorted(e["ts"] for e in events if e["ts"])
    examples = {}
    for e in errs:
        examples.setdefault(e["template"], e)
    return {
        "total_lines": len(events),
        "by_severity": dict(sev),
        "time_range": {"first": tss[0] if tss else None, "last": tss[-1] if tss else None,
                       "timezone_known": any(e["ts_has_tz"] for e in events)},
        "top_errors": [{"template": t, "count": c, "first_line": examples[t]["line_no"], "example": examples[t]["message"][:200]}
                       for t, c in groups.most_common(top)],
        "repeated_error_templates": sum(1 for c in groups.values() if c > 1),
    }


if __name__ == "__main__":  # self-check
    sample = ("2026-09-20 10:00:01 ERROR db timeout after 30 ms host 10.0.0.5\n"
              "2026-09-20 10:00:05 INFO login ok password=hunter2\n"
              "2026-09-20 10:01:01 ERROR db timeout after 31 ms host 10.0.0.6\n")
    ev = [e.__dict__ for e in parse(sample)]
    s = summarize(ev)
    assert s["top_errors"][0]["count"] == 2, s
    assert "hunter2" not in str(ev)
    assert s["time_range"]["first"].startswith("2026-09-20T10:00:01")
    print("logparse ok")
