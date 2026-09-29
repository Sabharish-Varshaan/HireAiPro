"""Execution-based verification of coding-question test cases.

LLM-written expected outputs are not trusted: in QA (2026-09-29) all three
generated coding questions of one assessment had wrong expected outputs, so
correct student code failed. A second, independent model call sees ONLY the
problem statement (never the tests) and writes a Python reference solution;
Judge0 executes it on every test input. The question is usable only if every
executed output equals the stored expected output. If the runner is unavailable
the question cannot be verified and stays DRAFT (fail closed).
"""

from pydantic import BaseModel

from app.services.ai_gateway.gateway import get_ai_gateway


class _Reference(BaseModel):
    solution: str


async def verify_test_cases(question_text: str, test_cases: list[dict], *, related_entity_id=None) -> tuple[bool, str]:
    from app.services.coding.judge0_client import ExecutionUnavailable, get_judge0_client

    ref = await get_ai_gateway().generate_structured(
        "Write a correct, complete Python 3 program for this problem. It reads the input from stdin and prints "
        f"only the answer. Return just the program.\n\nPROBLEM:\n{question_text}",
        _Reference, task_type="coding_reference_solution", related_entity_type="question",
        related_entity_id=related_entity_id,
    )
    try:
        results = await get_judge0_client().run_many(ref.solution, "python", test_cases)
    except ExecutionUnavailable as exc:
        return False, f"could not verify test cases: code runner unavailable ({exc})"
    bad = [i for i, r in enumerate(results) if (r.get("status") or {}).get("id") != 3]
    if bad:
        details = "; ".join(f"test {i + 1}: {(results[i].get('status') or {}).get('description')}" for i in bad)
        return False, f"independent reference solution disagrees with the expected output ({details})"
    return True, f"all {len(results)} expected outputs reproduced by an independent reference solution in Judge0"
