"""
Stylometry engine — heuristic AI-text estimator.

This is a *heuristic* estimator, not a trained neural detector. It extracts a set
of length-robust stylometric features and combines them through a logistic model
whose weights ship with sensible defaults and can be re-calibrated on labelled
data via ``train_logistic`` (pure Python — no scikit-learn / numpy required).

Design notes
------------
* Every sub-signal is oriented so that a higher value means "more AI-like" and is
  normalised to [0, 1] via documented reference bands (``_ramp`` / ``_inv_ramp``).
* Scores combine with a logistic (sigmoid) function, so the output is a smooth
  probability and the model is trivially trainable with gradient descent.
* ``analyze_text`` also returns a per-paragraph breakdown so a reviewer can see
  *where* a document reads as AI-generated, not just an overall number.

IMPORTANT: the default reference bands and weights are informed priors, not the
product of a fitted dataset. Treat the output as "flag for human review", never
as proof of AI authorship. Collect a labelled sample of known-human and known-AI
department writing and call ``train_logistic`` to make this defensible.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
from collections import Counter
from typing import Iterable

# ─── Tokenisation ──────────────────────────────────────────────────────────────

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’-][A-Za-zÀ-ÖØ-öø-ÿ]+)?")
SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)", re.S)
PARAGRAPH_RE = re.compile(r"\n\s*\n")

# Common English function words — a classic stylometric signal.
FUNCTION_WORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "it", "this", "that", "as", "at", "by",
    "from", "be", "been", "has", "have", "had", "not", "which", "their", "its",
    "these", "those", "such", "into", "than", "then", "so", "also", "can", "will",
}

# Transitions and buzzwords that current LLMs over-produce. Multi-word phrases are
# matched as substrings; single tokens are matched against the word list.
TEMPLATED_MARKERS = {
    "furthermore", "moreover", "additionally", "consequently", "notably",
    "importantly", "overall", "delve", "delving", "tapestry", "realm",
    "landscape", "underscore", "underscores", "pivotal", "seamless",
    "seamlessly", "leverage", "leveraging", "robust", "multifaceted",
    "in conclusion", "in summary", "to summarize", "in essence",
    "it is important to note", "it is worth noting", "on the other hand",
    "as a result", "in today's world", "plays a crucial role",
    "a wide range of", "in the realm of", "when it comes to",
}
_TEMPLATED_MULTI = tuple(m for m in TEMPLATED_MARKERS if " " in m)
_TEMPLATED_SINGLE = frozenset(m for m in TEMPLATED_MARKERS if " " not in m)

_PUNCT_CLASSES = (",", ";", ":", "!", "?", "—", "-", "(", '"', "'")

# ─── Small numeric helpers ──────────────────────────────────────────────────────


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _ramp(value: float, low: float, high: float) -> float:
    """Map ``value`` to [0, 1]; ``>= high`` → 1 (more AI-like), ``<= low`` → 0."""
    if high <= low:
        return 0.0
    return _clamp((value - low) / (high - low))


def _inv_ramp(value: float, low: float, high: float) -> float:
    """Inverse ramp: *lower* raw values are more AI-like."""
    if high <= low:
        return 0.0
    return _clamp((high - value) / (high - low))


def _sigmoid(z: float) -> float:
    if z <= -60:
        return 0.0
    if z >= 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


# ─── Feature extraction ─────────────────────────────────────────────────────────


def tokenize_words(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text)]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.findall(text) if WORD_RE.search(s)]


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in PARAGRAPH_RE.split(text) if WORD_RE.search(p)]


def _mattr(tokens: list[str], window: int = 50) -> float:
    """Moving-Average Type-Token Ratio — a length-robust lexical-diversity measure.

    Plain TTR falls mechanically as text grows, so it cannot fairly compare a
    short abstract with a long thesis. MATTR averages the TTR of a sliding window
    and is stable across lengths. Runs in O(n) via a rolling counter.
    """
    n = len(tokens)
    if n == 0:
        return 0.0
    if n <= window:
        return len(set(tokens)) / n
    counts: Counter[str] = Counter(tokens[:window])
    ttr_sum = len(counts) / window
    steps = 1
    for i in range(window, n):
        incoming, outgoing = tokens[i], tokens[i - window]
        counts[incoming] += 1
        counts[outgoing] -= 1
        if counts[outgoing] == 0:
            del counts[outgoing]
        ttr_sum += len(counts) / window
        steps += 1
    return ttr_sum / steps


def _ngram_repetition(tokens: list[str], n: int) -> float:
    """Fraction of n-grams that are repeats — AI text reuses phrasing/structure."""
    if len(tokens) < n + 1:
        return 0.0
    grams = [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]
    counts = Counter(grams)
    repeated = sum(c - 1 for c in counts.values() if c > 1)
    return repeated / len(grams)


def extract_features(text: str) -> dict:
    """Return a flat dict of raw stylometric features for ``text``."""
    words = tokenize_words(text)
    sentences = split_sentences(text)
    n_words = len(words)
    n_sentences = len(sentences)

    sentence_lengths = [len(WORD_RE.findall(s)) for s in sentences]
    avg_len = statistics.mean(sentence_lengths) if sentence_lengths else 0.0
    std_len = statistics.pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
    cv = std_len / avg_len if avg_len else 0.0
    # Sentence-length uniformity in [0, 1]; AI text tends to be more uniform.
    uniformity = _clamp(1.0 - _clamp(cv / 1.6))

    counts = Counter(words)
    types = len(counts)
    repeated = sum(c - 1 for c in counts.values() if c > 1)
    hapax = sum(1 for c in counts.values() if c == 1)

    openers = [WORD_RE.findall(s)[0].lower() for s in sentences if WORD_RE.findall(s)]
    opener_diversity = len(set(openers)) / len(openers) if openers else 0.0

    punct_total = sum(text.count(p) for p in _PUNCT_CLASSES)
    punct_variety = sum(1 for p in _PUNCT_CLASSES if p in text) / len(_PUNCT_CLASSES)

    lower_text = text.lower()
    templated = sum(lower_text.count(p) for p in _TEMPLATED_MULTI)
    templated += sum(1 for w in words if w in _TEMPLATED_SINGLE)

    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", w))) for w in words)
    readability = (
        206.835
        - 1.015 * (n_words / max(n_sentences, 1))
        - 84.6 * (syllables / max(n_words, 1))
    )

    return {
        "words": n_words,
        "sentences": n_sentences,
        "paragraphs": max(1, len(split_paragraphs(text))),
        "avg_sentence_length": avg_len,
        "sentence_length_std": std_len,
        "sentence_length_cv": cv,
        "sentence_uniformity": uniformity,
        "type_token_ratio": types / n_words if n_words else 0.0,
        "lexical_diversity_mattr": _mattr(words),
        "repetition_rate": repeated / max(n_words, 1),
        "hapax_ratio": hapax / max(types, 1),
        "bigram_repetition": _ngram_repetition(words, 2),
        "trigram_repetition": _ngram_repetition(words, 3),
        "sentence_opener_diversity": opener_diversity,
        "punctuation_density": punct_total / max(n_words, 1),
        "punctuation_variety": punct_variety,
        "function_word_rate": sum(w in FUNCTION_WORDS for w in words) / max(n_words, 1),
        "templated_per_100w": 100.0 * templated / max(n_words, 1),
        "readability": readability,
    }


# ─── Signals (each in [0, 1]; higher = more AI-like) ────────────────────────────


def compute_signals(features: dict) -> dict:
    """Turn raw features into normalised AI-ness signals used by the scorer."""
    return {
        "sentence_uniformity": _ramp(features["sentence_uniformity"], 0.55, 0.85),
        "low_lexical_diversity": _inv_ramp(features["lexical_diversity_mattr"], 0.60, 0.82),
        "word_repetition": _ramp(features["repetition_rate"], 0.06, 0.20),
        "ngram_repetition": _ramp(
            0.5 * features["bigram_repetition"] + 0.5 * features["trigram_repetition"],
            0.03, 0.16,
        ),
        "low_opener_diversity": _inv_ramp(features["sentence_opener_diversity"], 0.50, 0.90),
        "templated_language": _ramp(features["templated_per_100w"], 0.3, 2.5),
        "low_punctuation": (
            0.6 * _inv_ramp(features["punctuation_density"], 0.04, 0.11)
            + 0.4 * _inv_ramp(features["punctuation_variety"], 0.30, 0.80)
        ),
        "low_hapax": _inv_ramp(features["hapax_ratio"], 0.35, 0.65),
        "function_word_extremity": _clamp(abs(features["function_word_rate"] - 0.28) / 0.20),
    }


# Default logistic weights (log-odds space). "_bias" is the intercept.
# Neutral input (all signals ≈ 0.5) lands near 40% — innocent until flagged.
# Re-fit with train_logistic() once labelled data is available.
DEFAULT_WEIGHTS: dict[str, float] = {
    "_bias": -6.6,
    "sentence_uniformity": 1.3,
    "low_lexical_diversity": 1.6,
    "word_repetition": 1.0,
    "ngram_repetition": 2.2,
    "low_opener_diversity": 1.3,
    "templated_language": 2.6,
    "low_punctuation": 0.7,
    "low_hapax": 1.2,
    "function_word_extremity": 0.5,
}

SIGNAL_KEYS = tuple(k for k in DEFAULT_WEIGHTS if k != "_bias")


# Optional calibrated weights produced by train.py (sits next to this file).
# If present and valid, it overrides DEFAULT_WEIGHTS; otherwise we fall back to
# the informed priors. This is how training takes effect with no code edit —
# train.py writes weights.json, the engine picks it up on next start.
_WEIGHTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights.json")


def load_active_weights(path: str = _WEIGHTS_FILE) -> dict:
    """Return calibrated weights from ``weights.json`` if present/valid, else defaults."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: float(data[k]) for k in DEFAULT_WEIGHTS}
    except (OSError, ValueError, TypeError, KeyError):
        return dict(DEFAULT_WEIGHTS)


ACTIVE_WEIGHTS: dict[str, float] = load_active_weights()


def _score_signals(signals: dict, weights: dict) -> float:
    """Logistic combination of signals → AI probability in [0, 1]."""
    z = weights.get("_bias", 0.0)
    for key in SIGNAL_KEYS:
        z += weights.get(key, 0.0) * signals.get(key, 0.0)
    return _sigmoid(z)


# ─── Training (pure-Python logistic regression) ─────────────────────────────────


def train_logistic(
    labelled: Iterable[tuple[str, int]],
    epochs: int = 800,
    lr: float = 0.2,
    l2: float = 1e-3,
) -> dict:
    """Fit logistic weights from labelled samples via batch gradient descent.

    ``labelled`` is an iterable of ``(text, label)`` where ``label`` is 1 for
    AI-written and 0 for human-written. Returns a weights dict in the same shape
    as ``DEFAULT_WEIGHTS`` — paste it back in (or persist it) and pass to
    ``analyze_text(text, weights=...)``.
    """
    data = []
    for text, label in labelled:
        feats = extract_features(text)
        if feats["words"] > 0:
            data.append((compute_signals(feats), float(label)))
    if not data:
        raise ValueError("No usable training samples were provided.")

    weights = {k: 0.0 for k in DEFAULT_WEIGHTS}
    n = len(data)
    for _ in range(epochs):
        grad = {k: 0.0 for k in weights}
        for signals, y in data:
            z = weights["_bias"] + sum(weights[k] * signals[k] for k in SIGNAL_KEYS)
            error = _sigmoid(z) - y
            grad["_bias"] += error
            for k in SIGNAL_KEYS:
                grad[k] += error * signals[k]
        for k in weights:
            reg = 0.0 if k == "_bias" else l2 * weights[k]
            weights[k] -= lr * (grad[k] / n + reg)
    return weights


# ─── Public API ─────────────────────────────────────────────────────────────────


def _band(score_0_100: float) -> str:
    if score_0_100 >= 68:
        return "likely_ai"
    if score_0_100 >= 42:
        return "mixed_or_uncertain"
    return "likely_human"


def _score_paragraphs(text: str, weights: dict, min_words: int = 40) -> list[dict]:
    """Per-paragraph scores so reviewers can localise AI-looking sections."""
    results = []
    for index, para in enumerate(split_paragraphs(text)):
        feats = extract_features(para)
        if feats["words"] < min_words:
            results.append({
                "index": index,
                "word_count": feats["words"],
                "status": "too_short",
            })
            continue
        signals = compute_signals(feats)
        prob = _score_signals(signals, weights)
        contributions = {
            k: round(weights.get(k, 0.0) * signals[k], 3) for k in SIGNAL_KEYS
        }
        top = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)[:2]
        results.append({
            "index": index,
            "word_count": feats["words"],
            "status": "ok",
            "ai_probability": round(100 * prob, 1),
            "classification": _band(100 * prob),
            "top_signals": [name for name, _ in top],
        })
    return results


def analyze_text(text: str, min_words: int = 80, weights: dict | None = None) -> dict:
    """Estimate the probability that ``text`` was AI-generated.

    Returns a dict with an overall ``ai_probability`` (0–100), a ``classification``
    band, per-signal detail, per-paragraph breakdown, and a ``confidence`` that
    reflects both sample length and how decisively the signals point one way.
    """
    weights = weights or ACTIVE_WEIGHTS
    features = extract_features(text)

    if features["words"] < min_words:
        return {
            "status": "insufficient_text",
            "message": f"Provide at least {min_words} words for a more reliable estimate.",
            "word_count": features["words"],
            "min_words": min_words,
        }

    signals = compute_signals(features)
    prob = _score_signals(signals, weights)
    score = round(100 * prob, 1)

    # Confidence: longer samples + more decisive signals → higher confidence.
    length_quality = _clamp((features["words"] - min_words) / 220)
    separation = abs(prob - 0.5) * 2.0
    confidence = round(30 + 45 * length_quality + 20 * separation, 1)

    contributions = {k: round(weights.get(k, 0.0) * signals[k], 3) for k in SIGNAL_KEYS}
    ranked = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)

    # Display signals keep interpretable RAW values (backwards-compatible: the UI
    # and main.py read the "sentence_uniformity" entry's value).
    display = [
        ("sentence_uniformity", features["sentence_uniformity"]),
        ("lexical_diversity_mattr", features["lexical_diversity_mattr"]),
        ("repetition_rate", features["repetition_rate"]),
        ("ngram_repetition", 0.5 * features["bigram_repetition"] + 0.5 * features["trigram_repetition"]),
        ("sentence_opener_diversity", features["sentence_opener_diversity"]),
        ("templated_per_100w", features["templated_per_100w"]),
        ("punctuation_density", features["punctuation_density"]),
        ("hapax_ratio", features["hapax_ratio"]),
    ]
    ai_score_by_name = {
        "sentence_uniformity": signals["sentence_uniformity"],
        "lexical_diversity_mattr": signals["low_lexical_diversity"],
        "repetition_rate": signals["word_repetition"],
        "ngram_repetition": signals["ngram_repetition"],
        "sentence_opener_diversity": signals["low_opener_diversity"],
        "templated_per_100w": signals["templated_language"],
        "punctuation_density": signals["low_punctuation"],
        "hapax_ratio": signals["low_hapax"],
    }
    signal_list = []
    for name, raw in display:
        ai_score = ai_score_by_name[name]
        direction = "ai_signal" if ai_score > 0.55 else "human_signal" if ai_score < 0.45 else "neutral"
        signal_list.append({
            "name": name,
            "value": round(raw, 3),
            "ai_signal_score": round(ai_score, 3),
            "direction": direction,
        })

    return {
        "status": "ok",
        "ai_probability": score,
        "classification": _band(score),
        "confidence": confidence,
        "disclaimer": "Heuristic stylometry estimate, not proof of AI authorship. Use for human review, not adjudication.",
        "statistics": {
            "word_count": features["words"],
            "sentence_count": features["sentences"],
            "paragraph_count": features["paragraphs"],
            "average_sentence_length": round(features["avg_sentence_length"], 2),
            "sentence_length_std": round(features["sentence_length_std"], 2),
            "type_token_ratio": round(features["type_token_ratio"], 3),
            "lexical_diversity_mattr": round(features["lexical_diversity_mattr"], 3),
            "readability_proxy": round(features["readability"], 1),
        },
        "signals": signal_list,
        "top_contributors": [name for name, _ in ranked[:3]],
        "paragraphs": _score_paragraphs(text, weights),
        "explanations": [
            "Score is a logistic blend of sentence uniformity, length-robust lexical "
            "diversity (MATTR), word/phrase repetition, sentence-opener diversity, "
            "templated-language density, punctuation, and hapax rate.",
            "Longer samples and more decisive signals raise the confidence value.",
            "Default weights are informed priors — calibrate with train_logistic() "
            "on labelled department writing for defensible results.",
        ],
    }
