"""Per-molecule tracking: parsing watchlist labels, cross-sponsor trial search,
alias discovery, literature, derived links and the catalysts it feeds."""
from datetime import date, datetime, timedelta, timezone

from bioterm import store
from bioterm.db import bulk_upsert, init_db, news, read_sql, securities
from bioterm.ingest import molecules as ingest_mol
from bioterm.process import catalysts, molecules as proc_mol


def test_parse_labels():
    m = store.parse_molecule_label("mRNA-4157/V940 (melanoma)", "mrna")
    assert (m["ticker"], m["name"], m["aliases"], m["indication"]) == \
        ("MRNA", "mRNA-4157", ["V940"], "melanoma")
    m = store.parse_molecule_label("suzetrigine (VX-548)", "VRTX")
    assert m["aliases"] == ["VX-548"] and m["indication"] == ""
    m = store.parse_molecule_label("CTX310 (ANGPTL3, in vivo)", "CRSP")
    assert m["aliases"] == [] and m["indication"] == "ANGPTL3, in vivo"


def test_sync_from_watchlist_is_additive_and_respects_edits():
    init_db()
    store.save_watchlist([{"ticker": "MRNA", "conviction": 3, "thesis": "",
                           "molecules": ["mRNA-4157/V940 (melanoma)"]}])
    assert store.sync_molecules_from_watchlist() == 1
    m = store.get_molecules("MRNA")[0]
    m["aliases"] = ["V940", "intismeran autogene"]
    m["nct_ids"] = "NCT05933577, bogus"
    store.save_molecule(m)
    assert store.sync_molecules_from_watchlist() == 0
    got = store.get_molecules("MRNA")[0]
    assert got["aliases"] == ["V940", "intismeran autogene"]
    assert got["nct_ids"] == ["NCT05933577"]


def _study(nct, title, name, others, sponsor="Merck Sharp & Dohme LLC", phase="PHASE3",
           pcd="2027-03"):
    return {"protocolSection": {
        "identificationModule": {"nctId": nct, "briefTitle": title},
        "statusModule": {"overallStatus": "ACTIVE_NOT_RECRUITING",
                         "primaryCompletionDateStruct": {"date": pcd}},
        "designModule": {"phases": [phase], "studyType": "INTERVENTIONAL"},
        "armsInterventionsModule": {"interventions": [
            {"name": name, "otherNames": others}, {"name": "Pembrolizumab"}]},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor, "class": "INDUSTRY"}}}}


def test_ingest_finds_partner_trials_discovers_aliases_and_papers(monkeypatch):
    init_db()
    store.save_molecule({"ticker": "MRNA", "name": "mRNA-4157", "aliases": ["V940"]})
    search = {"studies": [
        _study("NCT05933577", "V940-001 in resected melanoma", "V940",
               ["mRNA-4157", "intismeran autogene"]),
        _study("NCT09999999", "Unrelated vaccine study", "mRNA-1283", []),
    ]}
    epmc = {"hitCount": 42, "resultList": {"result": [
        {"id": "1", "source": "MED", "pmid": "1", "title": "Intismeran in melanoma",
         "journalTitle": "NEJM", "firstPublicationDate": "2026-08-20", "pubYear": "2026"}]}}
    seen_queries = []

    def fake_json(url, params=None, **kw):
        if "europepmc" in url:
            seen_queries.append(params["query"])
            return epmc
        return search

    monkeypatch.setattr(ingest_mol, "get_json", fake_json)
    # the empty watchlist table falls back to config/watchlist.yml - keep this to one molecule
    monkeypatch.setattr(ingest_mol, "sync_molecules_from_watchlist", lambda: 0)
    out = ingest_mol.run()
    assert out["molecules"] == 1 and out["rows"] == 1          # the unrelated study is dropped
    t = read_sql("SELECT * FROM molecule_trials").iloc[0]
    assert t["nct_id"] == "NCT05933577" and t["ticker"] == "MRNA" and t["phase"] == "P3"
    assert '"intismeran autogene"' in seen_queries[0]           # discovered alias used
    st = read_sql("SELECT * FROM molecule_status").iloc[0]
    assert st["papers_total"] == 42 and "intismeran autogene" in st["discovered_aliases"]

    # the partnered readout becomes an MRNA catalyst
    catalysts.run()
    c = read_sql("SELECT * FROM catalysts WHERE source = 'molecule-tracking'")
    assert c["ticker"].tolist() == ["MRNA"] and c["type"].tolist() == ["phase3_readout"]

    # derived links: news naming any alias, and the catalyst
    now = datetime.now(timezone.utc)
    bulk_upsert(securities, [{"ticker": "MRNA", "name": "Moderna"}])
    bulk_upsert(news, [
        {"id": "n1", "ticker": "MRK", "title": "Merck's intismeran autogene hits endpoint",
         "published": now - timedelta(days=2), "sentiment": 0.6, "event_score": 1.0},
        {"id": "n2", "ticker": "MRNA", "title": "Moderna flu shot news",
         "published": now - timedelta(days=1), "sentiment": 0.1, "event_score": 0.0},
    ])
    proc_mol.run()
    links = read_sql("SELECT kind, ref_id FROM molecule_links")
    assert set(links[links["kind"] == "news"]["ref_id"]) == {"n1"}
    assert (links["kind"] == "catalyst").sum() == 1 and (links["kind"] == "paper").sum() == 1
    st = read_sql("SELECT * FROM molecule_status").iloc[0]
    assert st["n_trials"] == 1 and st["top_phase"] == "P3" and st["n_news_30d"] == 1
    assert st["next_readout"] is not None and st["papers_total"] == 42


def test_mentions_ignores_formatting():
    assert proc_mol.mentions("MRNA 4157 data at ESMO", ["mRNA-4157"])
    assert not proc_mol.mentions("mRNA vaccine data", ["mRNA-4157"])
    assert proc_mol.top_phase(["P1", "P2/P3", "P2"]) == "P2/P3"


def test_clean_aliases_keeps_names_and_drops_arm_labels():
    got = ingest_mol.clean_aliases(
        ["VX-548 Placebo", "Suzetrigine (Journavx)", "suzetrigine 100mg", "JOURNAVX®",
         "Seasonal influenza vaccine", "Formerly known as STx-02", "SUZ",
         "scAAVrh74.MHCK7.hSGCB, bidridistrogene xeboparvovec",
         "Long-Term Follow-up Study of patients who received BEAM-101"],
        known=["suzetrigine", "VX-548"])
    assert got == ["Journavx", "STx-02", "scAAVrh74.MHCK7.hSGCB",
                   "bidridistrogene xeboparvovec"]


def test_investigator_and_phase4_trials_are_not_catalysts():
    assert ingest_mol.material_trial("search", "INDUSTRY", "P3")
    assert ingest_mol.material_trial("pinned", "OTHER", "P4")          # you pinned it
    assert not ingest_mol.material_trial("search", "OTHER", "P3")      # university-run
    assert not ingest_mol.material_trial("search", "INDUSTRY", "P4")
    assert not ingest_mol.material_trial("search", "INDUSTRY", "NA")
    assert ingest_mol.material_trial("search", None, "P2")             # class unknown
    assert ingest_mol.material_trial("search", float("nan"), "P2")     # NULL read back as NaN
