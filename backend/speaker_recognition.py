from io import BytesIO
from typing import Dict, Optional

import numpy as np
import soundfile as sf
from resemblyzer import VoiceEncoder, preprocess_wav


class LocalSpeakerRecognizer:
    def __init__(self, similarity_threshold: float = 0.6) -> None:
        self._encoder = VoiceEncoder()
        self._profiles: Dict[str, np.ndarray] = {}
        self._threshold = similarity_threshold
        # With only one candidate profile, use a stricter gate to avoid over-labeling everything as that speaker.
        self._single_candidate_threshold = max(similarity_threshold, 0.75)

    def enroll(self, name: str, wav_bytes: bytes) -> None:
        embedding = self._embed(wav_bytes)
        self._profiles[name] = embedding

    def enroll_embedding(self, name: str, embedding: np.ndarray) -> None:
        self._profiles[name] = embedding

    def embed_bytes(self, wav_bytes: bytes) -> np.ndarray:
        return self._embed(wav_bytes)

    def set_profiles(self, profiles: Dict[str, np.ndarray]) -> None:
        self._profiles = dict(profiles)

    def clear_profiles(self) -> None:
        self._profiles = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(str(name or "").strip().lower().split())

    def identify(self, wav_bytes: bytes, allowed_speakers: Optional[set[str]] = None) -> Optional[str]:
        if not self._profiles:
            return None

        embedding = self._embed(wav_bytes)
        best_name = None
        best_score = -1.0

        candidates = self._profiles.items()
        if allowed_speakers is not None:
            candidates = [
                (name, profile)
                for name, profile in self._profiles.items()
                if self._normalize_name(name) in allowed_speakers
            ]
            if not candidates:
                return None

        candidate_count = len(candidates)

        for name, profile in candidates:
            score = float(np.dot(embedding, profile))
            if score > best_score:
                best_score = score
                best_name = name

        threshold = self._single_candidate_threshold if candidate_count == 1 else self._threshold
        if best_score >= threshold:
            return best_name
        return None

    def identify_samples(self, samples: np.ndarray, sample_rate: int, allowed_speakers: Optional[set[str]] = None) -> Optional[str]:
        if not self._profiles:
            return None

        if samples.ndim > 1:
            samples = np.mean(samples, axis=1)

        wav = preprocess_wav(samples, source_sr=sample_rate)
        embedding = np.asarray(self._encoder.embed_utterance(wav), dtype=np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        best_name = None
        best_score = -1.0

        candidates = self._profiles.items()
        if allowed_speakers is not None:
            candidates = [
                (name, profile)
                for name, profile in self._profiles.items()
                if self._normalize_name(name) in allowed_speakers
            ]
            if not candidates:
                return None

        candidate_count = len(candidates)

        for name, profile in candidates:
            score = float(np.dot(embedding, profile))
            if score > best_score:
                best_score = score
                best_name = name

        threshold = self._single_candidate_threshold if candidate_count == 1 else self._threshold
        if best_score >= threshold:
            return best_name
        return None

    def _embed(self, wav_bytes: bytes) -> np.ndarray:
        with sf.SoundFile(BytesIO(wav_bytes)) as audio_file:
            wav = audio_file.read(dtype="float32")
            sample_rate = audio_file.samplerate

        if wav.ndim > 1:
            wav = np.mean(wav, axis=1)

        wav = preprocess_wav(wav, source_sr=sample_rate)
        embedding = np.asarray(self._encoder.embed_utterance(wav), dtype=np.float32)
        return embedding / np.linalg.norm(embedding)
