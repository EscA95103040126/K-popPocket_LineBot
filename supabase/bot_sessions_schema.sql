-- Short-lived conversation state for the LINE bot (src/bot/sessions.py):
-- bias radar quiz progress and the AI curator's follow-up context.
-- Run this in the Supabase SQL editor; until then the bot keeps sessions in memory only
-- and /health reports session_store.ok = false.

create table if not exists bot_sessions (
  namespace text not null,
  session_key text not null,
  payload jsonb not null,
  expires_at timestamptz not null,
  updated_at timestamptz not null default now(),
  primary key (namespace, session_key)
);

create index if not exists idx_bot_sessions_expires_at
  on bot_sessions (expires_at);

-- Expired rows are never read, but they stay until removed. To clean them up on a
-- schedule, enable the pg_cron extension and run:
--   select cron.schedule('purge-bot-sessions', '0 * * * *',
--     $$delete from bot_sessions where expires_at < now()$$);
