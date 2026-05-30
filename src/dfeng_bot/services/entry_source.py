"""Entry-source resolution — map a join's invite link to a canonical source.

VOL-202 scope. The member workbook (``services/schema.py`` -> ``ENTRY_SOURCES``)
records *which channel* brought a user in. Telegram cannot tell us this directly:
group invite links are NOT bot deep links, and a ``/start`` parameter is NOT
available after a private-group join. The reliable mechanism is:

    1. Create one **named** invite link per entry source via the Bot API
       (``createChatInviteLink``, optionally ``creates_join_request=true`` for
       invite-only approval). See ``docs/entry-links.md`` for the operator steps.
    2. Telegram then echoes the exact ``invite_link`` string back on the join
       update (``chat_member`` / ``chat_join_request``).
    3. We map that link string back to its canonical source id here.

This module owns the mapping and the resolver. It is import-clean and has no
Telegram or Sheets dependency — the handler layer (``handlers/membership.py``,
``handlers/join_request.py``) calls :func:`resolve_entry_source` and stashes the
result for the persistence layer (VOL-205) to write into the "Entry source"
column.

Source identifiers
------------------
The canonical ids MUST match :data:`services.schema.ENTRY_SOURCES` exactly:

    salesperson, showroom QR, roadshow QR, Linktree, event QR, website placeholder

Fallback / default
------------------
If a join exposes no invite link, or an *unknown* link (e.g. the user was added
by someone sharing the primary link, or via a one-off link not in the registry),
we cannot know the true channel. We default to :data:`DEFAULT_ENTRY_SOURCE`
(``"salesperson"``) because in practice the most common un-tracked path is a
salesperson adding/inviting a customer directly. This default is DOCUMENTED in
``docs/entry-links.md``; operators who prefer an explicit "unknown" bucket can
set every link env and treat the default as the catch-all. Onboarding (VOL-204)
may optionally confirm the source with the member to correct a defaulted value.
"""

from __future__ import annotations

import os
from typing import Optional

from .schema import ENTRY_SOURCES

# The env var that holds the named invite link for each source. The KEY is the
# canonical source id (must be in ENTRY_SOURCES); the VALUE is the env var name.
# Link-based sources only: "salesperson" and "website placeholder" are NOT
# tracked by a group invite link (a salesperson adds people directly; the
# website is an external placeholder URL), so they have no env here — see the
# module docstring and docs/entry-links.md.
ENV_BY_SOURCE: dict[str, str] = {
    "showroom QR": "DFENG_INVITE_LINK_SHOWROOM",
    "roadshow QR": "DFENG_INVITE_LINK_ROADSHOW",
    "event QR": "DFENG_INVITE_LINK_EVENT",
    "Linktree": "DFENG_INVITE_LINK_LINKTREE",
}

# The documented fallback used when no invite link is present or the link is not
# in the registry. MUST be a member of ENTRY_SOURCES.
DEFAULT_ENTRY_SOURCE: str = "salesperson"

# Sanity: every key above and the default must be valid schema sources. Fail
# loudly at import if someone drifts the ids out of sync with the schema.
_unknown = set(ENV_BY_SOURCE) - set(ENTRY_SOURCES)
if _unknown:  # pragma: no cover - guards against developer error
    raise RuntimeError(f"entry_source ids not in schema.ENTRY_SOURCES: {sorted(_unknown)}")
if DEFAULT_ENTRY_SOURCE not in ENTRY_SOURCES:  # pragma: no cover
    raise RuntimeError(f"DEFAULT_ENTRY_SOURCE {DEFAULT_ENTRY_SOURCE!r} not in ENTRY_SOURCES")


def load_link_mapping(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Build the ``invite_link_string -> source_id`` lookup from the environment.

    Reads each ``DFENG_INVITE_LINK_*`` var. Empty / unset vars are skipped, so an
    operator can roll sources out incrementally. The returned dict is keyed by the
    full invite link string (e.g. ``"https://t.me/+abc123"``) for O(1) lookup.

    Args:
        env: Optional environment mapping (defaults to ``os.environ``). Injectable
            for tests so this stays free of global state.

    Returns:
        Mapping of invite link string -> canonical source id.
    """

    env = os.environ if env is None else env
    mapping: dict[str, str] = {}
    for source, var in ENV_BY_SOURCE.items():
        link = (env.get(var) or "").strip()
        if link:
            mapping[link] = source
    return mapping


def resolve_entry_source(
    invite_link: Optional[str],
    *,
    mapping: Optional[dict[str, str]] = None,
) -> str:
    """Resolve a join's ``invite_link`` to a canonical entry-source id.

    Args:
        invite_link: The ``invite_link`` string Telegram echoes on the join
            update (``chat_member.invite_link.invite_link`` /
            ``chat_join_request.invite_link.invite_link``). ``None`` when the join
            path exposes no link (added by a member, primary link, etc.).
        mapping: Optional precomputed ``link -> source`` map (see
            :func:`load_link_mapping`). Loaded from the environment when omitted.

    Returns:
        A source id from :data:`services.schema.ENTRY_SOURCES`. Falls back to
        :data:`DEFAULT_ENTRY_SOURCE` for missing/unknown links.

    Examples:
        >>> m = {"https://t.me/+show": "showroom QR", "https://t.me/+road": "roadshow QR"}
        >>> resolve_entry_source("https://t.me/+show", mapping=m)
        'showroom QR'
        >>> resolve_entry_source("https://t.me/+unknown", mapping=m)
        'salesperson'
        >>> resolve_entry_source(None, mapping=m)
        'salesperson'
    """

    if mapping is None:
        mapping = load_link_mapping()
    if not invite_link:
        return DEFAULT_ENTRY_SOURCE
    return mapping.get(invite_link.strip(), DEFAULT_ENTRY_SOURCE)
