"""A problem reworded under a sibling skill is still a duplicate (tenant-scoped,
not skill-scoped), while a genuinely different problem is not."""
import pytest

from app.core.database import AsyncSessionLocal
from app.services.questions import importer
from tests.factories import make_company, uniq

BASE = ("Given a list of integers, find the length of the longest subarray where the absolute difference between any two "
        "elements is at most 1. The input is a single line containing a list literal (e.g., [1,2,2,3,1,2]). {tail} [{tag}]")
TC = [{"input": "[1,2,2,3,1,2]", "expected_output": "5"}, {"input": "[4]", "expected_output": "1"}]


@pytest.mark.asyncio
async def test_cross_skill_near_duplicate_is_flagged_but_different_problem_is_not():
    tag = uniq("dedupe")
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        await db.commit()
        rows = [
            {"question_text": BASE.format(tail="Print the length of the longest such subarray.", tag=tag),
             "question_type": "CODING", "skill": "Data Structures", "test_cases": TC},
            {"question_text": BASE.format(tail="Your program should output the maximum length of such a subarray.", tag=tag),
             "question_type": "CODING", "skill": "Algorithms", "test_cases": TC},
            {"question_text": (f"Given a list of integers, print the length of the longest contiguous subarray whose sum is zero, "
                               f"or 0 if none exists. The input is one line with a list literal. [{tag}]"),
             "question_type": "CODING", "skill": "Algorithms", "test_cases": [{"input": "[1,-1]", "expected_output": "2"},
                                                                               {"input": "[5]", "expected_output": "0"}]},
        ]
        report = await importer.import_rows(db, rows, organization_id=org.id, created_by=rec.id, platform=False)
        await db.commit()
    assert len(report.created) == 2, report
    assert [d["row"] for d in report.duplicates] == [1]  # the Algorithms rewording of row 0
