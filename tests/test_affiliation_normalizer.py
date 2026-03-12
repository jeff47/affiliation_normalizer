from __future__ import annotations

import pytest

from affiliation_normalizer import (
    AffiliationNormalizer,
    match_affiliation,
    match_email_domain,
    match_grid,
    match_record,
    match_ror,
)
from affiliation_normalizer.build_rules import normalize_text as build_normalize_text
from affiliation_normalizer.matcher import DEFAULT_RULES_PATH, normalize_text


def _normalizer() -> AffiliationNormalizer:
    return AffiliationNormalizer.from_rules_json(DEFAULT_RULES_PATH)


def test_matches_yale_affiliation() -> None:
    normalizer = _normalizer()
    result = normalizer.match(
        "Yale Cancer Center, Yale University, New Haven, CT, USA. david.calderwood@yale.edu."
    )
    assert result.status == "matched"
    assert result.canonical_id == "us-ct-yale-university"
    assert result.canonical_name == "Yale University"
    assert result.standardized_name == "Yale University, New Haven, CT"
    assert result.state == "CT"


def test_matches_yale_school_of_medicine_subunit_affiliation() -> None:
    normalizer = _normalizer()
    result = normalizer.match(
        "Department of Medicine, Section of Infectious Diseases, Yale School of Medicine, "
        "New Haven, Connecticut, USA."
    )
    assert result.status == "matched"
    assert result.canonical_id == "us-ct-yale-university"
    assert result.canonical_name == "Yale University"


def test_matches_weill_cornell_medical_college_legacy_alias() -> None:
    normalizer = _normalizer()
    result = normalizer.match("Weill Cornell Medical College, New York, NY, USA.")
    assert result.status == "matched"
    assert result.canonical_id == "us-ny-weill-cornell-medicine"
    assert result.canonical_name == "Weill Cornell Medicine"


def test_nyu_grossman_and_legacy_variants_resolve_to_nyu_grossman() -> None:
    normalizer = _normalizer()

    for text in (
        "New York University Grossman School of Medicine",
        "New York University School of Medicine",
        "NYU Grossman School of Medicine",
        "NYU School of Medicine",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-ny-new-york-university-school-of-medicine"
        assert result.canonical_name == "New York University Grossman School of Medicine"


def test_unc_chapel_hill_at_variant_resolves() -> None:
    normalizer = _normalizer()

    for text in (
        "University of North Carolina at Chapel Hill",
        "The University of North Carolina at Chapel Hill, Chapel Hill, NC, USA.",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-nc-university-of-north-carolina-chapel-hill"
        assert result.canonical_name == "University of North Carolina Chapel Hill"


def test_fred_hutchinson_cancer_center_renamed_variant_resolves() -> None:
    normalizer = _normalizer()
    result = normalizer.match("Fred Hutchinson Cancer Center, Seattle, WA, USA.")
    assert result.status == "matched"
    assert result.canonical_id == "us-wa-fred-hutchinson-cancer-research-center"
    assert result.canonical_name == "Fred Hutchinson Cancer Research Center"


def test_chop_full_name_and_acronym_resolve() -> None:
    normalizer = _normalizer()

    for text in (
        "Children's Hospital of Philadelphia",
        "The Children's Hospital of Philadelphia, Philadelphia, PA, USA.",
        "CHOP",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-pa-children-s-hosp-of-philadelphia"
        assert result.canonical_name == "Children's Hosp of Philadelphia"


def test_icahn_school_of_medicine_short_form_resolves() -> None:
    normalizer = _normalizer()

    for text in (
        "Icahn school of medicine",
        "Icahn School of Medicine, New York, NY, USA.",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-ny-icahn-school-of-medicine-at-mount-sinai"
        assert result.canonical_name == "Icahn School of Medicine at Mount Sinai"


def test_precedence_brigham_over_harvard() -> None:
    normalizer = _normalizer()
    result = normalizer.match(
        "Division of Rheumatology, Brigham and Women's Hospital and Harvard Medical School, Boston, MA, USA."
    )
    assert result.status == "matched"
    assert result.canonical_id == "us-ma-brigham-and-women-s-hospital"


def test_precedence_mgh_over_harvard() -> None:
    normalizer = _normalizer()
    result = normalizer.match(
        "Department of Neurology, Massachusetts General Hospital, Harvard Medical School, Boston, MA, USA."
    )
    assert result.status == "matched"
    assert result.canonical_id == "us-ma-massachusetts-general-hospital"


def test_returns_ambiguous_for_multiple_unresolved_candidates() -> None:
    normalizer = _normalizer()
    result = normalizer.match(
        "Albany Medical College and Harvard Medical School, USA."
    )
    assert result.status == "ambiguous"
    assert "us-ma-harvard-university" in result.candidate_ids
    assert "us-ny-albany-medical-college" in result.candidate_ids


def test_returns_not_found_for_non_seed_foreign_affiliation() -> None:
    normalizer = _normalizer()
    result = normalizer.match(
        "Department of Clinical Medicine, University of Copenhagen, Copenhagen, Denmark."
    )
    assert result.status == "not_found"


def test_manual_alias_variants_match_existing_canonical_institutions() -> None:
    normalizer = _normalizer()

    harvard = normalizer.match("HARVARD UNIVERSITY D/B/A HARVARD SCHOOL OF PUBLIC HEALTH, Boston, MA")
    assert harvard.status == "matched"
    assert harvard.canonical_id == "us-ma-harvard-university"

    bu = normalizer.match("BOSTON UNIVERSITY (CHARLES RIVER CAMPUS), Boston, MA")
    assert bu.status == "matched"
    assert bu.canonical_id == "us-ma-boston-university"


def test_new_seed_institution_hss_matches() -> None:
    normalizer = _normalizer()

    hss = normalizer.match("Hospital for Special Surgery, New York, NY")
    assert hss.status == "matched"
    assert hss.canonical_id == "us-ny-hospital-for-special-surgery"


def test_penn_state_college_of_medicine_variants_resolve_to_hershey() -> None:
    normalizer = _normalizer()

    for text in (
        "Penn State College of Medicine",
        "Penn State Milton S. Hershey Medical Center",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-pa-pennsylvania-state-university-hershey-medical-center"
        assert result.canonical_name == "Pennsylvania State University Hershey Medical Center"


def test_albert_einstein_school_of_medicine_resolves_to_college_of_medicine() -> None:
    normalizer = _normalizer()
    result = normalizer.match("Albert Einstein School of Medicine")
    assert result.status == "matched"
    assert result.canonical_id == "us-ny-albert-einstein-college-of-medicine"
    assert result.canonical_name == "Albert Einstein College of Medicine"


def test_baylor_school_of_medicine_resolves_to_baylor_college_of_medicine() -> None:
    normalizer = _normalizer()
    result = normalizer.match("Baylor School of Medicine")
    assert result.status == "matched"
    assert result.canonical_id == "us-tx-baylor-college-of-medicine"
    assert result.canonical_name == "Baylor College of Medicine"


def test_caltech_resolves_to_california_institute_of_technology() -> None:
    normalizer = _normalizer()
    result = normalizer.match("Caltech")
    assert result.status == "matched"
    assert result.canonical_id == "us-ca-california-institute-of-technology"
    assert result.canonical_name == "California Institute of Technology"


def test_virginia_tech_resolves_to_virginia_polytechnic_institute() -> None:
    normalizer = _normalizer()
    result = normalizer.match("Virginia Tech")
    assert result.status == "matched"
    assert result.canonical_id == "us-va-virginia-polytechnic-institute"
    assert result.canonical_name == "Virginia Polytechnic Institute"


def test_university_of_new_mexico_health_science_center_resolves_to_health_sciences_center() -> None:
    normalizer = _normalizer()
    result = normalizer.match("University of New Mexico Health Science Center")
    assert result.status == "matched"
    assert result.canonical_id == "us-nm-university-of-new-mexico-health-sciences-center"
    assert result.canonical_name == "University of New Mexico Health Sciences Center"


def test_johns_hopkins_medicine_seed_and_aliases_match() -> None:
    normalizer = _normalizer()

    for text in (
        "Johns Hopkins University School of Medicine",
        "Johns Hopkins  School of Medicine",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-md-johns-hopkins-medicine"
        assert result.canonical_name == "Johns Hopkins Medicine"

    ror_result = normalizer.match_ror("037zgn354")
    assert ror_result.status == "matched"
    assert ror_result.canonical_id == "us-md-johns-hopkins-medicine"

    grid_result = normalizer.match_grid("grid.469474.c")
    assert grid_result.status == "matched"
    assert grid_result.canonical_id == "us-md-johns-hopkins-medicine"


def test_new_seed_eastern_virginia_medical_school_matches() -> None:
    normalizer = _normalizer()

    text_result = normalizer.match("Eastern Virginia Medical School")
    assert text_result.status == "matched"
    assert text_result.canonical_id == "us-va-eastern-virginia-medical-school"
    assert text_result.canonical_name == "Eastern Virginia Medical School"

    ror_result = normalizer.match_ror("056hr4255")
    assert ror_result.status == "matched"
    assert ror_result.canonical_id == "us-va-eastern-virginia-medical-school"

    grid_result = normalizer.match_grid("grid.255414.3")
    assert grid_result.status == "matched"
    assert grid_result.canonical_id == "us-va-eastern-virginia-medical-school"


def test_feinstein_plural_variant_resolves() -> None:
    normalizer = _normalizer()
    result = normalizer.match(
        "Center for Autoimmune Musculoskeletal and Hematopoietic Diseases, "
        "The Feinstein Institutes for Medical Research, Manhasset, NY."
    )
    assert result.status == "matched"
    assert result.canonical_id == "us-ny-feinstein-institute-for-medical-research"
    assert result.canonical_name == "Feinstein Institute for Medical Research"


def test_harvard_th_chan_variants_resolve_to_subunit_not_global_harvard() -> None:
    normalizer = _normalizer()

    for text in (
        "Harvard T.H. Chan School of Public Health",
        "Harvard T. H. Chan School of Public Health",
        "Harvard TH Chan School of Public Health",
        "Harvard T. H. Chan School of Public Health, Harvard University, Boston, MA",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-ma-harvard-th-chan-school-of-public-health"
        assert result.canonical_name == "Harvard T. H. Chan School of Public Health"


def test_new_seed_rensselaer_polytechnic_institute_matches() -> None:
    normalizer = _normalizer()

    text_result = normalizer.match("Rensselaer Polytechnic Institute")
    assert text_result.status == "matched"
    assert text_result.canonical_id == "us-ny-rensselaer-polytechnic-institute"
    assert text_result.canonical_name == "Rensselaer Polytechnic Institute"

    ror_result = normalizer.match_ror("01rtyzb94")
    assert ror_result.status == "matched"
    assert ror_result.canonical_id == "us-ny-rensselaer-polytechnic-institute"

    grid_result = normalizer.match_grid("grid.33647.35")
    assert grid_result.status == "matched"
    assert grid_result.canonical_id == "us-ny-rensselaer-polytechnic-institute"


def test_barbara_davis_center_variants_resolve_to_uc_anschutz() -> None:
    normalizer = _normalizer()

    for text in (
        "Barbara Davis Center for Diabetes",
        "Barbara Davis Center for Childhood Diabetes",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-co-university-of-colorado-anschutz-medical-campus"
        assert result.canonical_name == "University of Colorado Anschutz Medical Campus"


def test_university_of_colorado_aurora_variants_resolve_to_uc_anschutz_not_boulder() -> None:
    normalizer = _normalizer()

    for text in (
        "University of Colorado in Aurora",
        "University of Colorado, Aurora",
        "University of Colorado at Aurora",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-co-university-of-colorado-anschutz-medical-campus"
        assert result.canonical_name == "University of Colorado Anschutz Medical Campus"


def test_new_seed_ragon_institute_matches_by_text_and_identifiers() -> None:
    normalizer = _normalizer()

    text_result = normalizer.match("Ragon Institute of MGH, MIT and Harvard")
    assert text_result.status == "matched"
    assert text_result.canonical_id == "us-ma-ragon-institute-of-mgh-mit-and-harvard"
    assert text_result.canonical_name == "Ragon Institute of MGH, MIT and Harvard"

    ror_result = normalizer.match_ror("053r20n13")
    assert ror_result.status == "matched"
    assert ror_result.canonical_id == "us-ma-ragon-institute-of-mgh-mit-and-harvard"

    grid_result = normalizer.match_grid("grid.461656.6")
    assert grid_result.status == "matched"
    assert grid_result.canonical_id == "us-ma-ragon-institute-of-mgh-mit-and-harvard"


def test_ragon_institute_precedence_over_mgh_mit_harvard() -> None:
    normalizer = _normalizer()

    for text in (
        "Ragon Institute, MGH, MIT and Harvard, Cambridge, MA",
        "Ragon Institute of Mass General Brigham, MIT, and Harvard, Cambridge, MA 02139, USA.",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-ma-ragon-institute-of-mgh-mit-and-harvard"
        assert result.canonical_name == "Ragon Institute of MGH, MIT and Harvard"


def test_broad_institute_precedence_over_harvard_and_mit() -> None:
    normalizer = _normalizer()

    for text in (
        "Broad Institute of Harvard and MIT",
        "Broad Institute of Harvard and Massachusetts Institute of Technology",
        "Broad Institute, Harvard University, Cambridge, MA",
        "Broad Institute, Massachusetts Institute of Technology, Cambridge, MA",
    ):
        result = normalizer.match(text)
        assert result.status == "matched"
        assert result.canonical_id == "us-ma-broad-institute"
        assert result.canonical_name == "Broad Institute"


def test_matches_ror_bare_id() -> None:
    normalizer = _normalizer()

    result = normalizer.match_ror("03v76x132")
    assert result.status == "matched"
    assert result.canonical_id == "us-ct-yale-university"
    assert result.canonical_name == "Yale University"


def test_matches_ror_url() -> None:
    result = match_ror("https://ror.org/03v76x132")
    assert result.status == "matched"
    assert result.canonical_id == "us-ct-yale-university"


def test_returns_not_found_for_unknown_ror() -> None:
    normalizer = _normalizer()

    result = normalizer.match_ror("https://ror.org/000000000")
    assert result.status == "not_found"
    assert result.reason == "no_ror_match"


def test_matches_grid_bare_id() -> None:
    normalizer = _normalizer()

    result = normalizer.match_grid("grid.47100.32")
    assert result.status == "matched"
    assert result.canonical_id == "us-ct-yale-university"
    assert result.canonical_name == "Yale University"
    assert result.grid_id == "grid.47100.32"


def test_matches_grid_url() -> None:
    result = match_grid("https://www.grid.ac/institutes/grid.47100.32")
    assert result.status == "matched"
    assert result.canonical_id == "us-ct-yale-university"


def test_returns_not_found_for_unknown_grid() -> None:
    normalizer = _normalizer()

    result = normalizer.match_grid("grid.000000.0")
    assert result.status == "not_found"
    assert result.reason == "no_grid_match"


def test_maps_grid_id_to_bloomington() -> None:
    normalizer = _normalizer()

    result = normalizer.match_grid("grid.257410.5")
    assert result.status == "matched"
    assert result.reason == "grid_match"
    assert result.canonical_id == "us-in-indiana-university-bloomington"


def test_matches_email_domain_from_full_email() -> None:
    rules = {
        "institutions": {
            "inst-a": {
                "canonical_id": "inst-a",
                "canonical_name": "Alpha University",
                "city": "Alpha City",
                "state": "AA",
                "country": "US",
                "ror_id": "",
                "grid_id": "",
                "email_domains": "alpha.edu",
                "openalex_id": "",
            }
        },
        "alias_rules": [],
        "precedence_rules": [],
    }
    normalizer = AffiliationNormalizer(rules)

    result = normalizer.match_email_domain("person@dept.alpha.edu")
    assert result.status == "matched"
    assert result.canonical_id == "inst-a"
    assert result.reason == "email_domain_match"


def test_email_domain_disambiguates_alias_candidates() -> None:
    rules = {
        "institutions": {
            "inst-a": {
                "canonical_id": "inst-a",
                "canonical_name": "Alpha University",
                "city": "Alpha City",
                "state": "AA",
                "country": "US",
                "ror_id": "",
                "grid_id": "",
                "email_domains": "alpha.edu",
                "openalex_id": "",
            },
            "inst-b": {
                "canonical_id": "inst-b",
                "canonical_name": "Beta Institute",
                "city": "Beta City",
                "state": "BB",
                "country": "US",
                "ror_id": "",
                "grid_id": "",
                "email_domains": "beta.edu",
                "openalex_id": "",
            },
        },
        "alias_rules": [
            {
                "alias": "Medical Center",
                "alias_norm": "medical center",
                "canonical_id": "inst-a",
                "alias_type": "manual_alias",
                "policy": "allow",
            },
            {
                "alias": "Medical Center",
                "alias_norm": "medical center",
                "canonical_id": "inst-b",
                "alias_type": "manual_alias",
                "policy": "allow",
            },
        ],
        "precedence_rules": [],
    }
    normalizer = AffiliationNormalizer(rules)

    result = normalizer.match("Medical Center, contact: jane@dept.beta.edu")
    assert result.status == "matched"
    assert result.canonical_id == "inst-b"
    assert result.reason == "email_domain_match"


def test_module_match_email_domain_no_match_with_default_rules() -> None:
    result = match_email_domain("example.org")
    assert result.status == "not_found"
    assert result.reason == "no_email_domain_match"


def test_email_match_has_priority_over_text_match() -> None:
    rules = {
        "institutions": {
            "inst-a": {
                "canonical_id": "inst-a",
                "canonical_name": "Alpha University",
                "city": "Alpha City",
                "state": "AA",
                "country": "US",
                "ror_id": "",
                "grid_id": "",
                "email_domains": "",
                "openalex_id": "",
            },
            "inst-b": {
                "canonical_id": "inst-b",
                "canonical_name": "Beta Institute",
                "city": "Beta City",
                "state": "BB",
                "country": "US",
                "ror_id": "",
                "grid_id": "",
                "email_domains": "beta.edu",
                "openalex_id": "",
            },
        },
        "alias_rules": [
            {
                "alias": "Alpha University",
                "alias_norm": "alpha university",
                "canonical_id": "inst-a",
                "alias_type": "manual_alias",
                "policy": "allow",
            }
        ],
        "precedence_rules": [],
    }
    normalizer = AffiliationNormalizer(rules)

    result = normalizer.match("Alpha University, contact: person@beta.edu")
    assert result.status == "matched"
    assert result.canonical_id == "inst-b"
    assert result.reason == "email_domain_match"


def test_match_record_applies_identifier_email_text_priority() -> None:
    rules = {
        "institutions": {
            "inst-ror": {
                "canonical_id": "inst-ror",
                "canonical_name": "ROR Institution",
                "city": "City R",
                "state": "RR",
                "country": "US",
                "ror_id": "03v76x132",
                "grid_id": "",
                "email_domains": "",
                "openalex_id": "",
            },
            "inst-grid": {
                "canonical_id": "inst-grid",
                "canonical_name": "GRID Institution",
                "city": "City G",
                "state": "GG",
                "country": "US",
                "ror_id": "",
                "grid_id": "grid.47100.32",
                "email_domains": "",
                "openalex_id": "",
            },
            "inst-email": {
                "canonical_id": "inst-email",
                "canonical_name": "Email Institution",
                "city": "City E",
                "state": "EE",
                "country": "US",
                "ror_id": "",
                "grid_id": "",
                "email_domains": "email.edu",
                "openalex_id": "",
            },
            "inst-text": {
                "canonical_id": "inst-text",
                "canonical_name": "Text Institution",
                "city": "City T",
                "state": "TT",
                "country": "US",
                "ror_id": "",
                "grid_id": "",
                "email_domains": "",
                "openalex_id": "",
            },
        },
        "alias_rules": [
            {
                "alias": "Text Institution",
                "alias_norm": "text institution",
                "canonical_id": "inst-text",
                "alias_type": "manual_alias",
                "policy": "allow",
            }
        ],
        "precedence_rules": [],
    }
    normalizer = AffiliationNormalizer(rules)

    ror_result = normalizer.match_record(
        affiliation_text="Text Institution",
        ror_id="03v76x132",
        grid_id="grid.47100.32",
        email="person@email.edu",
    )
    assert ror_result.status == "matched"
    assert ror_result.canonical_id == "inst-ror"
    assert ror_result.reason == "ror_match"

    grid_result = normalizer.match_record(
        affiliation_text="Text Institution",
        grid_id="grid.47100.32",
        email="person@email.edu",
    )
    assert grid_result.status == "matched"
    assert grid_result.canonical_id == "inst-grid"
    assert grid_result.reason == "grid_match"

    email_result = normalizer.match_record(
        affiliation_text="Text Institution",
        email="person@email.edu",
    )
    assert email_result.status == "matched"
    assert email_result.canonical_id == "inst-email"
    assert email_result.reason == "email_domain_match"

    text_result = normalizer.match_record(
        affiliation_text="Text Institution",
    )
    assert text_result.status == "matched"
    assert text_result.canonical_id == "inst-text"
    assert text_result.reason == "precedence_or_direct_match"


def test_module_match_record_default_not_found_for_empty_input() -> None:
    result = match_record()
    assert result.status == "not_found"
    assert result.reason == "empty_input"


def test_module_match_affiliation_uses_bundled_rules() -> None:
    result = match_affiliation("Yale University, New Haven, CT")
    assert result.status == "matched"
    assert result.canonical_id == "us-ct-yale-university"


def test_normalize_text_preserves_boundary_for_unicode_dash() -> None:
    assert normalize_text("Harvard Medical School–Brigham") == "harvard medical school brigham"


def test_unicode_dash_and_curly_apostrophe_match_brigham() -> None:
    normalizer = _normalizer()
    result = normalizer.match("Harvard Medical School–Brigham and Women’s Hospital, Boston, MA")
    assert result.status == "matched"
    assert result.canonical_id == "us-ma-brigham-and-women-s-hospital"


@pytest.mark.parametrize(
    ("input_text", "expected_norm"),
    [
        ("Harvard Medical School–Brigham", "harvard medical school brigham"),
        ("Harvard Medical School—Brigham", "harvard medical school brigham"),
        ("Harvard Medical School‑Brigham", "harvard medical school brigham"),
        ("Brigham and Women’s Hospital", "brigham and womens hospital"),
        ("Brigham and Women's Hospital", "brigham and womens hospital"),
        ("O’Neill Institute", "oneill institute"),
        ("O'Neill Institute", "oneill institute"),
    ],
)
def test_normalize_text_unicode_variants(input_text: str, expected_norm: str) -> None:
    assert normalize_text(input_text) == expected_norm


@pytest.mark.parametrize(
    "input_text",
    [
        "Harvard Medical School–Brigham and Women’s Hospital",
        "Harvard Medical School—Brigham and Women's Hospital",
        "O’Neill Institute for National and Global Health Law",
        "UC–San Diego",
    ],
)
def test_build_and_runtime_normalize_text_parity(input_text: str) -> None:
    assert normalize_text(input_text) == build_normalize_text(input_text)
