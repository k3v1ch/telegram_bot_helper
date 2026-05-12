# CLAUDE.md

Project guidance for Claude Code working in this repo.

## Communication

Общайся с пользователем на русском языке. Код, идентификаторы, имена коммитов и технические артефакты — на английском.

## Project

Telegram Digest Bot. A userbot (Telethon) reads messages from source chats; a bot (python-telegram-bot) analyzes them via Groq API, sends scheduled digests and real-time alerts, and exposes an inline-menu management interface.

Originally a single-user, single-chat tool driven by env vars. Currently being refactored into a multi-user / multi-chat service backed by PostgreSQL — each user authorizes their own Telethon session and configures their own source/destination chats.

## Architecture

- **Telethon userbot** — reads SOURCE chats, never sends. Per-user `session_string` is stored in DB.
- **python-telegram-bot** — sends digests/alerts, handles commands and inline menus.
- **Groq API** — multi-stage filtering + summarization pipeline (`bot/analyzer.py`).
- **APScheduler** — schedules per-chat digest jobs.
- **PostgreSQL (asyncpg)** — single source of truth: users, sessions, chats, digests, stats, pinned messages.
- All components run in one process via `asyncio.gather`.

## File structure

```
bot/
  main.py                 # entry point, orchestrates bot + userbot + scheduler
  config.py               # global env vars (BOT_TOKEN, ADMIN_USER_ID, GROQ_API_KEY, DATABASE_URL, TELEGRAM_API_ID, TELEGRAM_API_HASH)
  analyzer.py             # Groq pipeline (stage 1/2/2.5/3 filtering and summarization)
  sender.py               # formats and dispatches digests, empty notices, error messages
  scheduler.py            # APScheduler setup, per-chat job registration
  keyboards.py            # inline keyboard builders
  states.py               # FSM state constants
  db/
    __init__.py
    models.py             # SQLAlchemy 2.0 declarative models (async)
    database.py           # async engine, async_sessionmaker, init_db, get_session
    crud.py               # async CRUD for users / sessions / chats / digests / stats / pinned
  userbot/
    __init__.py
    manager.py            # per-user Telethon client lifecycle
    reader.py             # message fetching (stage 1 filtering)
    alerter.py            # real-time alert handler
  handlers/
    __init__.py
    start.py              # /start, /menu, user registration
    auth.py               # Telethon login flow (phone, code, 2FA)
    chats.py              # add/list/edit/delete chats
    digest.py             # on-demand digest commands
    admin.py              # admin-only commands (block users, stats)
    search.py             # archive search
```

The legacy single-user modules (`digest_bot.py`, `digest_store.py`, `state.py`, `stats.py`, `pinned.py`, `health.py`, `atomic_io.py`, plus the original top-level `reader.py` / `alerter.py`) remain untouched while the refactor is in progress. They are unused by the new pipeline and can be removed in a follow-up cleanup.

## Pipeline flow

`DigestScheduler` (in `bot/scheduler.py`) is the single owner of the full pipeline for both scheduled and on-demand digests. `handlers/digest.py` just resolves the chat and calls `scheduler.run_digest(chat_id, hours)`.

`run_digest` steps:
1. Load `Chat` and `User` from DB; bail if missing / inactive / blocked.
2. `manager.get_client(chat.user_id)` — Telethon client for that user.
3. Parse `chat.source` / `chat.dest` → `(chat_id, topic_id)`.
4. `reader.fetch_messages(...)` returns `(messages, pinned_changed, pinned_text)`; previous pinned text comes from `crud.get_pinned`.
5. If pinned changed: send "📌 Закреп обновлён" header via bot, forward pinned via userbot client (fallback to text on permission errors), `crud.upsert_pinned`.
6. If no messages → `sender.send_empty_notice` + `crud.upsert_daily_stats`, done.
7. `analyzer.analyze(messages, custom_prompt=chat.custom_prompt, weekly=...)` → `(digest_text, s2_count)`.
8. `crud.get_stats_yesterday`, then `sender.send_digest` with full header.
9. `crud.save_digest` + `crud.upsert_daily_stats`.

`analyzer.init(api_key)` must be called once at startup (done in `main.py`).

## Realtime alerts

`alerter.register_alert(client, chat, bot, dest_chat_id, dest_topic_id)` attaches a Telethon `NewMessage` event handler to the user's client. `main.py` registers an alerter for every active chat that has `alerts_enabled=True` after `manager.start_all()` completes.

## Keep-alive

`UserbotManager.keep_alive()` is a coroutine launched from `main.py` after polling starts. Every 5 minutes it reconnects any Telethon client whose `is_connected()` returned False, and drops it from `_clients` if reconnect leaves the session unauthorized.

## Database schema

PostgreSQL 16, SQLAlchemy 2.0 async, asyncpg driver.

**users** — Telegram users authorized to use the bot
- `user_id` BIGINT PK
- `username` VARCHAR(255) NULL
- `first_name` VARCHAR(255) NULL
- `is_blocked` BOOL DEFAULT false
- `is_active` BOOL DEFAULT true
- `created_at` TIMESTAMP DEFAULT now()
- `last_active` TIMESTAMP NULL

**user_sessions** — Telethon session per user (1:1 with users)
- `user_id` BIGINT PK → users(user_id) ON DELETE CASCADE
- `phone` VARCHAR(50) NULL
- `session_string` TEXT NULL
- `is_authorized` BOOL DEFAULT false
- `authorized_at` TIMESTAMP NULL
- `created_at` TIMESTAMP DEFAULT now()

**chats** — per-user source→dest digest configurations
- `id` SERIAL PK
- `user_id` BIGINT → users(user_id) ON DELETE CASCADE
- `name` VARCHAR(255)
- `source` VARCHAR(100)
- `dest` VARCHAR(100)
- `custom_prompt` TEXT NULL
- `schedule_time` VARCHAR(10) DEFAULT '05:00'
- `lookback_hours` INTEGER DEFAULT 24
- `is_active` BOOL DEFAULT true
- `alerts_enabled` BOOL DEFAULT true
- `created_at` TIMESTAMP DEFAULT now()

**digests** — every generated digest, queryable for search
- `id` SERIAL PK
- `chat_id` INTEGER → chats(id) ON DELETE CASCADE
- `user_id` BIGINT → users(user_id) ON DELETE CASCADE
- `period` VARCHAR(10) — `24h`, `7d`, `1h`, etc.
- `raw_text` TEXT
- `message_count` INTEGER DEFAULT 0
- `s1_count` INTEGER DEFAULT 0
- `s2_count` INTEGER DEFAULT 0
- `created_at` TIMESTAMP DEFAULT now()

**daily_stats** — message count per chat per day
- `id` SERIAL PK
- `chat_id` INTEGER → chats(id) ON DELETE CASCADE
- `date` DATE
- `message_count` INTEGER DEFAULT 0
- UNIQUE(chat_id, date)

**pinned_messages** — last seen pinned-message text per chat
- `chat_id` INTEGER PK → chats(id) ON DELETE CASCADE
- `text` TEXT NULL
- `updated_at` TIMESTAMP DEFAULT now()

## Configuration

`.env` (see `.env.example`):
- `BOT_TOKEN` — from @BotFather
- `ADMIN_USER_ID` — your Telegram numeric ID (full bot admin)
- `GROQ_API_KEY` — from console.groq.com
- `POSTGRES_PASSWORD` — DB password (used by docker-compose)
- `DATABASE_URL` — e.g. `postgresql+asyncpg://digest:password@postgres:5432/digest_bot`
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — shared Telegram app credentials used for all users' Telethon sessions

Per-user/per-chat settings (phone, source, dest, schedule, lookback, alerts, prompt) live in the DB, not in env vars.

## Running

```bash
cp .env.example .env  # fill in BOT_TOKEN, ADMIN_USER_ID, GROQ_API_KEY, POSTGRES_PASSWORD
docker compose up -d
```

The `postgres` service starts first (healthchecked via `pg_isready`); the `digest` service waits for it before starting.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Existing tests cover the legacy modules. New tests for the DB layer and refactored handlers will be added alongside their implementation.

## Conventions

- Python 3.11+. `async`/`await` throughout.
- SQLAlchemy 2.0 style (`Mapped[...]`, `mapped_column`, `select(...)` constructs).
- DB access only through `bot/db/crud.py`. Handlers and userbot code take an `AsyncSession`, never raw SQL.
- Sessions opened via `async with get_session() as session:` from `bot/db/database.py` — auto-commits on success, rolls back on exception.
- Russian-language UI strings (this is a Russian-speaking user base). Code, identifiers, comments — English.
