"""Rules, text decoding and per-unit scanning for the sensitive-data scanner.

This module never calls git. scripts/scan_sensitive.py collects the units
and passes them here.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Sequence

RULE_IDS: tuple[str, ...] = (
    "home-path",
    "email",
    "ipv4",
    "token",
    "private-key",
    "secret-assignment",
    "uuid",
    "arabic-script",
    "deny",
)

EXCERPT_LIMIT = 60
MASK_LENGTH = 6
MASKED_RULES = frozenset({"token", "private-key", "secret-assignment"})
BINARY_PROBE_BYTES = 8000
UTF16_MAJORITY = 0.9
UTF16_NOISE = 0.1


@dataclass(frozen=True)
class Finding:
    location: str
    rule: str
    excerpt: str


class DenyFileError(ValueError):
    """An invalid regex in the deny file; line_no is 1-based."""

    def __init__(self, line_no: int, detail: str) -> None:
        super().__init__(f"invalid regex at line {line_no}: {detail}")
        self.line_no = line_no


@dataclass(frozen=True)
class _Matcher:
    rule: str
    regex: re.Pattern[str]
    allowed: Callable[[str], bool]


def _never(_matched: str) -> bool:
    return False


EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net")
NOREPLY_SUFFIX = "@users.noreply.github.com"
ANTHROPIC_NOREPLY = "noreply@anthropic.com"
ALLOWED_IPS = ("127.0.0.1", "0.0.0.0")
ALLOWED_IP_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.")
ALLOWED_UUID_PREFIX = "00000000-"
# SSH user of the hosting services in clone addresses (git@host:owner/repo.git).
# These are not mailboxes; any other git@ address stays a finding.
SSH_GIT_ADDRESSES = ("git@github.com", "git@gitlab.com", "git@bitbucket.org")


def _email_allowed(address: str) -> bool:
    lowered = address.lower()
    domain = lowered.rsplit("@", 1)[-1]
    return (
        domain in EXAMPLE_DOMAINS
        or lowered.endswith(NOREPLY_SUFFIX)
        or lowered == ANTHROPIC_NOREPLY
        or lowered in SSH_GIT_ADDRESSES
    )


def _ipv4_allowed(address: str) -> bool:
    return address in ALLOWED_IPS or address.startswith(ALLOWED_IP_PREFIXES)


def _uuid_allowed(value: str) -> bool:
    return value.lower().startswith(ALLOWED_UUID_PREFIX)


HOME_PATTERNS = (
    r"/home/[A-Za-z0-9._-]+",
    r"/Users/[A-Za-z0-9._-]+",
    r"(?i:[a-z]:\\Users\\)",
)
EMAIL_PATTERN = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
IPV4_PATTERN = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
PRIVATE_KEY_PATTERN = r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
UUID_PATTERN = (
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)

# Code point ranges as integers; the class is built with chr() so the source stays ASCII.
ARABIC_RANGES: tuple[tuple[int, int], ...] = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFC),
)
ARABIC_PATTERN = (
    "[" + "".join(chr(low) + "-" + chr(high) for low, high in ARABIC_RANGES) + "]"
)

TOKEN_LOOKBEHIND = r"(?<![A-Za-z0-9])"
TOKEN_PATTERNS = (
    TOKEN_LOOKBEHIND + r"sk-ant-[A-Za-z0-9_-]{10,}",
    TOKEN_LOOKBEHIND + r"sk-[A-Za-z0-9_-]{20,}",
    TOKEN_LOOKBEHIND + r"(?:sk|rk)_live_[A-Za-z0-9]{16,}",
    TOKEN_LOOKBEHIND + r"gh[pousr]_[A-Za-z0-9]{20,}",
    TOKEN_LOOKBEHIND + r"github_pat_[A-Za-z0-9_]{20,}",
    TOKEN_LOOKBEHIND + r"glpat-[A-Za-z0-9_-]{20,}",
    TOKEN_LOOKBEHIND + r"xox[abposr]-[A-Za-z0-9-]{10,}",
    TOKEN_LOOKBEHIND + r"AKIA[0-9A-Z]{16}",
    TOKEN_LOOKBEHIND + r"AIza[0-9A-Za-z_-]{35}",
    TOKEN_LOOKBEHIND + r"hf_[A-Za-z0-9]{30,}",
    TOKEN_LOOKBEHIND + r"npm_[A-Za-z0-9]{36}",
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
)

SECRET_PATTERN = (
    r"(?<![A-Za-z0-9])"
    r"(?P<key>[\x27\x22]?[A-Za-z0-9_.-]*"
    r"(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|access[_-]?key|private[_-]?key|auth[_-]?key)"
    r"[\x27\x22]?)"
    r"\s*[:=]\s*"
    r"(?:\x22(?P<dq>[^\x22\s]{12,})\x22"
    r"|\x27(?P<sq>[^\x27\s]{12,})\x27"
    r"|(?P<bare>[A-Za-z0-9_+/=.-]{16,})(?=$|[\s\x22\x27,;#)\]}]))"
)
SECRET_RE = re.compile(SECRET_PATTERN, re.IGNORECASE)
VARIABLE_REFERENCE = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$")
PLACEHOLDER = re.compile(r"^<[^>]*>$")
# An environment variable name as a quoted value: upper case words joined by underscores.
ENV_VAR_NAME = re.compile(r"^[A-Z]+(?:_[A-Z]+)+$")

UNICODE_ESCAPE = re.compile(r"\\u([0-9A-Fa-f]{4})")
LONG_UNICODE_ESCAPE = re.compile(r"\\U([0-9A-Fa-f]{8})")
HEX_REFERENCE = re.compile(r"&#[xX]([0-9A-Fa-f]{1,6});")
DECIMAL_REFERENCE = re.compile(r"&#([0-9]{1,7});")

BOM_CODECS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)
PRINTABLE_RUN = re.compile(rb"[\x09\x20-\x7e]{8,}")


def _build_matchers(
    rule: str,
    patterns: Iterable[str],
    allowed: Callable[[str], bool] = _never,
) -> tuple[_Matcher, ...]:
    return tuple(_Matcher(rule, re.compile(pattern), allowed) for pattern in patterns)


_MATCHERS: tuple[_Matcher, ...] = (
    *_build_matchers("home-path", HOME_PATTERNS),
    *_build_matchers("email", (EMAIL_PATTERN,), _email_allowed),
    *_build_matchers("ipv4", (IPV4_PATTERN,), _ipv4_allowed),
    *_build_matchers("token", TOKEN_PATTERNS),
    *_build_matchers("private-key", (PRIVATE_KEY_PATTERN,)),
    *_build_matchers("uuid", (UUID_PATTERN,), _uuid_allowed),
    *_build_matchers("arabic-script", (ARABIC_PATTERN,)),
)


def compile_deny(lines: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    """Compile deny-file lines; blank lines and # comments are skipped."""
    patterns: list[re.Pattern[str]] = []
    for number, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        try:
            patterns.append(re.compile(text, re.IGNORECASE))
        except re.error as exc:
            raise DenyFileError(number, str(exc)) from exc
    return tuple(patterns)


def _excerpt(matched: str, masked: bool) -> str:
    flat = matched.replace("\n", " ").replace("\r", " ")
    if masked:
        return flat[:MASK_LENGTH] + "..."
    return flat[:EXCERPT_LIMIT]


def _matcher_hits(matcher: _Matcher, view: str) -> Iterator[str]:
    for match in matcher.regex.finditer(view):
        matched = match.group(0)
        if matched and not matcher.allowed(matched):
            yield matched


def _is_bare_secret(value: str) -> bool:
    return any(ch.isdigit() for ch in value) and any(ch.isalpha() for ch in value)


def _secret_is_finding(match: re.Match[str]) -> bool:
    quoted = match.group("dq") or match.group("sq")
    if quoted is not None:
        return not (
            VARIABLE_REFERENCE.match(quoted)
            or PLACEHOLDER.match(quoted)
            or ENV_VAR_NAME.match(quoted)
        )
    return _is_bare_secret(match.group("bare") or "")


def _secret_hits(view: str) -> Iterator[str]:
    for match in SECRET_RE.finditer(view):
        if _secret_is_finding(match):
            yield match.group(0)


def _deny_matchers(deny: Sequence[re.Pattern[str]]) -> tuple[_Matcher, ...]:
    return tuple(_Matcher("deny", pattern, _never) for pattern in deny)


# Exact-match fingerprints for intentional fixtures: (path glob, rule, sha256 hex of the
# matched text). The table holds hashes only, so it does not contain the fixture values.
ALLOWED_FINDINGS: tuple[tuple[str, str, str], ...] = (
    # F-1: placeholder home path used in test fixtures
    (
        "tests/test_routing_audit.py",
        "home-path",
        "c033a7efb16d867f74dbb297fb4966466fe53c7e18b7a830755289ed9717bb8c",
    ),
    # F-2: fake key fixture on line 31
    (
        "tests/test_doctor.py",
        "secret-assignment",
        "317e54511dcd7cf17c2e75352938c6e0ef0ed5ee4209d26517ecf57658f94410",
    ),
)


def is_allowed_finding(path: str, rule: str, matched: str) -> bool:
    """True only when the path matches the glob, the rule is equal and the text hashes equal."""
    digest = hashlib.sha256(matched.encode("utf-8")).hexdigest()
    return any(
        fnmatch.fnmatchcase(path, glob) and rule == entry_rule and digest == entry_digest
        for glob, entry_rule, entry_digest in ALLOWED_FINDINGS
    )


def _fingerprinted(path: str | None, rule: str, matched: str) -> bool:
    return path is not None and is_allowed_finding(path, rule, matched)


def _view_findings(
    view: str, location: str, deny: Sequence[re.Pattern[str]], path: str | None = None
) -> list[Finding]:
    found = [
        Finding(location, matcher.rule, _excerpt(matched, matcher.rule in MASKED_RULES))
        for matcher in (*_MATCHERS, *_deny_matchers(deny))
        for matched in _matcher_hits(matcher, view)
        if not _fingerprinted(path, matcher.rule, matched)
    ]
    found.extend(
        Finding(location, "secret-assignment", _excerpt(matched, True))
        for matched in _secret_hits(view)
        if not _fingerprinted(path, "secret-assignment", matched)
    )
    return found


def _character(value: int) -> str | None:
    if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
        return None
    return chr(value)


def _replace_escape(match: re.Match[str], base: int) -> str:
    char = _character(int(match.group(1), base))
    return match.group(0) if char is None else char


def unescape(text: str) -> str:
    """Decode escapes in a copy of the text, in the order the plan fixes."""
    text = UNICODE_ESCAPE.sub(lambda m: _replace_escape(m, 16), text)
    text = LONG_UNICODE_ESCAPE.sub(lambda m: _replace_escape(m, 16), text)
    text = HEX_REFERENCE.sub(lambda m: _replace_escape(m, 16), text)
    text = DECIMAL_REFERENCE.sub(lambda m: _replace_escape(m, 10), text)
    text = text.replace("\\/", "/")
    return text.replace("\\\\", "\\")


def scan_unit(
    text: str,
    location: str,
    deny: Sequence[re.Pattern[str]],
    path: str | None = None,
) -> tuple[Finding, ...]:
    """Scan one unit (a content line, a path name or a metadata line) in both views.

    path is the file the unit belongs to, when known; it enables the fingerprint allowlist.
    """
    raw = _view_findings(text, location, deny, path)
    if "\\" not in text and "&#" not in text:
        return tuple(raw)
    raw_rules = {finding.rule for finding in raw}
    decoded = _view_findings(unescape(text), location, deny, path)
    kept = [finding for finding in decoded if finding.rule not in raw_rules]
    return tuple(raw + kept)


def scan_text(
    text: str,
    prefix: str,
    deny: Sequence[re.Pattern[str]],
    path: str | None = None,
) -> tuple[Finding, ...]:
    """Scan each line; locations are prefix:n, n 1-based."""
    found: list[Finding] = []
    for number, line in enumerate(text.split("\n"), start=1):
        found.extend(scan_unit(line, f"{prefix}:{number}", deny, path))
    return tuple(found)


def scan_content(
    data: bytes,
    prefix: str,
    deny: Sequence[re.Pattern[str]],
    path: str | None = None,
) -> tuple[Finding, ...]:
    """Decode bytes and scan them; binary content uses the :bytes location.

    path is the repository path of the content, when known (None: no fingerprint applies).
    """
    text, is_binary = decode_content(data)
    if not is_binary:
        return scan_text(text, prefix, deny, path)
    found: list[Finding] = []
    for run in text.split("\n"):
        found.extend(scan_unit(run, f"{prefix}:bytes", deny, path))
    return tuple(found)


def _utf16_codec(probe: bytes) -> str | None:
    if len(probe) < 2:
        return None
    odd = probe[1::2]
    even = probe[0::2]
    odd_nul = odd.count(0) / len(odd)
    even_nul = even.count(0) / len(even)
    if odd_nul >= UTF16_MAJORITY and even_nul < UTF16_NOISE:
        return "utf-16-le"
    if even_nul >= UTF16_MAJORITY and odd_nul < UTF16_NOISE:
        return "utf-16-be"
    return None


def decode_content(data: bytes) -> tuple[str, bool]:
    """Return (text, is_binary) for raw bytes, following the plan's decode order."""
    for bom, codec in BOM_CODECS:
        if data.startswith(bom):
            return data[len(bom):].decode(codec, "replace"), False
    probe = data[:BINARY_PROBE_BYTES]
    if b"\x00" not in probe:
        return data.decode("utf-8", "replace"), False
    codec = _utf16_codec(probe)
    if codec is not None:
        return data.decode(codec, "replace"), False
    runs = PRINTABLE_RUN.findall(data)
    return "\n".join(run.decode("ascii") for run in runs), True
