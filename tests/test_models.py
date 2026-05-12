from bot.db.models import Chat, UserSession


def test_user_session_columns():
    cols = {c.name for c in UserSession.__table__.columns}
    assert {"id", "user_id", "phone", "session_string", "label", "is_authorized"} <= cols


def test_user_session_unique_constraint():
    names = {c.name for c in UserSession.__table__.constraints}
    assert "uq_user_sessions_user_phone" in names


def test_chat_has_session_id():
    cols = {c.name for c in Chat.__table__.columns}
    assert "session_id" in cols
    assert "alert_keywords" in cols


def test_chat_session_id_nullable():
    col = Chat.__table__.columns["session_id"]
    assert col.nullable is True


def test_chat_alert_keywords_nullable():
    col = Chat.__table__.columns["alert_keywords"]
    assert col.nullable is True
