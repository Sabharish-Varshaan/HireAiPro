"""Local models are released after idling and reload transparently."""
import threading
import time

from app.services.ai_gateway import embeddings as E


class _Stub(E._IdleReleasedModel):
    builds = 0

    def _build(self):
        type(self).builds += 1
        return object()


def test_release_after_idle_and_reload_on_next_use():
    m = _Stub("stub", idle_seconds=60)
    m._run(lambda model: None)
    assert m.loaded and _Stub.builds == 1
    assert not m.release_if_idle(now=time.monotonic() + 10)   # still warm
    assert m.release_if_idle(now=time.monotonic() + 61)       # idle long enough
    assert not m.loaded
    m._run(lambda model: None)                                # transparent reload
    assert m.loaded and _Stub.builds == 2


def test_never_released_while_a_call_is_running():
    m = _Stub("stub", idle_seconds=1)
    inside, done = threading.Event(), threading.Event()

    def slow(model):
        inside.set()
        done.wait(2)
        return model

    t = threading.Thread(target=lambda: m._run(slow))
    t.start()
    inside.wait(2)
    released = []
    r = threading.Thread(target=lambda: released.append(m.release_if_idle(now=time.monotonic() + 100)))
    r.start()
    time.sleep(0.2)
    assert r.is_alive()          # blocked on the lock, not tearing the model down mid-call
    done.set(); t.join(); r.join()
    # The release only proceeded after the call returned its result intact.
    assert m._run(lambda model: "reloads fine") == "reloads fine"


def test_zero_keeps_models_resident():
    m = _Stub("stub", idle_seconds=0)
    m._run(lambda model: None)
    assert not m.release_if_idle(now=time.monotonic() + 10_000) and m.loaded
