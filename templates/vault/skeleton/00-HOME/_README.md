# 00-HOME

Identity and current focus. Small, frequently-updated notes that the session-start hook
injects into every Claude Code session (see templates/hooks/session_start_briefing.sh).

- `who-i-am.md`: distilled identity (role, context, stack, constants). Rendered once at
  install time from the interview, then updated by hand as things change.
- `current-focus.md`: the single current priority. Update whenever it changes; the
  briefing hook warns the agent if this note is more than 7 days old.
- `interaction-preferences.md` (optional): tone, language, format preferences for how AI
  should talk to the owner.

Keep these short. They are read on every session, so length here is a recurring token
cost, not a one-time cost.
