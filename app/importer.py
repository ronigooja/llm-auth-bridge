from dataclasses import dataclass
from urllib.parse import urlparse

@dataclass
class ImportRecord:
    username: str
    password: str
    totp: str
    mailbox_url: str | None = None

def parse_line(line: str) -> ImportRecord:
    fields = line.rstrip("\n").split("----")
    if len(fields) not in (3, 4) or any(not x for x in fields[:3]):
        raise ValueError("expected account----password----totp_secret[----mailbox_url]")
    mailbox = fields[3] if len(fields) == 4 else None
    if mailbox and urlparse(mailbox).scheme not in ("http", "https"):
        raise ValueError("mailbox_url must be an HTTP(S) URL")
    return ImportRecord(*fields[:3], mailbox)

def preview(text: str) -> list[dict]:
    seen = set(); result = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip(): continue
        try:
            r = parse_line(line)
            duplicate = r.username in seen
            seen.add(r.username)
            result.append({"line": number, "account": r.username, "valid": not duplicate, "duplicate": duplicate})
        except ValueError as exc:
            result.append({"line": number, "valid": False, "error": str(exc)})
    return result

