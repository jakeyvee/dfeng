"""Build a real dfeng_bot.config.Config for tests without touching os.environ.

We construct the immutable Config dataclass directly with explicit feature flags
so each test controls exactly which subsystems are enabled. This exercises the
real Config type (and real is_admin) rather than a mock.
"""

from __future__ import annotations

from dfeng_bot.config import (
    Config,
    FeatureFlags,
    InviteLinks,
    LinkRestrictions,
    RateLimits,
    SheetsConfig,
    SpamSettings,
    Topics,
    WebhookConfig,
    WriteQueueConfig,
)


def make_config(
    *,
    admin_ids=None,
    support_topic: int = 50,
    features: dict | None = None,
    rate_limits: RateLimits | None = None,
    spam: SpamSettings | None = None,
    link_restrictions: LinkRestrictions | None = None,
) -> Config:
    """Construct a Config with sensible test defaults; override as needed."""

    flag_defaults = dict(
        welcome=True,
        qualification=True,
        optional_capture=True,
        sheets=False,
        antispam=False,
        flood_control=False,
        link_restrictions=False,
        support_redirect=True,
    )
    if features:
        flag_defaults.update(features)

    return Config(
        bot_token="TEST:fake-token",
        group_id=-100123,
        topics=Topics(
            announcements=70,
            box=10,
            model_007=30,
            vigo=60,
            general=20,
            support=support_topic,
        ),
        welcome_topic=0,
        sheets=SheetsConfig(workbook_id="", tab_name="Members", credentials_path=""),
        invite_links=InviteLinks(),
        admin_ids=list(admin_ids or []),
        trust_threshold=3,
        rate_limits=rate_limits
        or RateLimits(max_messages=8, window_seconds=10, action="mute"),
        spam=spam or SpamSettings(block_links=True),
        link_restrictions=link_restrictions or LinkRestrictions(),
        write_queue=WriteQueueConfig(),
        features=FeatureFlags(**flag_defaults),
        run_mode="polling",
        webhook=WebhookConfig(url="", listen="0.0.0.0", port=8443, secret_token=""),
        log_level="INFO",
        log_format="kv",
    )
