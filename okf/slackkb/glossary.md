# SlackKB glossary

- note: one captured report. Fields: note_id, team_id, channel_id, user_id,
  text, severity, created_at (UTC ISO-8601), status.
- severity: LOW | MEDIUM | HIGH | CRITICAL. Default LOW.
- capture: receiving a /bnote command and persisting the note.
- route: post-capture processing (structure, store, escalate).
- thread: the Slack thread under the bot's confirmation; replies are
  questions.
