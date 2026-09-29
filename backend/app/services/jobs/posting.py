"""Job posting: constrained vocabularies, cross-field validation, normalization and display strings.

One place defines the rules; the API validates with it and the UI mirrors it. Money is stored as absolute amounts with a currency and a
period (no India-only column); 'LPA' is only an input/display convenience for INR per year (1 LPA = 100,000 INR).
"""

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

EMPLOYMENT_TYPES = {"FULL_TIME": "Full-time", "INTERNSHIP": "Internship", "INTERNSHIP_TO_FULL_TIME": "Internship → Full-time",
                    "PART_TIME": "Part-time", "CONTRACT": "Contract"}
WORK_MODES = {"ONSITE": "On-site", "HYBRID": "Hybrid", "REMOTE": "Remote"}
PERIODS = ("YEAR", "MONTH", "HOUR", "FIXED")
COMP_TYPES = ("SALARY", "STIPEND", "CTC", "HOURLY", "UNPAID")
DURATION_UNITS = ("WEEK", "MONTH")
INTERNSHIP_TYPES = {"INTERNSHIP", "INTERNSHIP_TO_FULL_TIME"}
LPA = Decimal(100_000)
SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


class PostingError(ValueError):
    pass


def _d(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def to_absolute(amount, unit: str | None, currency: str | None, period: str | None) -> Decimal | None:
    """Converts an entered amount to an absolute amount. LPA means lakh rupees per year, so it needs INR and YEAR."""
    a = _d(amount)
    if a is None:
        return None
    if unit == "LPA":
        if currency != "INR" or period not in (None, "YEAR"):
            raise PostingError("LPA is only valid for INR per year")
        return (a * LPA).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return a.quantize(Decimal("0.01"), ROUND_HALF_UP)


def validate_posting(v: dict) -> dict:
    """v: normalized-input dict (absolute amounts already). Raises PostingError with a readable message; returns v with derived fields."""
    et, wm = v.get("employment_type"), v.get("work_mode")
    if et is not None and et not in EMPLOYMENT_TYPES:
        raise PostingError(f"employment_type must be one of {sorted(EMPLOYMENT_TYPES)}")
    if wm is not None and wm not in WORK_MODES:
        raise PostingError(f"work_mode must be one of {sorted(WORK_MODES)}")
    internship = et in INTERNSHIP_TYPES
    dv, du = v.get("internship_duration_value"), v.get("internship_duration_unit")
    ft_min, ft_max = v.get("full_time_compensation_min"), v.get("full_time_compensation_max")
    if internship:
        if dv is None or du is None:
            raise PostingError("Internships need a duration (value and unit)")
        if dv < 1 or dv > 60:
            raise PostingError("Internship duration must be between 1 and 60")
        if du not in DURATION_UNITS:
            raise PostingError(f"internship_duration_unit must be one of {list(DURATION_UNITS)}")
    else:
        if dv is not None or du is not None:
            raise PostingError("Internship duration is only valid for internship roles")
    if et != "INTERNSHIP_TO_FULL_TIME":
        if ft_min is not None or ft_max is not None or v.get("conversion_notes") or v.get("conversion_guaranteed"):
            raise PostingError("Full-time package and conversion details are only valid for Internship → Full-time roles")
    elif ft_min is not None and ft_max is not None and ft_min > ft_max:
        raise PostingError("Full-time package minimum cannot exceed the maximum")
    if ft_min is not None and ft_min < 0 or ft_max is not None and ft_max < 0:
        raise PostingError("Full-time package cannot be negative")
    if v.get("conversion_guaranteed") and not v.get("conversion_notes"):
        raise PostingError("Explain the conversion guarantee in the conversion notes")

    if wm in ("ONSITE", "HYBRID") and not (v.get("location_city") and v.get("location_country")):
        raise PostingError("On-site and hybrid roles need a city and country")

    lvl = v.get("experience_level")
    if lvl is not None and lvl not in ("FRESHER", "EXPERIENCED"):
        raise PostingError("experience_level must be FRESHER or EXPERIENCED")
    emin, emax = v.get("experience_min_years"), v.get("experience_max_years")
    if lvl == "FRESHER" and (emin is not None or emax is not None):
        raise PostingError("A fresher role has no years-of-experience range")
    if emin is not None and emin < 0 or emax is not None and emax < 0:
        raise PostingError("Experience cannot be negative")
    if emin is not None and emax is not None and emin > emax:
        raise PostingError("Minimum experience cannot exceed the maximum")

    n = v.get("number_of_openings")
    if n is not None and n < 1:
        raise PostingError("Number of openings must be at least 1")

    cmin, cmax = v.get("compensation_min"), v.get("compensation_max")
    ctype, cper, cur = v.get("compensation_type"), v.get("compensation_period"), v.get("compensation_currency")
    if ctype is not None and ctype not in COMP_TYPES:
        raise PostingError(f"compensation_type must be one of {list(COMP_TYPES)}")
    if cper is not None and cper not in PERIODS:
        raise PostingError(f"compensation_period must be one of {list(PERIODS)}")
    if ctype == "UNPAID":
        if (cmin or 0) or (cmax or 0):
            raise PostingError("An unpaid role has no compensation amount")
    elif cmin is not None or cmax is not None:
        if not (cur and len(cur) == 3 and cur.isalpha()):
            raise PostingError("Choose a 3-letter currency")
        if cper is None or ctype is None:
            raise PostingError("Compensation needs a period and a type")
        if cmin is not None and cmin < 0 or cmax is not None and cmax < 0:
            raise PostingError("Compensation cannot be negative")
        if cmin is not None and cmax is not None and cmin > cmax:
            raise PostingError("Minimum compensation cannot exceed the maximum")
    if internship and ctype in ("SALARY", "CTC", "HOURLY") and (cmin is not None or cmax is not None):
        raise PostingError("Internship pay is a stipend (or unpaid)")
    if not internship and ctype in ("STIPEND",):
        raise PostingError("A stipend is only valid for internship roles")

    dl = v.get("application_deadline")
    if dl is not None and dl.tzinfo is None:
        raise PostingError("application_deadline needs a timezone")
    return v


def missing_for_publish(job) -> list[str]:
    miss = []
    if not job.employment_type:
        miss.append("employment_type")
    if not job.work_mode:
        miss.append("work_mode")
    elif job.work_mode in ("ONSITE", "HYBRID"):
        miss += [f for f, val in (("location_city", job.location_city), ("location_country", job.location_country)) if not val]
    return miss


def _num(x: Decimal) -> str:
    return f"{x.normalize():f}" if x == x.to_integral() else f"{x:.2f}".rstrip("0").rstrip(".")


def _money(x: Decimal, currency: str, period: str | None) -> str:
    sym = SYMBOLS.get(currency, currency + " ")
    if currency == "INR" and period == "YEAR" and x >= LPA:
        return f"{sym}{_num(x / LPA)}"
    if currency == "INR":
        s = f"{int(x):,}"  # Indian digit grouping
        head, tail = s.replace(",", ""), ""
        if len(head) > 3:
            body, last3 = head[:-3], head[-3:]
            groups = []
            while len(body) > 2:
                groups.insert(0, body[-2:])
                body = body[:-2]
            if body:
                groups.insert(0, body)
            s = ",".join(groups + [last3])
        return f"{sym}{s}"
    return f"{sym}{int(x):,}" if x == x.to_integral() else f"{sym}{x:,.2f}"


def format_range(lo, hi, currency: str, period: str | None) -> str | None:
    lo, hi = _d(lo), _d(hi)
    if lo is None and hi is None:
        return None
    lpa = currency == "INR" and period == "YEAR" and all(x is None or x >= LPA for x in (lo, hi))
    a = _money(lo if lo is not None else hi, currency, period)
    if lo is not None and hi is not None and lo != hi:
        b = _money(hi, currency, period)
        text = f"{a}–{b.lstrip('₹$€£') if b[0] in '₹$€£' and a[0] == b[0] else b}"
    else:
        text = a
    return f"{text} LPA" if lpa else text


PERIOD_SUFFIX = {"YEAR": "/year", "MONTH": "/month", "HOUR": "/hour", "FIXED": " (fixed)"}


def display(job) -> dict:
    """Human strings computed from the stored values; null fields produce None (never a fake default)."""
    d: dict = {"employment_type_label": EMPLOYMENT_TYPES.get(job.employment_type), "work_mode_label": WORK_MODES.get(job.work_mode)}
    parts = [p for p in (job.location_city, job.location_state, job.location_country) if p]
    d["location"] = ", ".join(parts) if parts else (job.location or None)
    comp = None
    cur = job.compensation_currency
    if job.compensation_type == "UNPAID":
        comp = "Unpaid"
    elif cur and (job.compensation_min is not None or job.compensation_max is not None):
        rng = format_range(job.compensation_min, job.compensation_max, cur, job.compensation_period)
        lpa = rng.endswith(" LPA")
        suffix = "" if lpa else PERIOD_SUFFIX.get(job.compensation_period, "")
        comp = rng + suffix + (" stipend" if job.compensation_type == "STIPEND" else " CTC" if job.compensation_type == "CTC" and not lpa else "")
    d["compensation"] = comp
    d["internship_duration"] = (f"{job.internship_duration_value} {job.internship_duration_unit.lower()}{'s' if job.internship_duration_value != 1 else ''}"
                                if job.internship_duration_value and job.internship_duration_unit else None)
    ft = None
    if cur and (job.full_time_compensation_min is not None or job.full_time_compensation_max is not None):
        ft = format_range(job.full_time_compensation_min, job.full_time_compensation_max, cur, "YEAR")
        if ft and not ft.endswith(" LPA"):
            ft += "/year"
    d["full_time_package"] = ft
    d["conversion"] = (None if job.employment_type != "INTERNSHIP_TO_FULL_TIME"
                       else "Full-time conversion guaranteed" if job.conversion_guaranteed else "Potential full-time conversion")
    if job.experience_level == "FRESHER":
        d["experience"] = "Fresher"
    elif job.experience_min_years is not None or job.experience_max_years is not None:
        lo, hi = job.experience_min_years, job.experience_max_years
        d["experience"] = (f"{lo}–{hi} years" if lo is not None and hi is not None else f"{lo}+ years" if lo is not None else f"Up to {hi} years")
    else:
        d["experience"] = None
    dl = job.application_deadline
    d["application_deadline"] = dl.isoformat() if dl else None
    d["applications_open"] = dl is None or dt.datetime.now(dt.timezone.utc) <= dl
    d["headline"] = " · ".join(x for x in (d["employment_type_label"], d["work_mode_label"], d["location"]) if x) or None
    return d
