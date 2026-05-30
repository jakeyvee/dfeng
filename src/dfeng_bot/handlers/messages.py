"""Generic message handler with extension hooks.

VOL-197 scope: receive group messages and log structured context (including the
topic/thread id). This is the central place later content-moderation and
routing tickets plug into.

Extension points (ordered as they should run):
    1. anti-spam / link restriction (VOL anti-spam): inspect & optionally
       delete/restrict, return early if the message was actioned.
    2. flood control (VOL flood-control): per-user rate limiting.
    3. support redirection: nudge users who post in the wrong topic toward the
       support topic.
    4. qualification (VOL-204): advance an in-progress qualification flow.

To keep handlers composable, each subsystem should be its own coroutine that
returns whether it "consumed" the update; ``handle_message`` calls them in order.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..logging_setup import log_event
from . import onboarding, qualification, support_redirect
from .base import get_config, thread_id_of


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for non-command group messages.

    Currently logs and returns. Future tickets insert their checks below, each
    returning early if it fully handles the update.
    """

    message = update.effective_message
    if message is None:
        return

    config = get_config(context)

    # --- Anti-spam / flood control run in GROUP_PREFILTER (-1), not here ------
    # VOL-208 anti-spam (handlers/antispam.py) and the future VOL-209/VOL-210
    # link/flood guards are registered as prefilter handlers in
    # ``handlers/__init__.py`` so they run BEFORE this handler and consume spam
    # via ApplicationHandlerStop. By the time we reach here the message is not
    # spam, so the subsystems below can treat it as legitimate.

    # --- EXTENSION POINT: support redirection (VOL-207) ----------------------
    # Observer: nudges support-flavoured messages toward the Support topic but
    # does NOT consume the update — qualification + logging still run below.
    await support_redirect.maybe_redirect(update, context)

    # --- EXTENSION POINT: qualification flow (VOL-204) -----------------------
    # Text-answer fallback to the inline-button qualification flow. Only acts
    # when the user is mid-flow (state in user_data); otherwise it's a no-op and
    # normal chat falls through to logging below. Consumes the update when it
    # advanced the flow so we don't also log it as generic chatter.
    if config.features.qualification:
        if await qualification.advance(update, context):
            return

    # --- EXTENSION POINT: PDPA-gated optional profile capture (VOL-205) -------
    # Text-answer fallback for the phone/plate steps. Only acts when the user is
    # mid-capture (profile_state in user_data awaiting a typed field); otherwise
    # a no-op so normal chat falls through. Consumes the update when it advanced
    # the capture. Qualification's advance() runs first and they use disjoint
    # states, so at most one consumes any given message.
    if config.features.optional_capture:
        if await onboarding.advance(update, context):
            return

    log_event(
        "message_received",
        update,
        thread_id=thread_id_of(update),
        has_text=bool(message.text),
        outcome="logged",
    )


async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle inline-button callback queries.

    Stub for VOL-197. Welcome/qualification flows that use inline keyboards
    (button-based PDPA consent, qualification answers) dispatch here. Always
    answer the callback so the client stops showing a loading state.
    """

    query = update.callback_query
    if query is None:
        return
    # Always answer first so the client stops showing a loading spinner.
    await query.answer()

    # --- ROUTE: qualification callbacks (qual: namespace, VOL-204) -----------
    # Qualification owns the ``qual:`` callback-data namespace. Route those to it
    # and let any other/future callbacks fall through to generic logging. This
    # keeps the shared callback seam composable as more inline flows are added.
    config = get_config(context)
    if config.features.qualification and qualification.owns_callback(query.data):
        await qualification.handle_callback(update, context)
        return

    # --- ROUTE: PDPA / profile callbacks ("pdpa:" / "profile:" ns, VOL-205) ---
    # Optional-capture owns these namespaces (distinct from qualification's
    # "qual:"). Route them here and let any other callbacks fall through.
    if config.features.optional_capture and onboarding.owns_callback(query.data):
        await onboarding.handle_callback(update, context)
        return

    log_event("callback_query", update, data=query.data, outcome="ack_v1")
