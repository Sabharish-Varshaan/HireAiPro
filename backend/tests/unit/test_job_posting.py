"""Posting rules: vocabularies, conditional validation, INR/LPA normalization, display strings."""
from decimal import Decimal as D
from types import SimpleNamespace as N

import pytest
from pydantic import ValidationError

from app.schemas.jobs import JobCreate
from app.services.jobs.posting import display

BASE = {"title": "Role"}


def mk(**kw):
    return JobCreate(**{**BASE, **kw})


def bad(**kw):
    with pytest.raises(ValidationError) as e:
        mk(**kw)
    return str(e.value)


def test_full_time_lpa_is_normalized_to_absolute_inr_per_year():
    c = mk(employment_type="FULL_TIME", work_mode="HYBRID", location_city="Bengaluru", location_country="India", compensation_currency="INR",
           compensation_min=D("10"), compensation_max=D("14.5"), compensation_period="YEAR", compensation_type="CTC", compensation_input_unit="LPA").columns()
    assert c["compensation_min"] == D("1000000.00") and c["compensation_max"] == D("1450000.00")  # no precision lost


def test_absolute_amounts_are_kept_and_lpa_requires_inr_per_year():
    c = mk(employment_type="FULL_TIME", compensation_currency="USD", compensation_min=D("120000"), compensation_max=D("150000"),
           compensation_period="YEAR", compensation_type="SALARY").columns()
    assert c["compensation_min"] == D("120000.00") and c["compensation_currency"] == "USD"
    assert "LPA is only valid" in bad(employment_type="FULL_TIME", compensation_currency="USD", compensation_min=D("10"), compensation_period="YEAR",
                                      compensation_type="SALARY", compensation_input_unit="LPA")
    assert "LPA is only valid" in bad(employment_type="FULL_TIME", compensation_currency="INR", compensation_min=D("10"), compensation_period="MONTH",
                                      compensation_type="SALARY", compensation_input_unit="LPA")


def test_internship_needs_duration_and_stipend_is_normalized():
    assert "duration" in bad(employment_type="INTERNSHIP")
    c = mk(employment_type="INTERNSHIP", internship_duration_value=6, internship_duration_unit="MONTH", compensation_currency="INR",
           compensation_min=D("30000"), compensation_max=D("30000"), compensation_period="MONTH", compensation_type="STIPEND").columns()
    assert c["internship_duration_value"] == 6 and c["internship_duration_unit"] == "MONTH" and c["compensation_min"] == D("30000.00")
    assert "Internship pay is a stipend" in bad(employment_type="INTERNSHIP", internship_duration_value=3, internship_duration_unit="MONTH",
                                                compensation_currency="INR", compensation_min=D("1000000"), compensation_period="YEAR", compensation_type="SALARY")


def test_internship_to_full_time_carries_package_and_conservative_conversion_wording():
    c = mk(employment_type="INTERNSHIP_TO_FULL_TIME", internship_duration_value=6, internship_duration_unit="MONTH", compensation_currency="INR",
           compensation_min=D("35000"), compensation_max=D("35000"), compensation_period="MONTH", compensation_type="STIPEND",
           full_time_compensation_min=D("10"), full_time_compensation_max=D("12"), full_time_input_unit="LPA").columns()
    assert (c["full_time_compensation_min"], c["full_time_compensation_max"]) == (D("1000000.00"), D("1200000.00"))
    assert "Explain the conversion guarantee" in bad(employment_type="INTERNSHIP_TO_FULL_TIME", internship_duration_value=6, internship_duration_unit="MONTH",
                                                      conversion_guaranteed=True)
    assert "Full-time package minimum" in bad(employment_type="INTERNSHIP_TO_FULL_TIME", internship_duration_value=6, internship_duration_unit="MONTH",
                                              compensation_currency="INR", full_time_compensation_min=D("12"), full_time_compensation_max=D("10"), full_time_input_unit="LPA")


@pytest.mark.parametrize("et", ["FULL_TIME", "PART_TIME", "CONTRACT"])
def test_contradictory_payloads_are_rejected(et):
    assert "only valid for internship" in bad(employment_type=et, internship_duration_value=6, internship_duration_unit="MONTH")
    assert "only valid for Internship → Full-time" in bad(employment_type=et, full_time_compensation_min=D("10"), full_time_input_unit="LPA", compensation_currency="INR")
    assert "stipend is only valid" in bad(employment_type=et, compensation_currency="INR", compensation_min=D("1"), compensation_period="MONTH", compensation_type="STIPEND")


def test_internship_only_types_and_vocabularies():
    assert "employment_type must be one of" in bad(employment_type="Full-time")  # display strings are not identifiers
    assert "work_mode must be one of" in bad(work_mode="Remote")
    assert "only valid for Internship → Full-time" in bad(employment_type="INTERNSHIP", internship_duration_value=3, internship_duration_unit="MONTH", conversion_notes="maybe")


def test_work_mode_and_location_rules():
    assert "city and country" in bad(work_mode="ONSITE")
    assert "city and country" in bad(work_mode="HYBRID", location_city="Pune")
    mk(work_mode="REMOTE")  # remote needs no location
    c = mk(work_mode="ONSITE", location_city=" Hyderabad ", location_state="Telangana", location_country="India").columns()
    assert c["location_city"] == "Hyderabad"


def test_experience_openings_compensation_bounds():
    assert "fresher role has no" in bad(experience_level="FRESHER", experience_min_years=0, experience_max_years=1)
    assert "Minimum experience" in bad(experience_level="EXPERIENCED", experience_min_years=5, experience_max_years=2)
    mk(experience_level="FRESHER")
    assert "at least 1" in bad(number_of_openings=0)
    assert mk(number_of_openings=3).columns()["number_of_openings"] == 3
    assert "Minimum compensation" in bad(employment_type="FULL_TIME", compensation_currency="INR", compensation_min=D("20"), compensation_max=D("10"),
                                         compensation_period="YEAR", compensation_type="CTC", compensation_input_unit="LPA")
    assert "unpaid" in bad(employment_type="INTERNSHIP", internship_duration_value=2, internship_duration_unit="MONTH", compensation_type="UNPAID",
                           compensation_min=D("100"), compensation_currency="INR", compensation_period="MONTH")
    assert "needs a period and a type" in bad(compensation_currency="INR", compensation_min=D("10"))


def _job(**kw):
    base = dict(employment_type=None, work_mode=None, location=None, location_city=None, location_state=None, location_country=None,
                compensation_currency=None, compensation_min=None, compensation_max=None, compensation_period=None, compensation_type=None,
                internship_duration_value=None, internship_duration_unit=None, full_time_compensation_min=None, full_time_compensation_max=None,
                conversion_guaranteed=False, experience_level=None, experience_min_years=None, experience_max_years=None, application_deadline=None)
    return N(**{**base, **kw})


def test_display_strings_match_the_product_examples_and_never_invent_defaults():
    d = display(_job(employment_type="FULL_TIME", work_mode="HYBRID", location_city="Bengaluru", compensation_currency="INR",
                     compensation_min=D(1200000), compensation_max=D(1500000), compensation_period="YEAR", compensation_type="CTC"))
    assert d["headline"] == "Full-time · Hybrid · Bengaluru" and d["compensation"] == "₹12–15 LPA"
    i = display(_job(employment_type="INTERNSHIP_TO_FULL_TIME", work_mode="ONSITE", location_city="Hyderabad", compensation_currency="INR",
                     compensation_min=D(35000), compensation_max=D(35000), compensation_period="MONTH", compensation_type="STIPEND",
                     internship_duration_value=6, internship_duration_unit="MONTH", full_time_compensation_min=D(1000000), full_time_compensation_max=D(1200000)))
    assert i["headline"] == "Internship → Full-time · On-site · Hyderabad"
    assert (i["compensation"], i["internship_duration"], i["full_time_package"]) == ("₹35,000/month stipend", "6 months", "₹10–12 LPA")
    assert i["conversion"] == "Potential full-time conversion"  # not "guaranteed" unless explicitly set
    empty = display(_job())
    assert empty["headline"] is None and empty["work_mode_label"] is None and empty["compensation"] is None and empty["experience"] is None
    assert display(_job(compensation_type="UNPAID"))["compensation"] == "Unpaid"
    assert display(_job(experience_level="FRESHER"))["experience"] == "Fresher"
    assert display(_job(compensation_currency="USD", compensation_min=D(120000), compensation_max=D(150000), compensation_period="YEAR",
                        compensation_type="SALARY"))["compensation"] == "$120,000–150,000/year"
    assert display(_job(compensation_currency="INR", compensation_min=D(150000), compensation_period="MONTH", compensation_type="SALARY"))["compensation"] == "₹1,50,000/month"
