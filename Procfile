# Procfile — simple-host / PaaS alternative (VOL-213) for the single long-poll bot.
# The platform injects config via its own env/secret manager (set the same keys
# as .env.production.example; NEVER commit real values). Run as ONE worker only —
# never run two pollers on the same TELEGRAM_BOT_TOKEN.
#
# Requires PYTHONPATH to include src/ (src layout). On most PaaS set a config var
# PYTHONPATH=src, or install the package (`pip install .`) so dfeng_bot resolves.
worker: python -m dfeng_bot.main
