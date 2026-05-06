"""簡易パスワードゲート — Streamlit Cloud 公開用"""
from __future__ import annotations

import streamlit as st


def require_password() -> None:
    """未認証なら入力UIを描画し st.stop()。認証済みなら何もしない。

    パスワードは secrets.toml の APP_PASSWORD を優先、無ければ既定値。
    """
    if st.session_state.get("auth_ok"):
        return

    try:
        expected = st.secrets["APP_PASSWORD"]
    except Exception:
        expected = "defense2024"

    st.title("🛡️ 防衛省・自衛隊 調達情報ダッシュボード")
    st.caption("閲覧にはパスワードが必要です。")
    pw = st.text_input("パスワード", type="password", key="auth_pw")
    if st.button("ログイン"):
        if pw == expected:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    st.stop()
