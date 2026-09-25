"""Settings - owner passcode, AI keys and models, notification channels, data
providers and system status. Every secret is stored encrypted in the database
(bioterm.vault) and is never shown again after saving - only its last four
characters."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import _auth
from _ui import card, kpi_row, kv_list, label, page_header, usd
from bioterm import ai, auth, notify, vault

page_header("Settings", "Owner access · AI keys and models · alert channels · data providers · "
                        "system")

# keys, channels, the API token and the pulse toggle are the owner-only surface
editable = _auth.can_admin()
tab_access, tab_ai, tab_notify, tab_data, tab_sys = st.tabs(
    ["Access", "AI", "Notifications", "Data providers", "System"], key="settings_tab")


def _when(ts) -> str:
    try:
        t = pd.Timestamp(ts)
        return "" if pd.isna(t) else f" · updated {t:%b %d, %Y}"
    except (ValueError, TypeError):
        return ""


def _rows() -> dict[str, dict]:
    try:
        return {r["name"]: r for r in vault.listing()}
    except Exception:  # noqa: BLE001
        return {}


def secret_editor(name: str, *, test=None, placeholder: str = "", secret: bool = True,
                  key: str | None = None) -> None:
    """Add / replace / test / delete one vault secret."""
    k = key or name
    row = _rows().get(name) or {"label": vault.CATALOG[name][0], "help": vault.CATALOG[name][2],
                                "set": False, "origin": None, "hint": None}
    origin, hint = row.get("origin"), row.get("hint")
    with st.container(border=True, key=f"bt-secret-{k}"):
        with st.container(horizontal=True, vertical_alignment="center",
                          horizontal_alignment="distribute"):
            st.markdown(f"**{row['label']}**")
            if origin == "env":
                st.badge("From environment", icon=":material/dns:", color="blue")
            elif origin == "vault":
                st.badge(f"Saved {hint or ''}".strip(), icon=":material/check_circle:",
                         color="green")
            else:
                st.badge("Not set", icon=":material/radio_button_unchecked:", color="gray")
        st.caption(row["help"] + (_when(row.get("updated_at")) if origin == "vault" else ""))
        if origin == "env":
            st.caption("Set in the app's secrets / environment, which takes precedence - "
                       "change or remove it there.")
            if test and st.button("Test", key=f"test_env_{k}", icon=":material/science:",
                                  type="tertiary"):
                ok, msg = test(vault.get(name))
                (st.success if ok else st.error)(msg)
            return
        if not editable:
            return
        with st.form(f"f_{k}", clear_on_submit=True, border=False):
            val = st.text_input("New value" if origin else "Value",
                                type="password" if secret else "default",
                                placeholder=placeholder, key=f"in_{k}",
                                label_visibility="collapsed", autocomplete="off")
            with st.container(horizontal=True, gap="small"):
                save = st.form_submit_button("Test & save" if test else "Save", type="primary",
                                             icon=":material/save:")
                force = st.form_submit_button("Save without testing", type="tertiary") \
                    if test else False
        if save or force:
            val = (val or "").strip()
            if not val:
                st.warning("Enter a value first.")
            else:
                ok, msg = (True, "Saved")
                if test and save:
                    with st.spinner("Checking…"):
                        ok, msg = test(val)
                if ok:
                    vault.set(name, val)
                    st.cache_data.clear()
                    st.toast(f"{row['label']} saved", icon=":material/check_circle:")
                    st.rerun()
                else:
                    st.error(f"Not saved - {msg}")
        if origin == "vault":
            with st.container(horizontal=True, gap="small"):
                if test and st.button("Test saved value", key=f"test_{k}", type="tertiary",
                                      icon=":material/science:"):
                    with st.spinner("Checking…"):
                        ok, msg = test(vault.get(name))
                    (st.success if ok else st.error)(msg)
                with st.popover("Delete", icon=":material/delete:", type="tertiary"):
                    st.caption(f"Remove the stored {row['label']}? Features that use it stop "
                               "until a new one is saved.")
                    if st.button("Delete permanently", key=f"del_{k}", type="primary",
                                 icon=":material/delete_forever:"):
                        vault.delete(name)
                        st.cache_data.clear()
                        st.toast(f"{row['label']} deleted", icon=":material/delete:")
                        st.rerun()


# ================================================================ Access
with tab_access:
    env_pw = auth.env_override()
    if not _auth.claimed():
        need_proof = auth.claim_proof_required()
        with card("Set an owner passcode", icon_name="lock"):
            st.warning("This terminal has no owner yet. Set a passcode now; afterwards "
                       "visitors can read everything but change nothing."
                       + (" API keys and alert channels unlock once it is set." if need_proof
                          else ""), icon=":material/warning:")
            with st.form("claim", border=False):
                proof = st.text_input(
                    "Database password", type="password", autocomplete="off",
                    help="Proves you own this deployment: the password inside your "
                         "DATABASE_URL (between the ':' after the user name and the '@'). "
                         "It is only compared, never stored.") if need_proof else None
                p1 = st.text_input("Passcode (8+ characters)", type="password",
                                   autocomplete="new-password")
                p2 = st.text_input("Repeat passcode", type="password",
                                   autocomplete="new-password")
                if st.form_submit_button("Set passcode", type="primary", icon=":material/lock:"):
                    if p1 != p2:
                        st.error("The two entries differ.")
                    else:
                        try:
                            auth.claim(p1, proof)
                            st.session_state[_auth._KEY] = True
                            st.cache_data.clear()
                            st.toast("Passcode set - this browser session is unlocked",
                                     icon=":material/lock:")
                            st.rerun()
                        except (ValueError, PermissionError) as exc:
                            st.error(str(exc))
    elif not _auth.is_owner_session():
        with card("Unlock", icon_name="lock"):
            st.caption("Visitors can read everything. Enter the owner passcode to edit.")
            _auth.unlock_form("unlock_settings")
    else:
        with card("Owner access", icon_name="lock_open",
                  meta="This browser session can edit"):
            if env_pw:
                st.info("The passcode is set by `BIOTERM_ADMIN_PASSWORD` in the app's secrets - "
                        "change it there.", icon=":material/dns:")
            else:
                with st.form("change_pw", clear_on_submit=True, border=False):
                    st.caption("Change passcode")
                    old = st.text_input("Current passcode", type="password",
                                        autocomplete="current-password")
                    new1 = st.text_input("New passcode", type="password",
                                         autocomplete="new-password")
                    new2 = st.text_input("Repeat new passcode", type="password",
                                         autocomplete="new-password")
                    if st.form_submit_button("Change passcode", icon=":material/key:"):
                        if new1 != new2:
                            st.error("The new entries differ.")
                        else:
                            try:
                                auth.change(old, new1)
                                st.toast("Passcode changed", icon=":material/check_circle:")
                            except (ValueError, PermissionError) as exc:
                                st.error(str(exc))
            if st.button("Lock this session", icon=":material/lock:"):
                _auth.lock()
                st.rerun()
        st.caption("Forgot the passcode? Set `BIOTERM_ADMIN_PASSWORD` in the Streamlit app's "
                   "secrets - it replaces the stored one.")

# ================================================================ AI
with tab_ai:
    stt = ai.status()
    s = ai.settings()
    budget = float(s.get("daily_budget_usd") or 0)
    with kpi_row(3, "ai"):
        st.metric("Provider", {"anthropic": "Anthropic (Claude)", "openai": "OpenAI-compatible",
                               None: "Off - no key"}[stt["provider"]], border=True)
        st.metric("Copilot model", stt["model"] or "—", border=True)
        st.metric("Spent today", usd(stt["spent_today"], 2),
                  delta=f"of {usd(budget, 2)} budget" if budget else "no budget cap",
                  delta_color="off", border=True)

    label("API keys", "encrypted in the database · shown only as the last 4 characters")
    if not editable:
        _auth.guard("add or delete API keys", key="ai", admin=True)
    c1, c2 = st.columns(2)
    with c1:
        secret_editor("ANTHROPIC_API_KEY", placeholder="sk-ant-…",
                      test=lambda v: ai.test_key("anthropic", v))
    with c2:
        secret_editor("OPENAI_API_KEY", placeholder="sk-…",
                      test=lambda v: ai.test_key("openai", v, vault.get("OPENAI_BASE_URL")))
        secret_editor("OPENAI_BASE_URL", secret=False,
                      placeholder="https://openrouter.ai/api/v1 (optional)")

    label("Models and budget")
    with st.container(border=True):
        with st.form("ai_settings", border=False):
            prov_opts = ["auto", "anthropic", "openai"]
            prov = st.segmented_control(
                "Provider", prov_opts, default=s.get("provider", "auto"),
                format_func={"auto": "Automatic", "anthropic": "Anthropic",
                             "openai": "OpenAI-compatible"}.get,
                help="Automatic uses Anthropic when its key is set, else the OpenAI-compatible "
                     "endpoint")
            models = list(ai.CLAUDE_MODELS)
            m1, m2 = st.columns(2)
            mc = m1.selectbox("Copilot & daily brief (Claude)", models,
                              index=models.index(s["model_copilot"])
                              if s["model_copilot"] in models else 0,
                              format_func=ai.CLAUDE_MODELS.get)
            mb = m2.selectbox("Background extraction & summaries (Claude)", models,
                              index=models.index(s["model_bulk"])
                              if s["model_bulk"] in models else 0,
                              format_func=ai.CLAUDE_MODELS.get,
                              help="Runs on every data refresh over new headlines and "
                                   "filings - the cheaper models cut the bill a lot")
            om = st.text_input("OpenAI-compatible model name", value=s.get("openai_model", ""),
                               placeholder="the model id your endpoint serves",
                               help="Only used with the OpenAI-compatible provider")
            b = st.number_input("Daily budget (USD)", min_value=0.0, max_value=500.0,
                                value=budget, step=0.5,
                                help="Background jobs stop for the day at this estimate; the "
                                     "Copilot gets 50% headroom on top. 0 = no cap")
            jobs = s["jobs"]
            label("Background jobs")
            j1, j2, j3, j4, j5 = st.columns(5)
            jn = j1.toggle("News events", jobs.get("news", True),
                           help="Tag headlines: topline, PDUFA, CRL, financing … + dates")
            jf = j2.toggle("8-K summaries", jobs.get("filings", True))
            jb = j3.toggle("Daily brief", jobs.get("brief", True))
            jr = j4.toggle("Risk-factor diffs", jobs.get("risk", True),
                           help="Summarise what changed in 10-K/10-Q risk factors")
            jp = j5.toggle("PDUFA reading", jobs.get("pdufa", True),
                           help="Read ambiguous PDUFA/AdCom mentions in filings")
            if st.form_submit_button("Save AI settings", type="primary", icon=":material/save:",
                                     disabled=not editable):
                ai.save_settings(provider=prov or "auto", model_copilot=mc, model_bulk=mb,
                                 openai_model=om.strip(), daily_budget_usd=float(b),
                                 jobs={"news": jn, "filings": jf, "brief": jb, "risk": jr,
                                       "pdufa": jp})
                st.toast("AI settings saved", icon=":material/check_circle:")
                st.rerun()

    with card("Usage, last 30 days", icon_name="payments",
              meta="token counts from the API · cost is an estimate at list prices"):
        try:
            hist = ai.usage_history(30)
        except Exception:  # noqa: BLE001
            hist = pd.DataFrame()
        if hist.empty:
            st.caption("No AI calls yet.")
        else:
            daily = hist.groupby("day", as_index=False)["cost_usd"].sum()
            st.bar_chart(daily, x="day", y="cost_usd", height=160, x_label="",
                         y_label="USD")
            by = hist.groupby("model", as_index=False)[
                ["calls", "input_tokens", "output_tokens", "cost_usd"]].sum()
            st.dataframe(by, hide_index=True, width="stretch",
                         column_config={"cost_usd": st.column_config.NumberColumn(
                             "Cost (est.)", format="$%.2f")})

# ================================================================ Notifications
with tab_notify:
    conf = notify.configured()
    st.caption("Alerts go to every configured channel unless the Alerts page routes a kind "
               "elsewhere. Snoozes and routing live on the Alerts page.")
    if not editable:
        _auth.guard("change alert channels", key="notify", admin=True)
    groups = {
        "ntfy": ("Phone push (ntfy)", ["NTFY_TOPIC", "NTFY_SERVER", "NTFY_TOKEN"]),
        "telegram": ("Telegram", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]),
        "slack": ("Slack", ["SLACK_WEBHOOK_URL"]),
        "discord": ("Discord", ["DISCORD_WEBHOOK_URL"]),
        "email": ("Email (SMTP)", ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                                   "SMTP_FROM", "SMTP_TO"]),
    }
    for ch, (title, names) in groups.items():
        with st.expander(f"{title} — {'configured' if conf.get(ch) else 'not configured'}",
                         icon=":material/check_circle:" if conf.get(ch)
                         else ":material/radio_button_unchecked:"):
            cols = st.columns(2)
            for i, n in enumerate(names):
                with cols[i % 2]:
                    secret_editor(n, secret=n not in ("NTFY_SERVER", "SMTP_HOST", "SMTP_PORT",
                                                      "SMTP_FROM", "SMTP_TO", "SMTP_USER",
                                                      "TELEGRAM_CHAT_ID"),
                                  key=f"{ch}_{n}")
            if st.button(f"Send a test to {title}", key=f"test_{ch}", icon=":material/send:",
                         disabled=not (conf.get(ch) and editable)):
                ok, msg = notify.test(ch)
                (st.success if ok else st.error)(msg)

# ================================================================ Data providers
with tab_data:
    st.caption("Optional providers. Without them BioTerm uses free public sources only.")
    if not editable:
        _auth.guard("change data-provider keys", key="data", admin=True)

    def _finnhub_test(v):
        try:
            from bioterm.quotes import _finnhub

            q = _finnhub("AAPL", v)
            return (True, f"Key works - AAPL {q['price']:.2f}") if q else \
                (False, "No quote returned")
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:120]

    secret_editor("FINNHUB_API_KEY", test=_finnhub_test, placeholder="Finnhub token")
    st.caption("Live prices come from Yahoo Finance, then Nasdaq's public quote API, then "
               "Finnhub (when a key is saved), then the last stored close.")

# ================================================================ System
with tab_sys:
    from bioterm.db import read_sql

    rows = []
    try:
        v = read_sql("SELECT MAX(version) AS v FROM schema_migrations").iloc[0]["v"]
        rows.append(("Schema version", str(int(v)) if pd.notna(v) else "—", None))
    except Exception:  # noqa: BLE001
        pass
    try:
        from bioterm.db import get_engine

        eng = get_engine()
        rows.append(("Database", eng.dialect.name, None))
        if eng.dialect.name.startswith("postgres"):
            sz = read_sql("SELECT pg_database_size(current_database()) AS b").iloc[0]["b"]
            rows.append(("Database size", f"{sz / 1e6:,.0f} MB", None))
    except Exception:  # noqa: BLE001
        pass
    from bioterm.market_calendar import next_trading_day, session

    state, lab = session()
    rows.append(("US market", lab, None))
    rows.append(("Next trading day", f"{next_trading_day(pd.Timestamp.now(tz='America/New_York').date()):%a %b %d}", None))
    try:
        from bioterm.store import get_meta

        w = get_meta("worker_state", {}) or {}
        if w:
            rows.append(("Background pulse", f"last run {str(w.get('last_run', '—'))[:16]} UTC",
                         None))
    except Exception:  # noqa: BLE001
        pass
    with card("Status", icon_name="monitor_heart"):
        kv_list(rows)
    try:
        from bioterm.store import get_meta, set_meta

        wcfg = get_meta("worker", {"enabled": True}) or {"enabled": True}
        on = st.toggle("Run the live pulse inside this app while someone has it open",
                       value=bool(wcfg.get("enabled", True)), disabled=not editable,
                       help="Checks trading halts, new SEC filings, wire headlines and big "
                            "movers every few minutes and fires alerts - in addition to the "
                            "scheduled GitHub Actions pulse")
        if editable and on != bool(wcfg.get("enabled", True)):
            set_meta("worker", {**wcfg, "enabled": on})
            st.toast("Saved", icon=":material/check_circle:")
    except Exception:  # noqa: BLE001
        pass
    st.page_link("app_pages/health.py", label="Data health and ingestion runs",
                 icon=":material/monitor_heart:")

    label("Read-only API")
    st.caption("`bioterm api` serves the database as JSON (universe, scores, signals, "
               "catalysts, one stock, screens, alerts, data-quality) for spreadsheets and "
               "notebooks. Every call needs this token as `Authorization: Bearer …`.")
    secret_editor("BIOTERM_API_TOKEN", placeholder="paste a token, or generate one below")
    if editable and vault.source("BIOTERM_API_TOKEN") != "env":
        if st.button("Generate a new token", icon=":material/key:", type="tertiary",
                     key="api_tok_gen"):
            import secrets as _secrets

            tok = _secrets.token_urlsafe(32)
            vault.set("BIOTERM_API_TOKEN", tok)
            st.session_state["api_tok_new"] = tok
        if st.session_state.get("api_tok_new"):
            st.code(st.session_state["api_tok_new"], language=None)
            st.caption("Copy it now - it is stored encrypted and shown only as its last "
                       "four characters from here on.")
