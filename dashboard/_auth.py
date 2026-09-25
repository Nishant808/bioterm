"""Owner lock for the dashboard's write actions.

BioTerm is published at a public URL: anyone with the link can read it, only
the owner can change it. The owner unlocks a browser session with the passcode
(``bioterm.auth``); every edit control checks ``can_edit()`` first.

Two more ways to be the owner, both optional:
- ``BIOTERM_ADMIN_PASSWORD`` in the app's secrets replaces the stored passcode
  (and is how a forgotten one is reset);
- Streamlit's built-in OIDC login (``[auth]`` in secrets + Authlib) with the
  signed-in email listed in ``BIOTERM_OWNER_EMAILS``.

An unclaimed terminal (no passcode yet) stays editable and says so.
"""
from __future__ import annotations

import os

import streamlit as st

from bioterm import auth

_KEY = "bt_owner"


def _oidc_owner() -> bool:
    emails = {e.strip().lower() for e in os.environ.get("BIOTERM_OWNER_EMAILS", "").split(",")
              if e.strip()}
    if not emails:
        return False
    try:
        u = st.user
        return bool(u.get("is_logged_in")) and str(u.get("email", "")).lower() in emails
    except Exception:  # noqa: BLE001 - auth not configured
        return False


@st.cache_data(ttl=30, show_spinner=False)
def _claimed() -> bool:
    try:
        return auth.is_claimed()
    except Exception:  # noqa: BLE001 - database unreachable: fail closed
        return True


def claimed() -> bool:
    return _claimed()


def can_edit() -> bool:
    if not claimed():
        return True
    return bool(st.session_state.get(_KEY)) or _oidc_owner()


def is_owner_session() -> bool:
    """Unlocked with the passcode (or signed in as an owner) - not merely unclaimed."""
    return bool(st.session_state.get(_KEY)) or _oidc_owner()


def lock() -> None:
    st.session_state[_KEY] = False


def unlock_form(key: str) -> None:
    with st.form(key, border=False, clear_on_submit=True):
        code = st.text_input("Owner passcode", type="password", key=f"{key}_code",
                             autocomplete="current-password")
        if st.form_submit_button("Unlock", icon=":material/lock_open:", type="primary",
                                 width="stretch"):
            if auth.verify(code):
                st.session_state[_KEY] = True
                st.rerun()
            else:
                st.error("That passcode isn't right.")


def guard(what: str = "make changes", key: str = "g") -> bool:
    """Put before an edit area. True = editing allowed; otherwise renders a
    one-line read-only notice with an unlock popover and returns False."""
    if can_edit():
        return True
    with st.container(horizontal=True, vertical_alignment="center", gap="small",
                      key=f"bt-guard-{key}"):
        st.caption(f":material/lock: Read-only - unlock to {what}.")
        with st.popover("Unlock", icon=":material/key:"):
            unlock_form(f"unlock_{key}")
    return False


def header_chip() -> None:
    """Lock state in the page header: unlock / lock, or a nudge to set a passcode."""
    if not claimed():
        st.page_link("app_pages/settings.py", label="Set passcode", icon=":material/lock_open:",
                     help="Anyone with the link can edit this terminal until you set an owner "
                          "passcode")
        return
    if is_owner_session():
        if st.button("Lock", icon=":material/lock_open:", type="tertiary", key="bt-lock",
                     help="You can edit. Lock this browser session."):
            lock()
            st.rerun()
        return
    with st.popover("Read-only", icon=":material/lock:",
                    help="Unlock with the owner passcode to edit"):
        unlock_form("unlock_header")
