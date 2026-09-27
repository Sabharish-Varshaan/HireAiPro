"""faster-whisper on real synthesized speech (macOS `say`), plus the API
endpoint and the text fallback."""

import shutil
import subprocess
import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.interviews import Interview, InterviewTurn
from app.services.ai_gateway.speech import get_speech_service
from tests.factories import make_application, make_company, make_job, make_student, skill

PHRASE = "Docker containers share the host kernel, while virtual machines run their own operating system."
needs_say = pytest.mark.skipif(shutil.which("say") is None, reason="macOS `say` not available")


@pytest.fixture(scope="module")
def speech_wav(tmp_path_factory):
    out = tmp_path_factory.mktemp("audio") / "answer.wav"
    subprocess.run(["say", "-o", str(out), "--data-format=LEI16@16000", PHRASE], check=True)
    return out


@needs_say
def test_whisper_transcribes_real_speech(speech_wav):
    r = get_speech_service().transcribe(str(speech_wav))
    text = r["text"].lower()
    assert "docker" in text and "kernel" in text and "virtual machine" in text
    assert r["language"] == "en" and r["duration_seconds"] > 2


@needs_say
@pytest.mark.asyncio
async def test_transcribe_endpoint_then_text_path(client, speech_wav):
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        job = await make_job(db, org, rec, [("Docker", "required", 0.5, 1.0)])
        st, _, hs = await make_student(db)
        app_ = await make_application(db, job, st)
        iv = Interview(application_id=app_.id, student_id=st.id, job_id=job.id)
        db.add(iv)
        await db.flush()
        turn = InterviewTurn(interview_id=iv.id, turn_index=0, target_skill_id=(await skill(db, "Docker")).id,
                             question_text="How do containers differ from VMs?", difficulty="easy")
        db.add(turn)
        await db.commit()
    r = await client.post(f"/interviews/turns/{turn.id}/transcribe", headers=hs,
                          files={"audio": ("answer.wav", speech_wav.read_bytes(), "audio/wav")})
    assert r.status_code == 200, r.text
    assert "kernel" in r.json()["text"].lower()
    bad = await client.post(f"/interviews/turns/{turn.id}/transcribe", headers=hs, files={"audio": ("x.txt", b"hi", "text/plain")})
    assert bad.status_code == 415
    # another student can't transcribe into this turn
    async with AsyncSessionLocal() as db:
        _, _, h2 = await make_student(db)
        await db.commit()
    other = await client.post(f"/interviews/turns/{turn.id}/transcribe", headers=h2,
                              files={"audio": ("answer.wav", speech_wav.read_bytes(), "audio/wav")})
    assert other.status_code == 404
