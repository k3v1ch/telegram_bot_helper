# CLAUDE.md

Project guidance for Claude Code working in this repo.

## Communication

Общайся с пользователем на русском языке. Код, идентификаторы, имена коммитов и технические артефакты — на английском.

## Project

Multi-user Telegram digest bot. A user authorizes their personal Telegram account through the bot; a Telethon "userbot" then reads messages from that account's chats while a `python-telegram-bot` bot delivers analyzed digests and real-time alerts to a destination of the user's choice. PostgreSQL is the single source of truth — every user, their Telethon session string, and their per-chat config live in the DB. Multiple users can coexist; their data is isolated.

## Architecture

- **Telethon userbot** (one client per authorized user, all driven by `bot/userbot/manager.py`) — reads source chats, never sends from itself except for forwarding pinned messages.
- **python-telegram-bot** — handles `/start`, inline-menu callbacks, and all outbound digest / alert / error messages.
- **Groq API** (`bot/analyzer.py`) — multi-stage filtering and summarization. Optional per-chat `custom_prompt` overrides the default stage-3 system prompt.
- **APScheduler** (`bot/scheduler.py::DigestScheduler`) — owns the digest pipeline for both scheduled and on-demand runs.
- **PostgreSQL** via SQLAlchemy 2.0 async + asyncpg — users, sessions, chats, digests, daily_stats, pinned_messages.
- Everything runs in a single asyncio event loop.

## File structure

```
bot/
  main.py                 # entry point: logging, legacy-env migration, app wiring, polling
  config.py               # global env vars (BOT_TOKEN, ADMIN_USER_ID, GROQ_API_KEY,
                          #   DATABASE_URL, TELEGRAM_API_ID, TELEGRAM_API_HASH)
  analyzer.py             # Groq pipeline (init(api_key) + analyze(...) -> tuple)
  sender.py               # send_digest / send_empty_notice / send_error
  scheduler.py            # DigestScheduler + parse_chat_topic util + scheduler singleton
  keyboards.py            # inline + reply keyboard builders
  states.py               # ConversationHandler state constants
  db/
    __init__.py
    models.py             # SQLAlchemy 2.0 declarative models
    database.py           # async engine, async_sessionmaker, init_db, get_session
    crud.py               # async CRUD: users / sessions / chats / digests / stats / pinned
  userbot/
    __init__.py           # singleton slot: `manager`
    manager.py            # UserbotManager: per-user Telethon clients + keep_alive
    reader.py             # fetch_messages (returns messages + pinned info), fetch_pinned*
    alerter.py            # register_alert(client, chat, bot, dest_chat_id, dest_topic_id)
  handlers/
    __init__.py
    start.py              # /start, /menu, reply-keyboard router, check_blocked decorator
    auth.py               # AUTH_PHONE / AUTH_CODE / AUTH_PASSWORD conversation
    chats.py              # add/edit/delete chats + per-chat menu callbacks
    digest.py             # digest_run/1h/5h/12h/24h/7d -> scheduler.run_digest
    search.py             # SEARCH_QUERY conversation over crud.search_digests
    admin.py              # ADMIN_USER_ID-only: users list, block, restart, etc.
    stats.py              # per-user stats panel from main menu
```

Legacy single-user modules (`digest_bot.py`, `digest_store.py`, `state.py`, `stats.py`, `pinned.py`, `health.py`, `atomic_io.py`, plus the old top-level `reader.py` / `alerter.py`) are no longer imported anywhere. Safe to delete in a future cleanup.

## Singletons

- `bot.userbot.manager: UserbotManager | None` — populated by `main.py` before the bot starts; handlers reach Telethon clients through it.
- `bot.scheduler.scheduler: DigestScheduler | None` — populated by `main.py` after Application is built; handlers call `scheduler.run_digest`, `add_chat_job`, etc.

Handlers and other modules read singletons via the module attribute (`bot.userbot.manager`, `bot.scheduler.scheduler`) rather than `from … import manager`, so they see the populated value at call time.

## Configuration

`.env` (see `.env.example`) — only global values:

| Var | Purpose |
|---|---|
| `BOT_TOKEN` | python-telegram-bot token from @BotFather |
| `ADMIN_USER_ID` | Telegram numeric ID with admin-panel access |
| `GROQ_API_KEY` | Groq API key |
| `POSTGRES_PASSWORD` | DB password (referenced from docker-compose) |
| `DATABASE_URL` | `postgresql+asyncpg://digest:…@postgres:5432/digest_bot` |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Shared Telethon app credentials for all users |

Per-user/per-chat settings (phone, source, dest, schedule, lookback, alerts toggle, custom prompt) live in the DB exclusively.

### Personal chat vs group topic dest format

`Chat.source` is always `chat_id:topic_id` — userbot reads a specific group topic.

`Chat.dest` accepts two forms (handled by `scheduler.parse_chat_topic`):

- `-1003332852289:220` → group + topic; messages are sent with `message_thread_id=220`.
- `635544292` → personal chat / DM; `topic_id` is `None`, messages are sent without `message_thread_id`.

`sender.py` and `alerter.py` and pinned forwarding all accept `dest_topic_id: int | None` and pass `message_thread_id=dest_topic_id or None`.

## Database schema

PostgreSQL 16. All timestamps stored UTC (naive `TIMESTAMP`), displayed in MSK.

**users** — `user_id` BIGINT PK, `username` VARCHAR(255), `first_name` VARCHAR(255), `is_blocked` BOOL, `is_active` BOOL, `created_at`, `last_active`.

**user_sessions** (1:1 with users) — `user_id` BIGINT PK FK→users, `phone` VARCHAR(50), `session_string` TEXT, `is_authorized` BOOL, `authorized_at`, `created_at`.

**chats** — `id` SERIAL PK, `user_id` BIGINT FK→users, `name`, `source` ("chat_id:topic_id"), `dest` ("chat_id:topic_id" or "chat_id"), `custom_prompt` TEXT, `schedule_time` "HH:MM" MSK, `lookback_hours`, `is_active`, `alerts_enabled`, `created_at`.

**digests** — `id` SERIAL PK, `chat_id` FK→chats, `user_id` FK→users, `period` ("24h", "7d", …), `raw_text` TEXT, `message_count`, `s1_count`, `s2_count`, `created_at`.

**daily_stats** — `id` SERIAL PK, `chat_id` FK→chats, `date` DATE, `message_count`, UNIQUE(chat_id, date).

**pinned_messages** — `chat_id` INTEGER PK FK→chats, `text` TEXT, `updated_at`.

## Flows

### Registration

User runs `/start`. `handlers/start.start_command` does `crud.get_user` → `crud.create_user` if absent, refuses if `is_blocked`, replies with welcome + main reply-keyboard (admin row added if `user_id == ADMIN_USER_ID`).

### Telethon auth

Reply-keyboard "📱 Аккаунт" → inline "➕ Подключить аккаунт" → `ConversationHandler` in `handlers/auth.py`:

1. `AUTH_PHONE` — `manager.authorize_new(user_id, phone)` returns a `phone_code_hash`, stashed in `context.user_data`.
2. `AUTH_CODE` — `manager.confirm_code(user_id, phone, code, hash)`. On `SessionPasswordNeededError` the conversation transitions to:
3. `AUTH_PASSWORD` — `manager.confirm_code(..., password=…)`.

On success `UserbotManager` writes `session_string` and `is_authorized=true` to DB and moves the Telethon client from `_pending` to `_clients`.

### Add chat

Inline "💬 Мои чаты" → "➕ Добавить чат" → `ADD_CHAT_NAME → SOURCE → DEST → TIME → HOURS → PROMPT`. `SOURCE_RE` enforces `chat_id:topic_id`; `DEST_RE` accepts that or a bare numeric `user_id` (DM). On finalize: `crud.create_chat` then `scheduler.add_chat_job(chat)` registers a daily cron and a Monday-weekly cron at the chat's `schedule_time` MSK.

### Digest pipeline

`scheduler.DigestScheduler.run_digest(chat_id, lookback_hours)` is the single entry point for both manual buttons (`handlers/digest.py`) and cron-triggered runs.

1. Load chat + user from DB. If chat missing → `remove_chat_jobs` and return (handles deleted-while-scheduled case). Skip if inactive / user blocked.
2. Parse `chat.source` and `chat.dest` (latter may yield `topic_id=None` for DMs).
3. `_resolve_client(chat, dest…)`: try `manager.get_client`; if not connected, attempt `manager.start_client(user_id)` once. On failure send a user-visible error to `dest` and bail — never crash the scheduler.
4. `reader.fetch_messages(client, source, topic, lookback, previous_pinned)` → `(messages, pinned_changed, pinned_text)`. `FloodWaitError` triggers a one-shot retry after `e.seconds`.
5. If `pinned_changed`: bot sends "📌 Закреп обновлён • {name}" header, userbot tries to forward the pinned message (fallback to plain text), `crud.upsert_pinned`.
6. If no messages: `sender.send_empty_notice` + `crud.upsert_daily_stats`.
7. `analyzer.analyze(messages, custom_prompt=chat.custom_prompt, weekly=lookback≥168)` → `(digest_text, s2_count)`. 429/503/rate/unavailable responses from Groq retry once after `RETRY_DELAY`.
8. `crud.get_stats_yesterday` → `sender.send_digest(...)` with `start_time`/`end_time` derived from `messages[0]['time']` / `messages[-1]['time']`.
9. `crud.save_digest` + `crud.upsert_daily_stats`.

### Realtime alerts

After `manager.start_all()`, `main._register_alerters` iterates `crud.get_all_active_chats`, and for each with `alerts_enabled=True` calls `alerter.register_alert(client, chat, bot, dest_chat_id, dest_topic_id)`. Telethon `events.NewMessage` filter scopes events to `chat.source`'s chat+topic. Per-`chat_id` debounce of 10 minutes per (sender, keyword).

### Keep-alive

`UserbotManager.keep_alive()` is launched as a background task in `main.py` after polling starts. Every 5 minutes it iterates `_clients`; for any client whose `is_connected()` is False it calls `stop_client` then `start_client(user_id)` — same path used by login, so it picks up the live session string from the DB.

### Stats

Reply-keyboard "📊 Статистика" → `handlers/stats.stats_show`. Computes from DB: chat count + active, total digests, digests in the last 7 days, last digest timestamp in MSK. Inline "← Назад" deletes the stats message.

### Admin

`handlers/admin.py` is gated by `admin_only`. Pagination (10 users / page), per-user detail (block toggle stops their clients + jobs), global stats, restart-all (`manager.stop_all` + `start_all`).

## Error handling

- `Application.add_error_handler` (in `main.py`) is the universal fallback — logs the traceback, shows "❌ Произошла ошибка. Попробуйте позже." to the user, DMs the admin a short repr.
- DB writes go through `get_session()` which auto-commits / rolls back. CRUD callers do not catch SQLAlchemy errors; the error handler swallows them with a user-visible message.
- Telethon `FloodWaitError` is caught in `scheduler.run_digest` for `fetch_messages`, sleeps the requested seconds, retries once.
- Groq 429 / 503 / "rate" / "unavailable" responses are caught in `analyzer.py` at both Stage 2 and Stage 3, retried after `RETRY_DELAY = 30s`.
- Userbot disconnect during a scheduled run is recovered by `_resolve_client` calling `manager.start_client` once before bailing out with a user-visible error.

## Legacy-env migration

`main._migrate_legacy_env(admin_user_id)` runs once on startup. If the legacy env vars `TELEGRAM_PHONE`, `SOURCE`, `DEST`, `LOOKBACK_HOURS`, `DIGEST_TIME` are present **and** the admin has no chats yet, it creates the admin User row (if missing) and one Chat row from those vars, logging "Migrated existing config to DB". Telethon session migration is not automatic — the admin must run `/start` and re-authorize through the bot.

## Logging

`setup_logging` (in `main.py`) writes to both stdout and `/app/logs/digest.log` via `RotatingFileHandler` (5 MB × 3 files). docker-compose mounts `./logs` into the container; `docker compose logs digest` shows the stdout stream.

## Docker setup

`docker-compose.yml`:

- `postgres` service: `postgres:16-alpine` with `pg_isready` healthcheck and named volume `postgres_data`.
- `digest` service: built from local Dockerfile (`python:3.11-slim`), `depends_on: postgres: service_healthy`, mounts `./logs:/app/logs`, runs `python -m bot.main` as ENTRYPOINT.

First run: `cp .env.example .env`, fill the values, `docker compose up -d`, then DM the bot `/start`.

## Conventions

- Python 3.11+, `async`/`await` throughout. No blocking calls in async paths.
- SQLAlchemy 2.0 style (`Mapped[...]`, `mapped_column`, `select(...)`).
- DB access only through `bot/db/crud.py`; handlers and scheduler take/get an `AsyncSession`, never raw SQL.
- All user-facing times in MSK (UTC+3). Scheduler `CronTrigger` is constructed with `timezone=MSK`. Bot/reader/alerter format times as `"HH:MM МСК"`.
- Russian UI strings; English code, identifiers, comments, commit messages.
