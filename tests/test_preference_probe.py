"""延遲量測：預設不跑；跑的時候每次都記提示詞字數和時間，不因失敗中斷。"""

from src.bot import preference_probe
from src.bot.preference_probe import run_probe, start_preference_probe
from tests.fakes import REPO_ROOT


def test_probe_is_off_unless_runs_are_set(monkeypatch):
    monkeypatch.delenv("PREFERENCE_PROBE_RUNS", raising=False)
    assert start_preference_probe("key", REPO_ROOT) is None
    monkeypatch.setenv("PREFERENCE_PROBE_RUNS", "3")
    assert start_preference_probe(None, REPO_ROOT) is None


def test_probe_times_every_call_and_keeps_going_after_errors(monkeypatch):
    calls = []

    def fake_generate(self, prompt, **kwargs):
        calls.append(len(prompt))
        if len(calls) == 2:
            raise TimeoutError("slow")
        return "{}"

    monkeypatch.setattr(preference_probe.GeminiTextClient, "generate", fake_generate)
    results = run_probe("key", REPO_ROOT, 4, sleep=lambda seconds: None)

    assert len(results["parse"]) == 4
    assert len(results["baseline"]) == preference_probe.BASELINE_RUNS
    assert len(calls) == 4 + preference_probe.BASELINE_RUNS
    # 偏好解析的提示詞含特質表，比網路基準長很多。
    assert min(calls[:4]) > 10 * max(calls[4:])
