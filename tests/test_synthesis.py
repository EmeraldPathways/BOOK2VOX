"""Chatterbox invocation tests with a lightweight fake model."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app import main


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
