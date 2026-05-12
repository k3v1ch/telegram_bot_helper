from bot.db.models import Chat, UserSession
from bot.keyboards import (
    CB_ACCOUNTS,
    CB_ADMIN,
    CB_BACK_MAIN,
    CB_CHATS,
    CB_STATS,
    account_detail,
    accounts_list,
    chats_list,
    main_menu,
    session_choice,
)


def test_main_menu_anon_no_chats_no_admin():
    kb = main_menu(is_admin=False, has_authorized_sessions=False)
    # 1 row: Accounts only
    rows = kb.inline_keyboard
    assert len(rows) == 1
    assert rows[0][0].callback_data == CB_ACCOUNTS


def test_main_menu_with_session_shows_chats_and_stats():
    kb = main_menu(is_admin=False, has_authorized_sessions=True)
    callbacks = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert CB_CHATS in callbacks
    assert CB_STATS in callbacks
    assert CB_ACCOUNTS in callbacks


def test_main_menu_admin_button_when_admin():
    kb = main_menu(is_admin=True, has_authorized_sessions=True)
    callbacks = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert CB_ADMIN in callbacks


def test_main_menu_no_admin_button_when_not_admin():
    kb = main_menu(is_admin=False, has_authorized_sessions=True)
    callbacks = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert CB_ADMIN not in callbacks


def test_accounts_list_empty():
    kb = accounts_list([], connected_ids=set())
    # Two rows: add button + back
    rows = kb.inline_keyboard
    assert len(rows) == 2


def test_accounts_list_marks_connected():
    s = UserSession(id=1, user_id=1, phone="+7", label="Main", is_authorized=True)
    kb = accounts_list([s], connected_ids={1})
    btn_text = kb.inline_keyboard[0][0].text
    assert "🟢" in btn_text


def test_accounts_list_marks_disconnected():
    s = UserSession(id=2, user_id=1, phone="+7", label="Main", is_authorized=True)
    kb = accounts_list([s], connected_ids=set())
    btn_text = kb.inline_keyboard[0][0].text
    assert "🔴" in btn_text


def test_account_detail_has_back():
    kb = account_detail(session_id=42)
    last_btn = kb.inline_keyboard[-1][0]
    assert "Назад" in last_btn.text
    assert last_btn.callback_data == CB_ACCOUNTS


def test_chats_list_shows_session_label():
    chat = Chat(id=10, user_id=1, session_id=5, name="MyChat", source="-1:1", dest="-1:2", is_active=True)
    kb = chats_list([chat], session_labels={5: "Main"})
    btn_text = kb.inline_keyboard[0][0].text
    assert "MyChat" in btn_text
    assert "Main" in btn_text


def test_session_choice_has_one_button_per_session():
    s1 = UserSession(id=1, user_id=1, phone="+7", label="A")
    s2 = UserSession(id=2, user_id=1, phone="+8", label="B")
    kb = session_choice([s1, s2])
    # 2 session rows + 1 cancel
    assert len(kb.inline_keyboard) == 3
