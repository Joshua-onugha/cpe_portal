from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’-][A-Za-zÀ-ÖØ-öø-ÿ]+)?")
SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)", re.S)


@dataclass(frozen=True)
class Features:
    words: int
    sentences: int
    paragraphs: int
    avg_sentence_length: float
    sentence_length_std: float
    vocabulary_richness: float
    repetition_rate: float
    punctuation_density: float
    function_word_rate: float
    burstiness: float
    readability: float


FUNCTION_WORDS = {"the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for", "with", "is", "are", "was", "were", "it", "this", "that", "as", "at", "by", "from"}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def extract_features(text: str) -> Features:
    words = [word.lower() for word in WORD_RE.findall(text)]
    sentences = [part.strip() for part in SENTENCE_RE.findall(text) if WORD_RE.search(part)]
    sentence_lengths = [len(WORD_RE.findall(sentence)) for sentence in sentences]
    counts = Counter(words)
    repeated = sum(count - 1 for count in counts.values() if count > 1)
    punctuation = len(re.findall(r"[,;:!?—-]", text))
    avg = statistics.mean(sentence_lengths) if sentence_lengths else 0.0
    std = statistics.pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
    richness = len(counts) / len(words) if words else 0.0
    function_rate = sum(word in FUNCTION_WORDS for word in words) / len(words) if words else 0.0
    burstiness = _clamp(std / max(avg, 1.0) / 1.6)
    syllable_proxy = sum(max(1, len(re.findall(r"[aeiouy]+", word))) for word in words)
    readability = 206.835 - 1.015 * (len(words) / max(len(sentences), 1)) - 84.6 * (syllable_proxy / max(len(words), 1))
    return Features(len(words), len(sentences), max(1, text.count("\n\n") + 1), avg, std, richness, repeated / max(len(words), 1), punctuation / max(len(words), 1), function_rate, burstiness, readability)


def analyze_text(text: str, min_words: int = 80) -> dict:
    features = extract_features(text)
    if features.words < min_words:
        return {"status": "insufficient_text", "message": f"Provide at least {min_words} words for a more reliable estimate.", "word_count": features.words, "min_words": min_words}
    uniformity = _clamp(1 - features.burstiness)
    low_richness = _clamp((0.62 - features.vocabulary_richness) / 0.28)
    low_punctuation = _clamp((0.075 - features.punctuation_density) / 0.075)
    repetition = _clamp(features.repetition_rate / 0.18)
    smooth_sentences = _clamp((0.38 - features.sentence_length_std / max(features.avg_sentence_length, 1)) / 0.38)
    score = round(100 * _clamp(0.28 * uniformity + 0.24 * low_richness + 0.18 * low_punctuation + 0.16 * repetition + 0.14 * smooth_sentences), 1)
    quality = _clamp((features.words - min_words) / 220)
    confidence = round(35 + 55 * quality, 1)
    band = "likely_ai" if score >= 68 else "mixed_or_uncertain" if score >= 42 else "likely_human"
    signals = [
        {"name": "sentence_uniformity", "value": round(uniformity, 3), "direction": "ai_signal" if uniformity > 0.58 else "human_signal"},
        {"name": "vocabulary_richness", "value": round(features.vocabulary_richness, 3), "direction": "ai_signal" if low_richness > 0.5 else "human_signal"},
        {"name": "repetition_rate", "value": round(features.repetition_rate, 3), "direction": "ai_signal" if repetition > 0.5 else "human_signal"},
        {"name": "punctuation_density", "value": round(features.punctuation_density, 3), "direction": "ai_signal" if low_punctuation > 0.5 else "human_signal"},
    ]
    return {"status": "ok", "ai_probability": score, "classification": band, "confidence": confidence, "disclaimer": "Heuristic stylometry estimate, not proof of AI authorship.", "statistics": {"word_count": features.words, "sentence_count": features.sentences, "paragraph_count": features.paragraphs, "average_sentence_length": round(features.avg_sentence_length, 2), "sentence_length_std": round(features.sentence_length_std, 2), "vocabulary_richness": round(features.vocabulary_richness, 3), "readability_proxy": round(features.readability, 1)}, "signals": signals, "explanations": ["The score combines sentence regularity, lexical diversity, repetition, and punctuation patterns.", "Longer samples generally produce more stable estimates."]}
