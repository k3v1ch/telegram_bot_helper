from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import Chat, UserSession

# --- Callback constants ----------------------------------------------------

CB_CANCEL = "cancel"
CB_BACK_MAIN = "back_main"
CB_NOOP = "noop"

CB_ACCOUNTS = "accounts"
CB_ACCOUNT_ADD = "account_add"
CB_ACCOUNT_OPEN_PREFIX = "account_open"      # account_open:{id}
CB_ACCOUNT_RENAME = "account_rename"          # account_rename:{id}
CB_ACCOUNT_RECONNECT = "account_reconnect"    # account_reconnect:{id}
CB_ACCOUNT_REVOKE = "account_revoke"          # account_revoke:{id}
CB_ACCOUNT_REVOKE_CONFIRM = "account_revoke_confirm"  # account_revoke_confirm:{id}

CB_CHATS = "chats"
CB_CHAT_ADD = "chat_add"
CB_CHAT_OPEN = "chat"                         # chat:{id}
CB_CHAT_TOGGLE = "chat_toggle"                # chat_toggle:{id}
CB_CHAT_ALERTS = "chat_alerts"                # chat_alerts:{id}
CB_CHAT_SETTINGS = "chat_settings"            # chat_settings:{id}
CB_CHAT_KEYWORDS = "chat_keywords"            # chat_keywords:{id}
CB_CHAT_KEYWORDS_EDIT = "chat_keywords_edit"  # chat_keywords_edit:{id}
CB_CHAT_DELETE = "chat_delete"                # chat_delete:{id}
CB_CHAT_DELETE_CONFIRM = "chat_delete_confirm"  # chat_delete_confirm:{id}

CB_STATS = "stats"
CB_ADMIN = "admin"

CB_ADD_SESSION_PREFIX = "add_session"         # add_session:{id}
CB_ADD_HOURS_PREFIX = "add_hours"             # add_hours:{n}
CB_ADD_PROMPT_PREFIX = "add_prompt"           # add_prompt:default|custom


# --- Main menu -------------------------------------------------------------


def main_menu(is_admin: bool, has_authorized_sessions: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton("📱 Аккаунты", callback_data=CB_ACCOUNTS)])
    if has_authorized_sessions:
        rows.append([
            InlineKeyboardButton("💬 Мои чаты", callback_data=CB_CHATS),
            InlineKeyboardButton("📊 Статистика", callback_data=CB_STATS),
        ])
    if is_admin:
        rows.append([InlineKeyboardButton("👑 Админ", callback_data=CB_ADMIN)])
    return InlineKeyboardMarkup(rows)


def cancel_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=CB_CANCEL)]])


def back_main_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=CB_BACK_MAIN)]])


# --- Accounts --------------------------------------------------------------


def accounts_list(sessions: list[UserSession], connected_ids: set[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for s in sessions:
        dot = "🟢" if s.id in connected_ids else "🔴"
        label = s.label or "Без названия"
        phone = s.phone or "—"
        rows.append([
            InlineKeyboardButton(
                f"{dot} {phone} — {label}",
                callback_data=f"{CB_ACCOUNT_OPEN_PREFIX}:{s.id}",
            ),
            InlineKeyboardButton("⚙️", callback_data=f"{CB_ACCOUNT_OPEN_PREFIX}:{s.id}"),
        ])
    rows.append([InlineKeyboardButton("➕ Добавить аккаунт", callback_data=CB_ACCOUNT_ADD)])
    rows.append([InlineKeyboardButton("← Назад", callback_data=CB_BACK_MAIN)])
    return InlineKeyboardMarkup(rows)


def account_detail(session_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✏️ Переименовать", callback_data=f"{CB_ACCOUNT_RENAME}:{session_id}")],
        [InlineKeyboardButton("🔄 Переподключить", callback_data=f"{CB_ACCOUNT_RECONNECT}:{session_id}")],
        [InlineKeyboardButton("❌ Удалить аккаунт", callback_data=f"{CB_ACCOUNT_REVOKE}:{session_id}")],
        [InlineKeyboardButton("← Назад", callback_data=CB_ACCOUNTS)],
    ]
    return InlineKeyboardMarkup(rows)


def account_revoke_confirm(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Да, удалить", callback_data=f"{CB_ACCOUNT_REVOKE_CONFIRM}:{session_id}")],
        [InlineKeyboardButton("← Отмена", callback_data=f"{CB_ACCOUNT_OPEN_PREFIX}:{session_id}")],
    ])


# --- Chats -----------------------------------------------------------------


def chats_list(chats: list[Chat], session_labels: dict[int, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for chat in chats:
        marker = "✅" if chat.is_active else "⏸"
        owner = session_labels.get(chat.session_id, "—") if chat.session_id else "—"
        rows.append([
            InlineKeyboardButton(
                f"📋 {chat.name} {marker} ({owner}) ▶",
                callback_data=f"{CB_CHAT_OPEN}:{chat.id}",
            )
        ])
    rows.append([InlineKeyboardButton("➕ Добавить чат", callback_data=CB_CHAT_ADD)])
    rows.append([InlineKeyboardButton("← Назад", callback_data=CB_BACK_MAIN)])
    return InlineKeyboardMarkup(rows)


def chat_menu(chat: Chat) -> InlineKeyboardMarkup:
    alerts_label = "ВКЛ" if chat.alerts_enabled else "ВЫКЛ"
    pause_label = "Пауза" if chat.is_active else "Запустить"
    rows = [
        [InlineKeyboardButton("▶️ Запустить", callback_data=f"digest_run:{chat.id}")],
        [
            InlineKeyboardButton("⏱ 1ч", callback_data=f"digest_1h:{chat.id}"),
            InlineKeyboardButton("⏱ 5ч", callback_data=f"digest_5h:{chat.id}"),
            InlineKeyboardButton("⏱ 12ч", callback_data=f"digest_12h:{chat.id}"),
            InlineKeyboardButton("⏱ 24ч", callback_data=f"digest_24h:{chat.id}"),
        ],
        [
            InlineKeyboardButton("📅 За неделю", callback_data=f"digest_7d:{chat.id}"),
            InlineKeyboardButton("🔎 Поиск", callback_data=f"search:{chat.id}"),
        ],
        [
            InlineKeyboardButton(f"⚡ Алерты: {alerts_label}", callback_data=f"{CB_CHAT_ALERTS}:{chat.id}"),
            InlineKeyboardButton("🔔 Ключевые слова", callback_data=f"{CB_CHAT_KEYWORDS}:{chat.id}"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_CHAT_SETTINGS}:{chat.id}"),
            InlineKeyboardButton(f"⏸ {pause_label}", callback_data=f"{CB_CHAT_TOGGLE}:{chat.id}"),
        ],
        [InlineKeyboardButton("← Назад", callback_data=CB_CHATS)],
    ]
    return InlineKeyboardMarkup(rows)


def chat_settings(chat_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✏️ Изменить промпт", callback_data=f"chat_edit_prompt:{chat_id}")],
        [InlineKeyboardButton("🕐 Изменить расписание", callback_data=f"chat_edit_time:{chat_id}")],
        [InlineKeyboardButton("📏 Изменить период", callback_data=f"chat_edit_hours:{chat_id}")],
        [InlineKeyboardButton("📤 Изменить источник/назначение", callback_data=f"chat_edit_src:{chat_id}")],
        [InlineKeyboardButton("🗑 Удалить чат", callback_data=f"{CB_CHAT_DELETE}:{chat_id}")],
        [InlineKeyboardButton("← Назад", callback_data=f"{CB_CHAT_OPEN}:{chat_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def chat_keywords_menu(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить список", callback_data=f"{CB_CHAT_KEYWORDS_EDIT}:{chat_id}")],
        [InlineKeyboardButton("← Назад", callback_data=f"{CB_CHAT_OPEN}:{chat_id}")],
    ])


def chat_delete_confirm(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Да, удалить", callback_data=f"{CB_CHAT_DELETE_CONFIRM}:{chat_id}")],
        [InlineKeyboardButton("← Отмена", callback_data=f"{CB_CHAT_OPEN}:{chat_id}")],
    ])


def back_to_chat(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад", callback_data=f"{CB_CHAT_OPEN}:{chat_id}")]
    ])


# --- Add-chat wizard -------------------------------------------------------


def session_choice(sessions: list[UserSession]) -> InlineKeyboardMarkup:
    rows = []
    for s in sessions:
        label = s.label or "Без названия"
        rows.append([
            InlineKeyboardButton(
                f"🟢 {label} ({s.phone})",
                callback_data=f"{CB_ADD_SESSION_PREFIX}:{s.id}",
            )
        ])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(rows)


def hours_choice() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("1ч", callback_data=f"{CB_ADD_HOURS_PREFIX}:1"),
            InlineKeyboardButton("5ч", callback_data=f"{CB_ADD_HOURS_PREFIX}:5"),
            InlineKeyboardButton("12ч", callback_data=f"{CB_ADD_HOURS_PREFIX}:12"),
            InlineKeyboardButton("24ч", callback_data=f"{CB_ADD_HOURS_PREFIX}:24"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data=CB_CANCEL)],
    ]
    return InlineKeyboardMarkup(rows)


def prompt_choice() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📝 Ввести свой", callback_data=f"{CB_ADD_PROMPT_PREFIX}:custom")],
        [InlineKeyboardButton("✅ Использовать стандартный", callback_data=f"{CB_ADD_PROMPT_PREFIX}:default")],
        [InlineKeyboardButton("❌ Отмена", callback_data=CB_CANCEL)],
    ]
    return InlineKeyboardMarkup(rows)


# --- Admin -----------------------------------------------------------------


def admin_menu() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("👥 Пользователи", callback_data="admin_users:0"),
            InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        ],
        [InlineKeyboardButton("🔄 Перезапустить всё", callback_data="admin_restart")],
        [InlineKeyboardButton("← Назад", callback_data=CB_BACK_MAIN)],
    ]
    return InlineKeyboardMarkup(rows)


def admin_users_pagination(page: int, total_pages: int) -> list[InlineKeyboardButton]:
    prev_page = max(0, page - 1)
    next_page = min(total_pages - 1, page + 1)
    return [
        InlineKeyboardButton("← Пред", callback_data=f"admin_users:{prev_page}"),
        InlineKeyboardButton(f"{page + 1}/{max(1, total_pages)}", callback_data=CB_NOOP),
        InlineKeyboardButton("След →", callback_data=f"admin_users:{next_page}"),
    ]


def admin_users_list(
    users_page: list[tuple[int, str, int, bool]],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    rows = []
    for user_id, label, _chats, blocked in users_page:
        mark = "🚫" if blocked else "✅"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {label}",
                callback_data=f"admin_user:{user_id}",
            )
        ])
    if total_pages > 1:
        rows.append(admin_users_pagination(page, total_pages))
    rows.append([InlineKeyboardButton("← Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(rows)


def admin_user_detail(user_id: int, is_blocked: bool) -> InlineKeyboardMarkup:
    block_label = "✅ Разблокировать" if is_blocked else "🚫 Заблокировать"
    rows = [
        [InlineKeyboardButton(block_label, callback_data=f"admin_block:{user_id}")],
        [InlineKeyboardButton("📋 Чаты пользователя", callback_data=f"admin_user_chats:{user_id}")],
        [InlineKeyboardButton("📊 Статистика пользователя", callback_data=f"admin_user_stats:{user_id}")],
        [InlineKeyboardButton("🔌 Переподключить сессии", callback_data=f"admin_user_reconnect:{user_id}")],
        [InlineKeyboardButton("← Назад", callback_data="admin_users:0")],
    ]
    return InlineKeyboardMarkup(rows)


# --- Stats -----------------------------------------------------------------


def stats_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=CB_BACK_MAIN)]])
