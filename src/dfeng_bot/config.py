"""Typed runtime configuration loaded from environment variables.

The :class:`Config` dataclass is the single source of truth for every tunable
in the bot. It is built once at startup via :func:`Config.from_env` and then
passed into the handler registration functions, so future tickets read settings
from here instead of touching ``os.environ`` directly.

Conventions for later tickets:
    * Add new settings as typed dataclass fields with sane defaults.
    * Document the matching env key in ``.env.example``.
    * Never put secrets in logs (see ``logging_setup.py``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

try:
    # Optional: load a local .env when present. Safe no-op in production where
    # python-dotenv may not be installed or no .env exists.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a dev convenience only
    pass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


# --- env parsing helpers -----------------------------------------------------


def _get_str(key: str, default: Optional[str] = None, *, required: bool = False) -> str:
    value = os.environ.get(key, default)
    if required and (value is None or value == ""):
        raise ConfigError(f"Missing required environment variable: {key}")
    return value if value is not None else ""


def _get_int(key: str, default: Optional[int] = None, *, required: bool = False) -> int:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        if required:
            raise ConfigError(f"Missing required environment variable: {key}")
        return default if default is not None else 0
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {key} must be an integer, got {raw!r}") from exc


def _get_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_list(key: str, default: Optional[list[int]] = None) -> list[int]:
    raw = os.environ.get(key, "")
    if not raw.strip():
        return list(default) if default else []
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError as exc:
            raise ConfigError(f"Environment variable {key} contains a non-integer: {part!r}") from exc
    return result


def _get_str_list(key: str, default: Optional[list[str]] = None) -> list[str]:
    raw = os.environ.get(key, "")
    if not raw.strip():
        return list(default) if default else []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _load_spam_rules_yaml() -> dict:
    """Load ``config/spam-rules.yaml`` if present and PyYAML is installed.

    Returns the parsed mapping, or ``{}`` when the file is absent or PyYAML is
    not installed. PyYAML is lazily imported here so the module stays import-clean
    and adds no hard dependency (the committed file is ``spam-rules.example.yaml``;
    the real ``spam-rules.yaml`` is gitignored and optional). Env vars remain the
    primary config path; YAML is a convenience for managing long rule lists.
    """

    path = os.environ.get("DFENG_SPAM_RULES_FILE", "config/spam-rules.yaml")
    if not path or not os.path.exists(path):
        return {}
    try:
        import yaml  # lazy: optional dependency, not in requirements.txt
    except Exception:  # pragma: no cover - PyYAML simply not installed
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:  # pragma: no cover - surface malformed rules clearly
        raise ConfigError(f"Failed to parse spam rules file {path!r}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _spam_list(yaml_rules: dict, yaml_key: str, env_key: str) -> list[str]:
    """Resolve a spam rule list: YAML value wins, else env (comma-separated)."""
    value = yaml_rules.get(yaml_key)
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return _get_str_list(env_key, [])


# --- structured sub-configs --------------------------------------------------


@dataclass(frozen=True)
class Topics:
    """The six community forum topics (``message_thread_id`` values)."""

    welcome: int
    general: int
    qualification: int
    support: int
    events: int
    announcements: int

    def all_ids(self) -> list[int]:
        return [
            self.welcome,
            self.general,
            self.qualification,
            self.support,
            self.events,
            self.announcements,
        ]


@dataclass(frozen=True)
class SheetsConfig:
    """Google Sheets target. Unused in VOL-197; wired up by later tickets."""

    workbook_id: str
    tab_name: str
    credentials_path: str


@dataclass(frozen=True)
class InviteLinks:
    """Named invite-link strings, one per link-based entry source (VOL-202).

    Each holds the full ``https://t.me/+...`` invite link created via the Bot API
    (``createChatInviteLink``) for that source. ``salesperson`` and
    ``website placeholder`` are NOT link-tracked (see ``services/entry_source.py``
    and ``docs/entry-links.md``), so they have no field here. Empty when unset —
    the resolver falls back to the documented default. The canonical link ->
    source mapping lives in ``services/entry_source.py``; these fields just expose
    the configured strings for logging / tooling (e.g. the QR script).
    """

    showroom_qr: str = ""
    roadshow_qr: str = ""
    event_qr: str = ""
    linktree: str = ""

    def as_mapping(self) -> dict[str, str]:
        """Return ``invite_link -> source_id`` for the configured (non-empty) links."""
        pairs = {
            self.showroom_qr: "showroom QR",
            self.roadshow_qr: "roadshow QR",
            self.event_qr: "event QR",
            self.linktree: "Linktree",
        }
        return {link: source for link, source in pairs.items() if link}


@dataclass(frozen=True)
class RateLimits:
    """Per-user flood-control thresholds + chosen action (VOL-210).

    Counting is PER USER across the WHOLE supergroup (all forum topics combined),
    not per-topic — see ``handlers/flood_control.py``. ``max_messages`` /
    ``window_seconds`` define the trip rate (default > 8 msgs / 10s). ``action``
    selects the escalating response when the rate is exceeded:

        * ``"warn"``   — log + reply a warning in-thread (no removal/mute).
        * ``"mute"``   — log + temporary, time-bounded, REVERSIBLE mute via
                          ``restrict_chat_member(until_date=...)`` so it auto-expires.
        * ``"delete"`` — log + remove the offending (latest) message only.
        * ``"mute_delete"`` — delete the message AND apply the temporary mute.

    ``mute_seconds`` bounds the mute (auto-expiring). ``exempt_admins`` keeps
    admins/moderators clear by default. Defaults are deliberately lenient so
    normal active conversation never trips it (see module docstring rationale).
    """

    max_messages: int
    window_seconds: int
    action: str = "mute"
    mute_seconds: int = 600
    exempt_admins: bool = True


@dataclass(frozen=True)
class SpamSettings:
    """Anti-spam settings (VOL-208).

    Rule lists default to empty here; the anti-spam handler
    (``handlers/antispam.py``) substitutes its own built-in DEFAULT_* lists when a
    field is empty, so a deployment only needs to set the keys it wants to
    override. Lists are populated from env (comma-separated) and/or an optional
    ``config/spam-rules.yaml`` (loaded by :func:`_load_spam_rules_yaml`); the YAML
    file, when present, takes precedence over the env defaults below.
    """

    block_links: bool
    exempt_admins: bool = True
    allowed_domains: list[str] = field(default_factory=list)
    crypto_keywords: list[str] = field(default_factory=list)
    ad_keywords: list[str] = field(default_factory=list)
    shortener_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    blocked_tlds: list[str] = field(default_factory=list)
    repeat_count: int = 3
    repeat_window_seconds: int = 60
    # Escalation: temporarily restrict a user after this many removed messages in
    # one process lifetime (0 = delete + log only; no restrict).
    restrict_after: int = 0
    restrict_seconds: int = 3600


@dataclass(frozen=True)
class FeatureFlags:
    """Toggles so subsystems can ship dark and be enabled per environment."""

    welcome: bool
    qualification: bool
    sheets: bool
    antispam: bool
    flood_control: bool
    support_redirect: bool


@dataclass(frozen=True)
class WebhookConfig:
    """Webhook runtime settings (only used when run_mode == 'webhook')."""

    url: str
    listen: str
    port: int
    secret_token: str


@dataclass(frozen=True)
class Config:
    """Top-level immutable runtime configuration."""

    # Core
    bot_token: str
    group_id: int

    # Structured sub-configs
    topics: Topics
    sheets: SheetsConfig
    invite_links: InviteLinks
    admin_ids: list[int]
    trust_threshold: int
    rate_limits: RateLimits
    spam: SpamSettings
    features: FeatureFlags

    # Runtime
    run_mode: str  # "polling" | "webhook"
    webhook: WebhookConfig

    # Logging
    log_level: str
    log_format: str  # "kv" | "json"

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from the process environment, applying defaults."""

        run_mode = _get_str("DFENG_RUN_MODE", "polling").strip().lower()
        if run_mode not in {"polling", "webhook"}:
            raise ConfigError(
                f"DFENG_RUN_MODE must be 'polling' or 'webhook', got {run_mode!r}"
            )

        log_format = _get_str("DFENG_LOG_FORMAT", "kv").strip().lower()
        if log_format not in {"kv", "json"}:
            raise ConfigError("DFENG_LOG_FORMAT must be 'kv' or 'json'")

        return cls(
            bot_token=_get_str("TELEGRAM_BOT_TOKEN", required=True),
            group_id=_get_int("DFENG_GROUP_ID", required=True),
            topics=Topics(
                welcome=_get_int("DFENG_TOPIC_WELCOME", 0),
                general=_get_int("DFENG_TOPIC_GENERAL", 0),
                qualification=_get_int("DFENG_TOPIC_QUALIFICATION", 0),
                support=_get_int("DFENG_TOPIC_SUPPORT", 0),
                events=_get_int("DFENG_TOPIC_EVENTS", 0),
                announcements=_get_int("DFENG_TOPIC_ANNOUNCEMENTS", 0),
            ),
            sheets=SheetsConfig(
                workbook_id=_get_str("DFENG_SHEETS_WORKBOOK_ID", ""),
                tab_name=_get_str("DFENG_SHEETS_TAB_NAME", "Members"),
                credentials_path=_get_str("GOOGLE_APPLICATION_CREDENTIALS", ""),
            ),
            invite_links=InviteLinks(
                showroom_qr=_get_str("DFENG_INVITE_LINK_SHOWROOM", ""),
                roadshow_qr=_get_str("DFENG_INVITE_LINK_ROADSHOW", ""),
                event_qr=_get_str("DFENG_INVITE_LINK_EVENT", ""),
                linktree=_get_str("DFENG_INVITE_LINK_LINKTREE", ""),
            ),
            admin_ids=_get_int_list("DFENG_ADMIN_IDS", []),
            trust_threshold=_get_int("DFENG_TRUST_THRESHOLD", 3),
            rate_limits=RateLimits(
                max_messages=_get_int("DFENG_RATE_LIMIT_MESSAGES", 8),
                window_seconds=_get_int("DFENG_RATE_LIMIT_WINDOW_SECONDS", 10),
                action=_get_str("DFENG_RATE_LIMIT_ACTION", "mute").strip().lower(),
                mute_seconds=_get_int("DFENG_RATE_LIMIT_MUTE_SECONDS", 600),
                exempt_admins=_get_bool("DFENG_RATE_LIMIT_EXEMPT_ADMINS", True),
            ),
            spam=cls._build_spam(),
            features=FeatureFlags(
                welcome=_get_bool("DFENG_FEATURE_WELCOME", True),
                qualification=_get_bool("DFENG_FEATURE_QUALIFICATION", True),
                sheets=_get_bool("DFENG_FEATURE_SHEETS", False),
                antispam=_get_bool("DFENG_FEATURE_ANTISPAM", False),
                flood_control=_get_bool("DFENG_FEATURE_FLOOD_CONTROL", False),
                support_redirect=_get_bool("DFENG_FEATURE_SUPPORT_REDIRECT", True),
            ),
            run_mode=run_mode,
            webhook=WebhookConfig(
                url=_get_str("DFENG_WEBHOOK_URL", ""),
                listen=_get_str("DFENG_WEBHOOK_LISTEN", "0.0.0.0"),
                port=_get_int("DFENG_WEBHOOK_PORT", 8443),
                secret_token=_get_str("DFENG_WEBHOOK_SECRET_TOKEN", ""),
            ),
            log_level=_get_str("DFENG_LOG_LEVEL", "INFO").upper(),
            log_format=log_format,
        )

    @staticmethod
    def _build_spam() -> "SpamSettings":
        """Assemble :class:`SpamSettings` from env + optional spam-rules.yaml.

        Rule lists resolve as: ``config/spam-rules.yaml`` value (if present) >
        env var (comma-separated) > empty (handler falls back to its DEFAULT_*).
        Scalars come from env. Keeps all spam config plumbing in one place.
        """
        y = _load_spam_rules_yaml()
        return SpamSettings(
            block_links=_get_bool("DFENG_SPAM_BLOCK_LINKS", True),
            exempt_admins=_get_bool("DFENG_SPAM_EXEMPT_ADMINS", True),
            allowed_domains=_spam_list(y, "allowed_domains", "DFENG_SPAM_ALLOWED_DOMAINS"),
            crypto_keywords=_spam_list(y, "crypto_keywords", "DFENG_SPAM_CRYPTO_KEYWORDS"),
            ad_keywords=_spam_list(y, "ad_keywords", "DFENG_SPAM_AD_KEYWORDS"),
            shortener_domains=_spam_list(y, "shortener_domains", "DFENG_SPAM_SHORTENER_DOMAINS"),
            blocked_domains=_spam_list(y, "blocked_domains", "DFENG_SPAM_BLOCKED_DOMAINS"),
            blocked_tlds=_spam_list(y, "blocked_tlds", "DFENG_SPAM_BLOCKED_TLDS"),
            repeat_count=int(y.get("repeat_count", _get_int("DFENG_SPAM_REPEAT_COUNT", 3))),
            repeat_window_seconds=int(
                y.get("repeat_window_seconds", _get_int("DFENG_SPAM_REPEAT_WINDOW_SECONDS", 60))
            ),
            restrict_after=int(y.get("restrict_after", _get_int("DFENG_SPAM_RESTRICT_AFTER", 0))),
            restrict_seconds=int(
                y.get("restrict_seconds", _get_int("DFENG_SPAM_RESTRICT_SECONDS", 3600))
            ),
        )

    # --- convenience ---------------------------------------------------------

    def is_admin(self, telegram_id: Optional[int]) -> bool:
        return telegram_id is not None and telegram_id in self.admin_ids

    def safe_summary(self) -> dict[str, object]:
        """Loggable view of config with secrets redacted."""
        return {
            "group_id": self.group_id,
            "run_mode": self.run_mode,
            "topics": self.topics.all_ids(),
            "admin_count": len(self.admin_ids),
            # Count of configured named invite links only — never log the link
            # strings themselves (they are join-grant secrets).
            "invite_links_configured": len(self.invite_links.as_mapping()),
            "trust_threshold": self.trust_threshold,
            "features": {
                "welcome": self.features.welcome,
                "qualification": self.features.qualification,
                "sheets": self.features.sheets,
                "antispam": self.features.antispam,
                "flood_control": self.features.flood_control,
                "support_redirect": self.features.support_redirect,
            },
            "log_level": self.log_level,
            "log_format": self.log_format,
        }
