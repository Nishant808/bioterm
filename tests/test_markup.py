"""Feed markup handling: titles carrying HTML must come out as plain text
everywhere - ingestion, alert details and the Telegram message."""
from datetime import datetime, timezone

from bioterm.util import strip_markup

FIERCE = ('<a href="https://www.fiercebiotech.com/biotech/otsuka-heads-fda" '
          'hreflang="en">Otsuka heads to FDA as Ionis-partnered ALS drug hits phase 3</a>')


def test_strip_markup_removes_tags_and_decodes_entities():
    assert strip_markup(FIERCE) == "Otsuka heads to FDA as Ionis-partnered ALS drug hits phase 3"
    assert strip_markup("R&amp;D update &mdash; <b>big</b>") == "R&D update — big"


def test_strip_markup_drops_a_tag_cut_off_by_truncation():
    assert strip_markup(FIERCE[:60]) == ""
    assert strip_markup("approval — " + FIERCE[:50]) == "approval —"


def test_strip_markup_keeps_comparisons_in_prose():
    # feedparser decodes entities, so these arrive as literal "<" / ">"
    for s in ("Drug X hits primary endpoint (p<0.001)", "viral load <LLOQ in 90% of patients",
              "ALT <3x ULN, HR>0.8", "survival <median OS"):
        assert strip_markup(s) == s


def test_strip_markup_handles_missing_values():
    assert strip_markup(None) == ""
    assert strip_markup(float("nan")) == ""


def test_alert_details_are_plain_text(monkeypatch):
    from bioterm import alerts
    from bioterm.db import bulk_upsert, init_db, news

    init_db()
    now = datetime.now(timezone.utc)
    bulk_upsert(news, [{
        "id": "n1", "ticker": "IONS", "tickers_csv": "IONS", "title": FIERCE,
        "summary": "", "url": "http://x", "source": "FierceBiotech", "published": now,
        "sentiment": 0.5, "event_tags": "approval", "event_score": 1.0, "fetched_at": now,
    }])
    fired = alerts.evaluate({**alerts.DEFAULT_RULES, "event_tags": ["approval"]})
    detail = next(a["detail"] for a in fired if a["kind"] == "headline")
    assert "<" not in detail and "href" not in detail
    assert "Otsuka heads to FDA" in detail


def test_telegram_message_is_html_escaped(monkeypatch):
    from bioterm import alerts, notify

    sent = {}

    class _Resp:
        def raise_for_status(self):
            return None

    class _Session:
        def post(self, url, json=None, timeout=None, **kw):
            sent.update(json or {})
            return _Resp()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setattr(notify, "session", lambda: _Session())
    monkeypatch.setattr(alerts, "evaluate", lambda rules=None: [
        {"kind": "headline", "ticker": "ABC", "detail": "R&D day <10% dilution", "weight": 1.0}])
    from bioterm.db import init_db

    init_db()
    alerts.run(deliver=True)
    assert "R&amp;D day &lt;10% dilution" in sent["text"]
