from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.db.models import Chat

MAIN_MY_CHATS = "💬 Мои чаты"
MAIN_STATS = "📊 Статистика"
MAIN_ADMIN = "👑 Админ панель"
MAIN_ACCOUNT = "📱 Аккаунт"

CB_CANCEL = "cancel"
CB_BACK_MAIN = "back_main"


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(MAIN_MY_CHATS)],
        [KeyboardButton(MAIN_ACCOUNT)],
        [KeyboardButton(MAIN_STATS)],
    ]
    if is_admin:
        rows.append([KeyboardButton(MAIN_ADMIN)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def cancel_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=CB_CANCEL)]])


def chats_list(chats: list[Chat]) -> InlineKeyboardMarkup:
    rows = []
    for chat in chats:
        marker = "✅" if chat.is_active else "⏸"
        rows.append([
            InlineKeyboardButton(
                f"📋 {chat.name} {marker}",
                callback_data=f"chat:{chat.id}",
            )
        ])
    rows.append([InlineKeyboardButton("➕ Добавить чат", callback_data="chat_add")])
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
        [InlineKeyboardButton(f"⚡ Алерты: {alerts_label}", callback_data=f"chat_alerts:{chat.id}")],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"chat_settings:{chat.id}"),
            InlineKeyboardButton(f"⏸ {pause_label}", callback_data=f"chat_toggle:{chat.id}"),
        ],
        [InlineKeyboardButton("← Назад", callback_data="chats_list")],
    ]
    return InlineKeyboardMarkup(rows)


def chat_settings(chat_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✏️ Изменить промпт", callback_data=f"chat_edit_prompt:{chat_id}")],
        [InlineKeyboardButton("🕐 Изменить расписание", callback_data=f"chat_edit_time:{chat_id}")],
        [InlineKeyboardButton("📏 Изменить период", callback_data=f"chat_edit_hours:{chat_id}")],
        [InlineKeyboardButton("📤 Изменить источник/назначение", callback_data=f"chat_edit_src:{chat_id}")],
        [InlineKeyboardButton("🗑 Удалить чат", callback_data=f"chat_delete:{chat_id}")],
        [InlineKeyboardButton("← Назад", callback_data=f"chat:{chat_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def chat_delete_confirm(chat_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🗑 Да, удалить", callback_data=f"chat_delete_confirm:{chat_id}")],
        [InlineKeyboardButton("← Отмена", callback_data=f"chat_settings:{chat_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def account_menu(is_authorized: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_authorized:
        rows.append([InlineKeyboardButton("🔄 Переподключить", callback_data="account_reconnect")])
        rows.append([InlineKeyboardButton("❌ Удалить аккаунт", callback_data="account_revoke")])
    else:
        rows.append([InlineKeyboardButton("➕ Подключить аккаунт", callback_data="account_add")])
    rows.append([InlineKeyboardButton("← Назад", callback_data=CB_BACK_MAIN)])
    return InlineKeyboardMarkup(rows)


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
        InlineKeyboardButton(f"{page + 1}/{max(1, total_pages)}", callback_data="noop"),
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
        [InlineKeyboardButton("🔌 Переподключить сессию", callback_data=f"admin_user_reconnect:{user_id}")],
        [InlineKeyboardButton("← Назад", callback_data="admin_users:0")],
    ]
    return InlineKeyboardMarkup(rows)


def hours_choice() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("1ч", callback_data="add_hours:1"),
            InlineKeyboardButton("5ч", callback_data="add_hours:5"),
            InlineKeyboardButton("12ч", callback_data="add_hours:12"),
            InlineKeyboardButton("24ч", callback_data="add_hours:24"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data=CB_CANCEL)],
    ]
    return InlineKeyboardMarkup(rows)


def prompt_choice() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📝 Ввести промпт", callback_data="add_prompt:custom")],
        [InlineKeyboardButton("✅ Использовать стандартный", callback_data="add_prompt:default")],
        [InlineKeyboardButton("❌ Отмена", callback_data=CB_CANCEL)],
    ]
    return InlineKeyboardMarkup(rows)


def back_to_chat(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад", callback_data=f"chat:{chat_id}")]
    ])
