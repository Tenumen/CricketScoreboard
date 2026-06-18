#!/bin/bash
# mail_logs.sh -- triggered by the admin-console "Email match logs" button.
#
# Spawned detached by debug_server.cpp. Runs the Python mailer, which reuses the
# shutdown mailer's encrypted credential (CREDENTIALS_DIRECTORY is set for the
# whole scoreboard24 unit and inherited here). Fire-and-forget: the email
# arriving is the confirmation. Never blocks; never exits non-zero in a way that
# matters (the parent does not wait on it).

set -u

logger -t scoreboard24-maillogs "admin-console email-logs triggered"

exec /usr/bin/python3 /home/tenumen/scoreboard24/scripts/mail_logs.py
