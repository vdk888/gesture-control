# GestureControl v2 Part 2 — Voice Integration Design Spec

**Date:** 2026-07-17
**Status:** Draft
**Author:** Rick (R&D) + Joris

## Overview

Integrate the audio-listener voice pipeline into GestureControl as a new VoiceMode. A hand gesture replaces the wake word — make the gesture, speak, release to send. The existing audio-listener stack (sounddevice + Silero VAD ONNX + faster-whisper + bubble-inject to DeepSeek) is adapted into an in-app background thread. The HUD gains live streaming transcription. Every voice utterance auto-captures a screenshot. An always-on toggle lets the mic run continuously, VAD-gated, with the gesture as an explicit send trigger.

## Architecture

```
gesture-control/
├── gesture_control.py        # main loop (+ voice mode in mode_order)
├── hand_tracking.py           # + detect_ok_sign() for new trigger gesture
├── hud.py                     # HUD: live transcription text line, voice status pill
├── config_manager.py          # + voice defaults, always-on toggle, inject path
├── modes/
│   ├── voice.py               # VoiceMode class
│   └── ...
├── voice/
│   ├── __init__.py
│   ├── pipeline.py            # adapted from listener.py: VAD, whisper, inject
│   ├── screenshot.py          # CGWindowListCreateImage wrapper
│   └── transcription.py       # streaming transcription buffer for HUD
├── config.json                # + "voice" section
└── requirements.txt           # + sounddevice, silero-vad, faster-whisper, onnxruntime
```

## Data Flow

```
Webcam → OpenCV frame → flip → RGB → HandLandmarker
    → fingers_up() → name_gesture()
    → if VoiceMode active: check trigger gesture
        ├─ gesture ON  → start mic capture thread (or resume VAD in always-on)
        ├─ gesture OFF → stop mic, finalize utterance, transcribe, inject
        └─ always-on   → VAD gates continuously, gesture = manual send
    → Mic (sounddevice) → Silero VAD (ONNX) → speech buffer
    → faster-whisper base (streaming partials for HUD, full on flush)
    → Screenshot captured via CGWindowListCreateImage
    → Inject into DeepSeek channel (~/.claude/channels/telegram-deepseek/inject)
    → HUD shows live transcription text + voice status indicator
```

## VoiceMode

New mode class at `modes/voice.py`, following the Mode ABC:

```python
class VoiceMode(Mode):
    name = "Voice"
```

**enter()**: Spawn background `voice.pipeline.VoicePipeline` thread. Load faster-whisper base model (shared, loaded once). Initialize screenshot helper. Register HUD transcription callback.

**exit()**: Signal pipeline to stop. Join thread. Clear HUD transcription.

**update()**: Check trigger gesture. Three states:
1. **Gesture held + not listening**: Start pipeline recording. HUD shows "Listening..." with mic icon.
2. **Gesture held + already listening**: HUD shows live partial transcription from pipeline.
3. **Gesture released + was listening**: Pipeline finalizes utterance. HUD shows "Processing..." then the final transcript. Auto-captures screenshot. Injects to DeepSeek.

## Trigger Gesture

The gesture that activates voice capture replaces the wake word entirely.

**Primary trigger:** "3 fingers" (index + middle + ring extended, thumb + pinky down). Already detected by `name_gesture()`. Distinctive, not used by other modes, natural "talk to the hand" pose.

**Alternative:** "OK sign" (thumb + index touching, other three extended). New `detect_ok_sign()` helper in hand_tracking.py.

Config key: `voice_trigger_gesture` (default `"3 fingers"`, also `"ok_sign"`).

**Hysteresis:** 300ms cooldown between trigger activations.

## Always-On Toggle

Always-on keeps the mic active and VAD-gated regardless of gesture.

**Toggle:** Peace sign held for 1.0s toggles always-on.

**When ON:**
- VAD processes continuously
- Any speech > 0.5s is transcribed and shown in HUD
- Trigger gesture = explicit "send now" (inject current buffer immediately)
- Without trigger, utterances auto-inject after silence (0.7s)

**HUD:** Shows "Voice always-on: ON" (green) or "OFF" (grey) for 2s on toggle.

**Config:** `voice_always_on` (default `false`).

## Screenshot Capture

`voice/screenshot.py`:
```python
def capture_screenshot() -> bytes:
    """Return PNG bytes of the primary display via CGWindowListCreateImage."""
```

Saved to `~/.cache/gesture-control/screenshots/voice_{ts}.png`. Path included in inject payload. TTL: 24h, max 50MB.

## Live Transcription in HUD

New HUD API:
```python
hud.show_transcription(text: str)
hud.clear_transcription()
hud.show_voice_status(status: str)  # "Listening...", "Processing...", "Sent"
```

HUD grows to 100px when showing transcription. Two lines: mode name + status (18pt), transcription text (14pt, auto-scrolling).

Pipeline calls a callback every ~500ms during active speech with latest faster-whisper partials.

## Inject Integration

File append to `~/.claude/channels/telegram-deepseek/inject`:

```
VOICE_GESTURE ts=... authorized=yes path=<wav> screenshot=<png> duration=3.2s lang=fr transcript=<text>
🎙️ Voice message from Joris via GestureControl. Screenshot at path. Execute: low-risk=auto. Reply in French.
```

No wake word needed — the gesture IS the trigger.

## Config Additions

```json
{
  "voice": {
    "enabled": true,
    "trigger_gesture": "3 fingers",
    "always_on": false,
    "sample_rate": 16000,
    "whisper_model": "base",
    "whisper_language": "fr",
    "inject_path": "~/.claude/channels/telegram-deepseek/inject",
    "screenshot_enabled": true,
    "always_on_toggle_gesture": "Peace",
    "always_on_toggle_hold_s": 1.0
  }
}
```

## Dependencies

```
sounddevice>=0.4.6, silero-vad>=0.1.0, faster-whisper>=1.0.0, onnxruntime>=1.16.0
```

## Error Handling

| Condition | Behavior |
|---|---|
| No mic | HUD shows "No mic", log warning |
| Mic permission denied | HUD shows "Mic denied — System Settings" |
| VAD model missing | Fall back to energy VAD |
| Whisper load failure | HUD "STT unavailable", sends audio path only |
| Inject path not writable | Log error, HUD "Inject failed" for 3s |
| Screenshot denied | Skipped, inject goes through without attachment |

## Testing

- Unit: `detect_ok_sign()`, voice config validation, screenshot capture
- Integration: Mock sounddevice stream, verify VAD triggers, verify inject
- Manual: VoiceMode → trigger gesture → speak → verify HUD + inject + screenshot
