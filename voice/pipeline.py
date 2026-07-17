"""
Voice Pipeline -- Mic -> VAD -> Whisper -> Inject.

Adapted from audio-listener/listener.py for GestureControl v2.
Stripped down: no wake word detection, no conversation mode, no semantic
matching, no Gemma brain.  The gesture IS the trigger.

The VAD class is copied verbatim from listener.py (Silero ONNX + energy
fallback) -- it is the proven implementation.
"""

import logging
import os
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

log = logging.getLogger("gesture-control.voice")


# ── VAD (copied exactly from audio-listener/listener.py) ──────────────────


class VAD:
    """
    Voice Activity Detection -- Silero ONNX (ML, best accuracy) with
    energy fallback.

    Silero VAD via ONNX Runtime: ~2MB model, ~30MB RAM, <5% CPU.
    No torch dependency -- pure ONNX inference.
    Energy VAD fallback: RMS threshold, zero deps, near-zero CPU.
    """

    def __init__(self, config: dict):
        self.sample_rate = config.get("sample_rate", 16000)
        self.energy_threshold = config.get("energy_threshold", 0.003)
        self.silero_threshold = config.get("silero_threshold", 0.5)
        self.frame_len = int(self.sample_rate * config.get("frame_ms", 30) / 1000)
        self.min_speech_frames = int(
            config.get("min_speech_s", 0.5) * 1000 / config.get("frame_ms", 30)
        )
        self.pad_frames = int(config.get("speech_pad_ms", 300) / config.get("frame_ms", 30))
        self.mode = config.get("vad_mode", "silero")

        # Try to load Silero VAD ONNX model
        self._silero_session = None
        self._silero_h = None
        self._silero_c = None
        if self.mode == "silero":
            self._init_silero()

    def _init_silero(self):
        """Load Silero VAD ONNX model. Falls back to energy VAD on failure."""
        try:
            import onnxruntime as ort
            import silero_vad

            model_path = os.path.join(
                os.path.dirname(silero_vad.__file__), "data", "silero_vad.onnx"
            )
            if not os.path.exists(model_path):
                raise FileNotFoundError(
                    f"Silero VAD ONNX model not found at {model_path}"
                )

            self._silero_session = ort.InferenceSession(
                model_path, providers=["CPUExecutionProvider"]
            )
            # Initialize LSTM hidden/cell states (2 layers x 64 units each)
            self._silero_h = np.zeros((2, 1, 64), dtype=np.float32)
            self._silero_c = np.zeros((2, 1, 64), dtype=np.float32)
            self._silero_sample_rate = 16000
            log.info("VAD: Silero ONNX loaded (~2MB model, ~30MB RAM)")
        except Exception as e:
            log.warning("VAD: Silero unavailable (%s), using energy-based fallback", e)
            self.mode = "energy"

    def reset_silero_state(self):
        """Reset LSTM states between utterances."""
        if self._silero_session is not None:
            self._silero_h = np.zeros((2, 1, 64), dtype=np.float32)
            self._silero_c = np.zeros((2, 1, 64), dtype=np.float32)

    def is_speech_frame(self, frame: np.ndarray) -> bool:
        """Check if a single frame contains speech."""
        if len(frame) == 0:
            return False

        if self.mode == "silero" and self._silero_session is not None:
            return self._is_speech_silero(frame)
        return self._is_speech_energy(frame)

    def _is_speech_energy(self, frame: np.ndarray) -> bool:
        energy = np.sqrt(np.mean(frame**2))
        return energy > self.energy_threshold

    def _is_speech_silero(self, frame: np.ndarray) -> bool:
        """Run Silero VAD on a single frame (expects 512 or 1024 samples at 16kHz)."""
        target_len = 512
        if len(frame) < target_len:
            padded = np.zeros(target_len, dtype=np.float32)
            padded[: len(frame)] = frame
        else:
            padded = frame[:target_len].astype(np.float32)

        audio_chunk = padded.reshape(1, -1)

        try:
            ort_inputs = {
                "input": audio_chunk,
                "h": self._silero_h,
                "c": self._silero_c,
            }
            output, self._silero_h, self._silero_c = self._silero_session.run(
                ["output", "hn", "cn"], ort_inputs
            )
            prob = float(output[0, 0])
            return prob > self.silero_threshold
        except Exception:
            return self._is_speech_energy(frame)

    def extract_speech(self, audio: np.ndarray) -> Optional[np.ndarray]:
        """
        Extract the speech region from audio.

        Uses Silero for timestamps if available, otherwise frame-wise energy.
        Returns the trimmed speech segment, or None if no speech found.
        """
        n_frames = len(audio) // self.frame_len
        if n_frames == 0:
            return None

        frames = audio[: n_frames * self.frame_len].reshape(n_frames, self.frame_len)
        is_speech = np.array([self.is_speech_frame(f) for f in frames])

        if not np.any(is_speech):
            return None

        speech_indices = np.where(is_speech)[0]
        if len(speech_indices) < self.min_speech_frames:
            return None

        start = max(0, speech_indices[0] - self.pad_frames) * self.frame_len
        end = min(len(audio), (speech_indices[-1] + self.pad_frames + 1) * self.frame_len)

        return audio[start:end]


# ── Voice Pipeline ────────────────────────────────────────────────────────


class VoicePipeline:
    """
    Manages mic -> VAD -> whisper -> inject in a background thread.

    Simplified from audio-listener: no wake words, no conversation mode,
    no semantic matching, no Gemma.  The gesture IS the trigger.

    Usage::

        pipeline = VoicePipeline(config, on_transcription=my_callback)
        pipeline.start()          # begin capturing
        # ... user makes gesture, speaks ...
        wav, transcript, dur = pipeline.stop()   # finalize
        pipeline.inject(transcript, wav, screenshot, dur)  # send to DeepSeek
    """

    def __init__(self, config: dict, on_transcription: callable = None):
        self.config = config
        self.on_transcription = on_transcription
        self.sample_rate = config.get("sample_rate", 16000)

        # VAD
        self.vad = VAD(config)

        # Speech buffering -- protected by _lock
        self._speech_buffer: list = []
        self._speech_active = False
        self._silence_samples = 0
        self._silence_trigger_samples = int(
            config.get("silence_trigger_s", 0.7) * self.sample_rate
        )
        self._max_buffer_samples = int(
            config.get("max_buffer_s", 15.0) * self.sample_rate
        )
        self._lock = threading.Lock()

        # State
        self._listening = False
        self._thread: Optional[threading.Thread] = None
        self._stream = None

        # Partial transcription (for HUD streaming)
        self._last_partial_time = 0.0
        self._partial_interval = 0.5  # 500ms

        # Directories
        self.cache_dir = Path(
            os.path.expanduser("~/.cache/gesture-control/voice")
        )
        self.inject_path = Path(
            os.path.expanduser(
                config.get(
                    "inject_path",
                    "~/.claude/channels/telegram-deepseek/inject",
                )
            )
        )

        # Whisper model -- loaded lazily
        self._whisper = None

    # ── Whisper ──────────────────────────────────────────────────────────

    def _load_whisper(self):
        """Lazy-load the faster-whisper model."""
        if self._whisper is not None:
            return
        try:
            from faster_whisper import WhisperModel

            t0 = time.time()
            model_name = self.config.get("whisper_model", "base")
            device = self.config.get("whisper_device", "auto")
            compute = self.config.get("whisper_compute", "int8")
            self._whisper = WhisperModel(
                model_name,
                device=device,
                compute_type=compute,
                cpu_threads=4,
            )
            elapsed = time.time() - t0
            log.info(
                "Whisper %s loaded (device=%s, compute=%s, %.1fs)",
                model_name,
                device,
                compute,
                elapsed,
            )
        except Exception as e:
            log.error("Whisper init failed: %s", e)
            self._whisper = None

    def _transcribe(self, audio: np.ndarray) -> Optional[str]:
        """Transcribe a numpy audio array with faster-whisper.  Returns text or None."""
        self._load_whisper()
        if self._whisper is None or len(audio) == 0:
            return None

        # Save to a temp WAV file (faster-whisper reads from disk)
        tmp_wav = self.cache_dir / f"_partial_{os.getpid()}.wav"
        try:
            audio_clamped = np.clip(audio, -1.0, 1.0)
            audio_int16 = (audio_clamped * 32767).astype(np.int16)
            with wave.open(str(tmp_wav), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_int16.tobytes())

            language = self.config.get("whisper_language", "fr")
            segments, _ = self._whisper.transcribe(
                str(tmp_wav), language=language, beam_size=1
            )
            transcript = " ".join(seg.text.strip() for seg in segments)
            return transcript.strip()
        except Exception as e:
            log.error("Transcription error: %s", e)
            return None
        finally:
            tmp_wav.unlink(missing_ok=True)

    # ── Audio callback (runs in PortAudio's thread) ─────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        """
        Called by sounddevice for each audio block (~100ms).

        Kept fast: only VAD + buffering.  Transcription happens in the
        stream-loop thread via _maybe_partial_transcribe().
        """
        if status:
            log.warning("Audio status: %s", status)

        if not self._listening:
            import sounddevice as sd

            raise sd.CallbackStop()

        audio = indata.flatten().astype(np.float32)
        frame_is_speech = self.vad.is_speech_frame(audio)

        with self._lock:
            if frame_is_speech:
                self._speech_buffer.extend(audio.tolist())
                self._silence_samples = 0
                self._speech_active = True
            elif self._speech_active:
                self._speech_buffer.extend(audio.tolist())
                self._silence_samples += len(audio)

    # ── Partial transcription (called from stream-loop thread) ──────────

    def _maybe_partial_transcribe(self):
        """If enough time has passed and speech is active, transcribe and
        call on_transcription with the partial result."""
        now = time.time()
        if not self._speech_active:
            return
        if (now - self._last_partial_time) < self._partial_interval:
            return

        self._last_partial_time = now

        with self._lock:
            if len(self._speech_buffer) < self.sample_rate * 0.5:
                return  # need at least 0.5s of audio
            audio_snapshot = np.array(list(self._speech_buffer), dtype=np.float32)

        if self.on_transcription is not None:
            partial = self._transcribe(audio_snapshot)
            if partial:
                try:
                    self.on_transcription(partial)
                except Exception:
                    log.debug("on_transcription callback raised", exc_info=True)

    # ── Stream thread ────────────────────────────────────────────────────

    def _run_stream(self):
        """Run the sounddevice InputStream in a dedicated thread."""
        try:
            import sounddevice as sd

            device = self.config.get("device", None)
            if device is not None and not isinstance(device, int):
                device = None  # "auto" or unknown -> system default

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.config.get("channels", 1),
                dtype=self.config.get("dtype", "float32"),
                device=device,
                callback=self._audio_callback,
                blocksize=int(self.sample_rate * 0.1),  # 100ms blocks
            )
            with self._stream:
                while self._listening:
                    time.sleep(0.1)
                    self._maybe_partial_transcribe()
        except Exception as e:
            log.error("Audio stream error: %s", e)

    # ── Public API ───────────────────────────────────────────────────────

    def start(self):
        """Start mic capture + VAD in a background thread."""
        self._listening = True
        self._speech_buffer = []
        self._speech_active = False
        self._silence_samples = 0
        self._last_partial_time = 0.0

        self.vad.reset_silero_state()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._thread = threading.Thread(target=self._run_stream, daemon=True)
        self._thread.start()
        log.info("Voice pipeline started")

    def stop(self) -> Tuple[Optional[str], str, float]:
        """
        Stop mic capture, flush the accumulated speech buffer,
        transcribe the final utterance.

        Returns (audio_path, transcript, duration_seconds).
        audio_path is None if no speech was captured.
        """
        self._listening = False

        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._thread = None

        with self._lock:
            if not self._speech_buffer:
                return (None, "", 0.0)

            audio = np.array(self._speech_buffer, dtype=np.float32)

            # Try to extract just the speech portion
            speech = self.vad.extract_speech(audio)
            if speech is not None and len(speech) > 0:
                audio = speech

            duration = len(audio) / self.sample_rate

            # Discard if too short
            min_speech_s = self.config.get("min_speech_s", 0.5)
            if duration < min_speech_s:
                log.debug(
                    "Utterance too short (%.1fs < %.1fs), discarding",
                    duration,
                    min_speech_s,
                )
                self._speech_buffer = []
                self._speech_active = False
                return (None, "", 0.0)

            # Save WAV
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            wav_path = self.cache_dir / f"utterance_{ts}.wav"
            audio_clamped = np.clip(audio, -1.0, 1.0)
            audio_int16 = (audio_clamped * 32767).astype(np.int16)
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_int16.tobytes())

            audio_path = str(wav_path)

            # Clear the buffer
            self._speech_buffer = []
            self._speech_active = False
            self._silence_samples = 0

        # Transcribe (outside the lock -- takes ~300ms)
        transcript = self._transcribe(audio) or ""

        log.info(
            "Utterance: %.1fs, transcript: %s",
            duration,
            transcript[:80] if transcript else "(empty)",
        )

        return (audio_path, transcript, duration)

    def is_listening(self) -> bool:
        """Return whether the mic is currently being captured."""
        return self._listening

    def inject(
        self,
        transcript: str,
        audio_path: Optional[str],
        screenshot_path: Optional[str],
        duration: float,
    ):
        """Inject the voice message into the DeepSeek channel via file append.

        Writes a ``VOICE_GESTURE`` header line followed by a prompt line to
        ``~/.claude/channels/telegram-deepseek/inject``.  The Telegram plugin
        watching that directory delivers each line as a Claude Code turn.
        """
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        audio_str = audio_path or "none"
        sc_str = screenshot_path or "none"

        header = (
            f"VOICE_GESTURE ts={ts} authorized=yes "
            f"path={audio_str} screenshot={sc_str} "
            f"duration={duration:.1f}s lang=fr "
            f"transcript={transcript[:200]}"
        )
        prompt = (
            f"🎙️ Voice message from Joris via GestureControl. "
            f"Screenshot at {sc_str}. "
            f"Execute: low-risk=auto. Reply in French."
        )

        try:
            self.inject_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.inject_path, "a") as f:
                f.write(header + "\n")
                f.write(prompt + "\n")
            log.info("Injected -> %s: %s", self.inject_path.name, header[:120])
        except Exception as e:
            log.error("Inject failed: %s", e)
