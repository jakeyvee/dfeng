#!/usr/bin/env python3
"""Generate QR-code PNGs for the entry-source named invite links (VOL-202).

Each link-based entry source (showroom QR, roadshow QR, event QR, and Linktree)
has a named Telegram invite link stored in a ``DFENG_INVITE_LINK_*`` env var
(see ``services/entry_source.py`` and ``docs/entry-links.md``). This script reads
those links from the environment and writes one scannable PNG per configured
source into ``assets/qr/``.

The generated PNGs are gitignored (they encode real, sensitive invite links);
only ``assets/qr/.gitkeep`` is committed. Print/laminate the PNGs for the
showroom, roadshows, and events.

Usage
-----
    # Populate the link env vars first (e.g. via .env or your shell), then:
    pip install "qrcode[pil]"            # one-time; also in requirements.txt
    python scripts/generate_qr.py        # writes assets/qr/<source>.png

    # Or point at a custom output dir:
    python scripts/generate_qr.py --out /tmp/qr

Notes
-----
* ``qrcode`` is imported lazily inside :func:`main` so this module compiles and
  imports without the optional dependency installed (matches project convention).
* Sources with an empty/unset link env var are skipped with a warning, so you can
  roll out QR codes incrementally.
* The minimum required surfaces (showroom QR, roadshow QR, event QR) all generate
  here; Linktree is generated too (its QR points at the same named link, handy if
  you also want a scannable Linktree-channel code).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import-clean: only stdlib + the project's own (dependency-free) mapping module
# at module scope. qrcode is imported lazily in main().
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dfeng_bot.services.entry_source import ENV_BY_SOURCE, load_link_mapping  # noqa: E402

DEFAULT_OUT_DIR = _REPO_ROOT / "assets" / "qr"


def _slug(source_id: str) -> str:
    """Filesystem-safe filename stem for a source id (e.g. 'showroom QR' -> 'showroom_qr')."""
    return source_id.strip().lower().replace(" ", "_")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for PNGs (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--invite-links",
        action="store_true",
        help="Force legacy group-invite-link QR mode instead of bot deep links.",
    )
    args = parser.parse_args(argv)

    import os

    # Deep-link mode (recommended, Option A): when DFENG_BOT_USERNAME is set, the
    # QR encodes a BOT deep link t.me/<bot>?start=<source>. The user lands in the
    # bot DM, onboards privately, and is granted a single-use group invite on
    # completion (see docs/entry-links.md, handlers/dm_onboarding.py). These deep
    # links are PUBLIC (meant for signage), so printing them is fine.
    bot_username = os.environ.get("DFENG_BOT_USERNAME", "").lstrip("@").strip()
    if bot_username and not args.invite_links:
        try:
            import qrcode
        except ImportError:
            print('ERROR: install qrcode:  pip install "qrcode[pil]"', file=sys.stderr)
            return 2
        out_dir = args.out
        out_dir.mkdir(parents=True, exist_ok=True)
        generated = 0
        for token in ("showroom", "roadshow", "event", "linktree"):
            url = f"https://t.me/{bot_username}?start={token}"
            qrcode.make(url).save(out_dir / f"{token}.png")
            print(f"OK    {token} -> {out_dir / (token + '.png')}   ({url})")
            generated += 1
        print(f"Done: {generated} deep-link QR code(s) written to {out_dir}.")
        print("Put the matching link behind your Linktree button too:")
        print(f"  https://t.me/{bot_username}?start=linktree")
        return 0

    # Lazy import so the module is import-clean without the optional dep.
    try:
        import qrcode
    except ImportError:
        print(
            "ERROR: the 'qrcode' library is not installed.\n"
            "Install it with:  pip install \"qrcode[pil]\"",
            file=sys.stderr,
        )
        return 2

    mapping = load_link_mapping()  # link_string -> source_id
    # Invert to source_id -> link for stable, named output files.
    link_by_source = {source: link for link, source in mapping.items()}

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    for source, env_var in ENV_BY_SOURCE.items():
        link = link_by_source.get(source)
        if not link:
            print(f"SKIP  {source!r}: {env_var} is empty/unset.", file=sys.stderr)
            continue

        img = qrcode.make(link)
        dest = out_dir / f"{_slug(source)}.png"
        img.save(dest)
        # Do NOT print the link itself (sensitive join grant) — only the source.
        print(f"OK    {source!r} -> {dest}")
        generated += 1

    if generated == 0:
        print(
            "No QR codes generated. Set the DFENG_INVITE_LINK_* env vars first "
            "(see docs/entry-links.md).",
            file=sys.stderr,
        )
        return 1

    print(f"Done: {generated} QR code(s) written to {out_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
