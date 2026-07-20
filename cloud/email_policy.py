"""Email hygiene for sign-up: block disposable domains, normalize aliases.

Two abuse vectors this closes, now that the free plan is open to email (not
just Google) accounts:
  * temp-mail domains → free-minute farms (blocklist below).
  * provider aliases (gmail dots / +tags) → one address becomes infinite
    accounts → normalized to a single canonical form.
"""
import os

_DOMAINS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "disposable_domains.txt")

# Providers where a "+tag" suffix and (for Google) dots are ignored by the
# mail server, so foo+1@ and f.oo@ all deliver to the same inbox.
_DOT_INSENSITIVE = {"gmail.com", "googlemail.com"}
_PLUS_ALIASING = _DOT_INSENSITIVE | {
    "outlook.com", "hotmail.com", "live.com", "icloud.com", "me.com",
    "fastmail.com", "protonmail.com", "proton.me", "yahoo.com",
}


def _load_disposable() -> set:
    domains = set()
    try:
        with open(_DOMAINS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    domains.add(line)
    except FileNotFoundError:
        pass
    return domains


_DISPOSABLE = _load_disposable()


def is_disposable(email: str) -> bool:
    """True if the address's domain is a known disposable/temp-mail provider."""
    domain = (email or "").rsplit("@", 1)[-1].strip().lower()
    return domain in _DISPOSABLE


def normalize_email(email: str) -> str:
    """Canonical form used as the account key.

    Lowercases; strips a +tag from providers that ignore it; strips dots from
    the Gmail local part. Non-aliasing providers keep their local part intact
    so we never merge two genuinely different addresses.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if domain in _PLUS_ALIASING and "+" in local:
        local = local.split("+", 1)[0]
    if domain in _DOT_INSENSITIVE:
        local = local.replace(".", "")
    return f"{local}@{domain}"


def disposable_count() -> int:
    return len(_DISPOSABLE)
