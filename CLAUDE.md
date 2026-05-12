# CLAUDE.md

Project guidance for Claude Code working in this repo.

## Communication

Общайся с пользователем на русском языке. Код, идентификаторы, имена коммитов и технические артефакты — на английском.

При любых изменениях в коде — обновляй этот CLAUDE.md и README.md, чтобы документация всегда соответствовала текущему состоянию проекта.

## Project

Multi-user, multi-account Telegram digest bot. Каждый пользователь может подключить НЕСКОЛЬКО Telegram-аккаунтов через бота. Под каждый аккаунт работает свой Telethon userbot — он читает сообщения из источников. `python-telegram-bot` отправляет дайджесты, алерты и предоставляет полностью **inline UI** (никаких reply-клавиатур). PostgreSQL — единственный источник правды: пользователи, их сессии, привязка чатов к сессиям, кастомные ключевые слова алертов.

## Architecture

- **Telethon userbot** (`bot/userbot/manager.py::UserbotManager`) — N клиентов на пользователя, ключ — `session_id` (SERIAL PK таблицы `user_sessions`). Читает source-чаты, форвардит закрепы.
- **python-telegram-bot** — inline-only UI: одно сообщение редактируется при навигации, все экраны через `InlineKeyboardMarkup`. Reply-клавиатур нет.
- **Groq API** (`bot/analyzer.py`) — три стадии (фильтр → сжатие → дайджест). Универсальный default prompt; опциональный per-chat `custom_prompt` переопределяет Stage 3.
- **APScheduler** (`bot/scheduler.py::DigestScheduler`) — daily + Monday weekly cron на каждый активный чат, plus on-demand `run_digest`.
- **PostgreSQL 16** через SQLAlchemy 2.0 async + asyncpg.
- Один asyncio event loop на всё.

## File structure

```
bot/
  main.py                 # entry point: logging, legacy-env migration, app wiring, polling
  config.py               # global env (BOT_TOKEN, ADMIN_USER_ID, GROQ_API_KEY,
                          #   DATABASE_URL, TELEGRAM_API_ID, TELEGRAM_API_HASH)
  analyzer.py             # Groq pipeline (init(api_key) + analyze(...) -> tuple)
  sender.py               # send_digest / send_empty_notice / send_error
  scheduler.py            # DigestScheduler + parse_chat_topic + scheduler singleton
  keyboards.py            # inline keyboard builders (no ReplyKeyboard anywhere)
  states.py               # ConversationHandler state constants
  db/
    models.py             # SQLAlchemy 2.0 models
    database.py           # async engine, init_db, get_session
    crud.py               # async CRUD: users / sessions / chats / digests / stats / pinned
  userbot/
    __init__.py           # singleton slot: `manager`
    manager.py            # UserbotManager keyed by session_id
    reader.py             # fetch_messages / fetch_pinned*
    alerter.py            # register_alert + parse_keywords + per-chat keywords
  handlers/
    start.py              # /start, /menu, gated open_chats/open_stats/open_admin callbacks
    auth.py               # AUTH_LABEL/PHONE/CODE/PASSWORD + rename conversation
    accounts.py           # accounts list / detail / revoke screens
    chats.py              # add/edit/delete/keywords + per-chat menu callbacks
    digest.py             # digest_run/1h/5h/12h/24h/7d -> scheduler.run_digest
    search.py             # SEARCH_QUERY over crud.search_digests
    admin.py              # ADMIN_USER_ID-only: users list, block, restart, etc.
    stats.py              # per-user stats screen (inline)
tests/
  test_*.py               # pytest suite (130+ unit tests)
```

Legacy single-user modules (`digest_bot.py`, `digest_store.py`, `state.py`, `stats.py`, `pinned.py`, `health.py`, `atomic_io.py`, top-level `reader.py` / `alerter.py`) больше не импортируются — оставлены ради старого тест-сьюта, можно удалить.

## Singletons

- `bot.userbot.manager: UserbotManager | None`
- `bot.scheduler.scheduler: DigestScheduler | None`

Обращаются к ним через атрибут модуля (`bot.userbot.manager`, `bot.scheduler.scheduler`), не через `from … import`.

## Configuration

`.env`:

| Var | Purpose |
|---|---|
| `BOT_TOKEN` | python-telegram-bot токен |
| `ADMIN_USER_ID` | Telegram numeric ID админа |
| `GROQ_API_KEY` | Groq API key |
| `POSTGRES_PASSWORD` | DB password |
| `DATABASE_URL` | `postgresql+asyncpg://digest:…@postgres:5432/digest_bot` |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Общие Telethon креды |

Всё user-specific / chat-specific — в БД.

### Source/dest формат

`Chat.source` — всегда `chat_id:topic_id`.
`Chat.dest` — либо `chat_id:topic_id` (топик группы), либо просто `user_id` (DM). Парсится через `scheduler.parse_chat_topic`.

## Database schema

PostgreSQL 16. Timestamps — UTC naive, в UI — МСК.

**users** — `user_id` BIGINT PK, username, first_name, is_blocked, is_active, created_at, last_active.

**user_sessions** — `id` SERIAL PK, `user_id` BIGINT FK→users, `phone`, `session_string`, `label` VARCHAR(100), `is_authorized`, `authorized_at`, `created_at`. UNIQUE(user_id, phone). У одного пользователя может быть N строк (multi-account).

**chats** — `id` SERIAL PK, `user_id` FK→users, `session_id` FK→user_sessions(id) ON DELETE SET NULL (nullable — после удаления аккаунта чат остаётся "осиротевшим"), `name`, `source`, `dest`, `custom_prompt` TEXT, `alert_keywords` TEXT (comma-separated, NULL → default keywords), `schedule_time`, `lookback_hours`, `is_active`, `alerts_enabled`, `created_at`.

**digests** — `id` SERIAL PK, `chat_id`, `user_id`, `period`, `raw_text`, `message_count`, `s1_count`, `s2_count`, `created_at`.

**daily_stats** — `id`, `chat_id`, `date`, `message_count`. UNIQUE(chat_id, date).

**pinned_messages** — `chat_id` PK FK→chats, `text`, `updated_at`.

## UI rules (inline-only)

- Все экраны через `InlineKeyboardMarkup`. `ReplyKeyboardMarkup` нигде не используется.
- Навигация — `edit_message_text` + `edit_message_reply_markup` на ОДНОМ сообщении. Никаких новых сообщений ради навигации.
- Callback data — `screen:param`, например `chat:42`, `account_open:7`, `digest_1h:42`, `chat_keywords:5`.
- На каждом экране есть `[← Назад]` к родителю.
- Максимальная глубина: 4 уровня.

### Gating

- Если у пользователя нет ни одного авторизованного `UserSession` — главное меню показывает только `[📱 Аккаунты]` (и `[👑 Админ]` если `ADMIN_USER_ID`).
- Прямой клик по `chats`/`stats` callback без аккаунта → popup-alert "⚠️ Сначала подключите аккаунт Telegram".
- Декоратор `bot.handlers.start.require_session` инкапсулирует эту проверку.

## Flows

### Registration (`/start`)

`handlers/start.start_command`: `get_user` → `create_user` если нет; refuse если `is_blocked`; редактирует/отправляет главное меню с учётом наличия авторизованных сессий и админ-прав.

### Multi-account auth (`AUTH_LABEL → PHONE → CODE → PASSWORD`)

1. `AUTH_LABEL` — пользователь вводит человекочитаемое название аккаунта (Основной, Рабочий).
2. `AUTH_PHONE` — `manager.authorize_new(user_id, phone, label)` создаёт строку `user_sessions`, возвращает `(session_id, phone_code_hash)`.
3. `AUTH_CODE` — `manager.confirm_code(session_id, phone, code, hash)`. На `SessionPasswordNeededError` → `AUTH_PASSWORD`.
4. `AUTH_PASSWORD` — `manager.confirm_code(session_id, ..., password=…)`.

На успехе `session_string` сохраняется, `is_authorized=True`, Telethon-клиент перемещается из `_pending` в `_clients[session_id]`.

Отмена в любой момент → `cancel_pending(session_id)` удаляет неавторизованную запись.

### Rename / Revoke account

- Кнопка ✏️ Переименовать → `EDIT_SESSION_LABEL` → `crud.update_session_label`.
- ❌ Удалить аккаунт → confirm → `manager.revoke(session_id)` (stop + delete row). Привязанные чаты получают `session_id=NULL`.

### Add chat (`ADD_CHAT_NAME → SESSION → SOURCE → DEST → TIME → HOURS → PROMPT`)

После ввода имени:
- Если у пользователя 1 авторизованная сессия — выбирается автоматически, шаг SESSION пропускается.
- Если N — показывается inline-выбор `session_choice(sessions)`, callback `add_session:{id}`.

Чат создаётся с `session_id` указывающим на выбранную сессию.

### Per-chat alert keywords

`Chat.alert_keywords` — comma-separated. NULL → `DEFAULT_KEYWORDS` из `bot/userbot/alerter.py`.

Экран `[🔔 Ключевые слова]` показывает текущий список, кнопка `[✏️ Изменить список]` → `EDIT_KEYWORDS` → `crud.update_chat(alert_keywords=...)`. Пустой ввод сбрасывает в NULL (= дефолтные).

### Digest pipeline (`DigestScheduler.run_digest`)

1. Load chat + user + (если был ранее) `pinned_messages`. Skip/cleanup на missing chat, inactive, blocked user.
2. Parse `source` и `dest` через `parse_chat_topic`.
3. `_resolve_client(chat, dest…)` — `manager.get_client(chat.session_id)`; при offline пытается `start_client(session_id)` один раз. На неудачу шлёт user-visible ошибку. Если `session_id is None` (осиротевший чат после удаления аккаунта) — шлёт соответствующую ошибку.
4. `reader.fetch_messages(...)` → `(messages, pinned_changed, pinned_text)`. `FloodWaitError` retry один раз.
5. Если pinned изменился — header через бота, forward через Telethon, `crud.upsert_pinned`.
6. Если сообщений нет — `send_empty_notice` + `upsert_daily_stats`.
7. `analyzer.analyze(messages, custom_prompt=chat.custom_prompt, weekly=lookback≥168)`. Groq 429/503/rate/unavailable retry через `RETRY_DELAY`.
8. `crud.get_stats_yesterday` → `sender.send_digest(...)`.
9. `crud.save_digest` + `crud.upsert_daily_stats`.

### Realtime alerts

После `manager.start_all()`, `main._register_alerters` для каждого `alerts_enabled` чата с привязанным `session_id`:
- `client = manager.get_client(chat.session_id)`
- `register_alert(client, chat, bot, dest_chat_id, dest_topic_id)`

`alerter._check_alert` использует `parse_keywords(chat.alert_keywords)` — comma-separated либо `DEFAULT_KEYWORDS`. IP-патерн добавляет матчинг по `keyword` рядом с IP. Per-chat дебаунс 10 мин по (sender, keyword).

### Keep-alive

`UserbotManager.keep_alive()` каждые 5 минут перебирает `_clients` (ключ `session_id`). Disconnected → `stop_client + start_client` (свежий `session_string` из БД).

## Default prompts

`bot/analyzer.py`:
- `FILTER_PROMPT` — Stage 2, generic фильтр полезных сообщений.
- `FINAL_PROMPT` — Stage 3, generic дайджест с резюме + 🔴 Важное / 🟡 Обновления / 🔵 Полезно.
- `WEEKLY_PROMPT` — Stage 3 для 168h, лимит 10 пунктов.
- `COMPRESS_PROMPT` — Stage 2.5 для weekly с >8000 chars.

`chat.custom_prompt` если задан — заменяет Stage 3 prompt.

## Error handling

- `Application.add_error_handler` (в `main.py`) — лог + user-popup + DM админу.
- DB через `get_session()` с auto-commit/rollback.
- Telethon `FloodWaitError` — retry в `scheduler.run_digest`.
- Groq 429/503/rate/unavailable — retry в analyzer на Stage 2 и Stage 3.
- Telethon disconnect — `_resolve_client` пытается `start_client(session_id)` один раз.

## Legacy-env migration

`main._migrate_legacy_env(admin_user_id)` запускается один раз. Если есть `TELEGRAM_PHONE`/`SOURCE`/`DEST`/`LOOKBACK_HOURS`/`DIGEST_TIME` и у админа нет чатов — создаёт User + Chat (session_id=None). Telethon-сессию переподключить вручную через `/start`.

## Logging

`setup_logging` пишет в stdout и `/app/logs/digest.log` через `RotatingFileHandler` (5 МБ × 3). Docker mountит `./logs`. Если /app/logs недоступен (локальный запуск тестов) — только stdout.

## Docker

- `postgres:16-alpine` + `pg_isready` healthcheck + named volume.
- `digest` сервис на python:3.11-slim, `depends_on: postgres: service_healthy`, mountит `./logs`.
- Первый запуск: `cp .env.example .env`, fill, `docker compose up -d`, в боте `/start` и Telethon auth.

## Tests

Запуск: `pip install -r requirements-dev.txt && pytest`. 130+ юнит-тестов, не трогают внешних сервисов.

## Conventions

- Python 3.11+, async/await.
- SQLAlchemy 2.0 (`Mapped[...]`, `mapped_column`, `select(...)`).
- DB-доступ только через `bot/db/crud.py`.
- Время UI — МСК. Scheduler `CronTrigger` с `timezone=MSK`.
- Русский UI; английские code/identifiers/commit messages.
- При каждом изменении кода — обновлять CLAUDE.md и README.md.
