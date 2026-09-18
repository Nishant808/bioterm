from bioterm.ingest.clinical import _keep


def _row(**over):
    base = {
        "study_type": "INTERVENTIONAL",
        "phase": "P1",
        "status": "RECRUITING",
        "title": "",
        "conditions": "",
    }
    base.update(over)
    return base


def test_drops_pure_pk_housekeeping_in_healthy_volunteers():
    row = _row(
        title="A Pharmacokinetic Study of Drug X in Healthy Volunteers",
        conditions="Healthy Volunteers",
    )
    assert _keep(row) is False


def test_keeps_phase1_with_pk_language_but_efficacy_in_patients():
    # PK is a routine secondary endpoint even on a real first-in-human study -
    # the efficacy language in the title should override the housekeeping guess.
    row = _row(
        title="A Study for Relative Bioavailability and Preliminary Efficacy "
              "of Drug X in Patients With NASH",
        conditions="NASH",
    )
    assert _keep(row) is True


def test_keeps_phase1_with_pk_language_but_real_named_condition():
    row = _row(
        title="Pharmacokinetics and Safety of Drug X",
        conditions="Non-Small Cell Lung Cancer",
    )
    assert _keep(row) is True


def test_drops_hepatic_impairment_special_population_study():
    row = _row(
        title="A Study to Assess Pharmacokinetics of Drug X in Subjects With "
              "Hepatic Impairment",
        conditions="Hepatic Impairment",
    )
    assert _keep(row) is False


def test_phase3_with_pk_language_is_never_excluded():
    row = _row(
        phase="P3",
        title="A Pharmacokinetic Bridging Study for Drug X",
        conditions="",
    )
    assert _keep(row) is True


def test_non_interventional_still_dropped():
    row = _row(study_type="OBSERVATIONAL")
    assert _keep(row) is False


def test_inactive_status_still_dropped():
    row = _row(status="WITHDRAWN")
    assert _keep(row) is False


def test_ordinary_phase1_efficacy_study_unaffected():
    row = _row(title="A Study of Drug X in Patients With Advanced Solid Tumors",
               conditions="Advanced Solid Tumors")
    assert _keep(row) is True
