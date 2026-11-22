"""Chatterbox invocation tests with a lightweight fake model."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app import main


def test_narration_direction_parses_structured_lm_studio_response(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            calls.append(("get", url))
            return FakeResponse({"data": [{"id": "text-embedding-nomic-embed-text-v1.5"}, {"id": "qwen/qwen3.5-9b"}]})

        def post(self, url, json):
            calls.append(("post", url, json))
            return FakeResponse({"choices": [{"message": {"content": '{"guidance":"Build quiet tension and slow the pauses.","mood":"tense","exaggeration":0.9,"cfg_weight":0.35}'}}]})

    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    direction = main.narration_direction("The door opened.")

    assert direction.guidance == "Build quiet tension and slow the pauses."
    assert direction.mood == "tense"
    assert direction.exaggeration == 0.9
    assert direction.cfg_weight == 0.35
    assert calls[1][2]["model"] == "qwen/qwen3.5-9b"


def test_narration_direction_uses_lm_studio_native_non_thinking_chat(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            return FakeResponse({"data": [{"id": "qwen/qwen3.5-9b"}]})

        def post(self, url, json):
            calls.append((url, json))
            return FakeResponse({"output": [{
                "type": "message",
                "content": '{"guidance":"Keep the delivery restrained.","mood":"calm","exaggeration":0.4,"cfg_weight":0.5}',
            }]})

    monkeypatch.setattr(main.httpx, "Client", FakeClient)
    monkeypatch.setenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1")

    direction = main.narration_direction("The door opened slowly.")

    assert direction.guidance == "Keep the delivery restrained."
    assert calls == [("http://127.0.0.1:1234/api/v1/chat", {
        "model": "qwen/qwen3.5-9b",
        "system_prompt": "You are an audiobook narration director. Return JSON only with these keys: guidance (one concise actionable sentence), mood (one word), exaggeration (number from 0 to 1), cfg_weight (number from 0 to 1). Do not rewrite or repeat the passage.",
        "input": "The door opened slowly.",
        "temperature": 0.2,
        "max_output_tokens": 128,
        "reasoning": "off",
        "store": False,
    })]


def test_apply_narration_direction_blends_with_manual_controls():
    direction = main.NarrationDirection(exaggeration=0.9, cfg_weight=0.2)

    exaggeration, cfg_weight = main.apply_narration_direction(0.5, 0.5, direction)

    assert exaggeration == 0.64
    assert cfg_weight == 0.395


def test_synthesize_uses_voice_reference_and_emotion_controls(tmp_path, monkeypatch):
    calls = {"load": [], "generate": [], "save": []}

    class FakeAudio:
        def cpu(self):
            return self

    class FakeModel:
        sr = 24000

        @classmethod
        def from_pretrained(cls, device):
            calls["load"].append(device)
            return cls()

        def generate(self, text, **kwargs):
            calls["generate"].append((text, kwargs))
            return FakeAudio()

    torch_module = types.ModuleType("torch")
    torch_module.cuda = types.SimpleNamespace(is_available=lambda: True)
    torchaudio_module = types.ModuleType("torchaudio")
    torchaudio_module.save = lambda path, audio, sample_rate: calls["save"].append((path, audio, sample_rate))
    chatterbox_module = types.ModuleType("chatterbox")
    chatterbox_tts_module = types.ModuleType("chatterbox.tts")
    chatterbox_tts_module.ChatterboxTTS = FakeModel
    chatterbox_module.tts = chatterbox_tts_module
    monkeypatch.setitem(sys.modules, "torch", torch_module)
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio_module)
    monkeypatch.setitem(sys.modules, "chatterbox", chatterbox_module)
    monkeypatch.setitem(sys.modules, "chatterbox.tts", chatterbox_tts_module)
    monkeypatch.setattr(main.voice_library, "reference_path", lambda voice_id: "reference.wav")
    monkeypatch.setattr(main, "_model", None)

    output = tmp_path / "preview.wav"
    main.synthesize("A dramatic line.", output, 0.8, 0.3, "voice-id")

    assert calls["load"] == ["cuda"]
    assert calls["generate"] == [("A dramatic line.", {
        "exaggeration": 0.8,
        "cfg_weight": 0.3,
        "audio_prompt_path": "reference.wav",
    })]
    assert len(calls["save"]) == 1
    assert calls["save"][0][0] == str(output)
    assert calls["save"][0][2] == 24000


def test_preview_request_accepts_talking_speed():
    request = main.PreviewRequest(text="A short line.", speed=1.15)

    assert request.speed == 1.15


def test_synthesize_applies_pitch_preserving_speed(tmp_path, monkeypatch):
    calls = {"ffmpeg": []}

    class FakeAudio:
        def cpu(self):
            return self

    class FakeModel:
        sr = 24000

        @classmethod
        def from_pretrained(cls, device):
            return cls()

        def generate(self, text, **kwargs):
            return FakeAudio()

    torch_module = types.ModuleType("torch")
    torch_module.cuda = types.SimpleNamespace(is_available=lambda: True)
    torchaudio_module = types.ModuleType("torchaudio")
    torchaudio_module.save = lambda path, audio, sample_rate: Path(path).write_bytes(b"source")
    chatterbox_module = types.ModuleType("chatterbox")
    chatterbox_tts_module = types.ModuleType("chatterbox.tts")
    chatterbox_tts_module.ChatterboxTTS = FakeModel
    chatterbox_module.tts = chatterbox_tts_module
    monkeypatch.setitem(sys.modules, "torch", torch_module)
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio_module)
    monkeypatch.setitem(sys.modules, "chatterbox", chatterbox_module)
    monkeypatch.setitem(sys.modules, "chatterbox.tts", chatterbox_tts_module)
    monkeypatch.setattr(main, "_model", None)
    monkeypatch.setattr(main.shutil, "which", lambda name: "ffmpeg.exe" if name == "ffmpeg" else None)

    def fake_run(args, **kwargs):
        calls["ffmpeg"].append(args)
        Path(args[-1]).write_bytes(b"adjusted")

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    output = tmp_path / "preview.wav"

    main.synthesize("A faster line.", output, 0.5, 0.5, speed=1.15)

    assert output.read_bytes() == b"adjusted"
    assert calls["ffmpeg"][0][0] == "ffmpeg"
    filter_index = calls["ffmpeg"][0].index("-filter:a")
    assert calls["ffmpeg"][0][filter_index + 1] == "atempo=1.150"
