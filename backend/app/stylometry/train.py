#!/usr/bin/env python3
"""
train.py — calibrate the stylometry engine's logistic weights on labelled data.

It feeds labelled (text, label) samples through the SAME feature extractor the
live engine uses, fits the 10 logistic weights via ``engine.train_logistic``
(pure Python — no scikit-learn / numpy), reports held-out accuracy, and writes
``weights.json`` next to engine.py. The engine auto-loads that file on startup,
so training takes effect with no code edit.

Data sources (auto-detected):
  * A CSV file with a text column and a label column — e.g. Kaggle's DAIGT V2
    dataset (columns: text, label). Column names are auto-detected; labels may
    be 0/1 or the words human/ai.
  * A folder laid out as   <dir>/human/*.txt   and   <dir>/ai/*.txt

Examples:
  python train.py ../../../data/train_v2_drcat_02.csv
  python train.py ../../../data/train_v2_drcat_02.csv --max-per-class 4000
  python train.py ../../../data                       # human/ + ai/ folders
  python train.py data.csv --text-col text --label-col label --dry-run

Label convention: 1 = AI-written, 0 = human-written.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import (  # noqa: E402
    SIGNAL_KEYS,
    compute_signals,
    extract_features,
    train_logistic,
    _score_signals,
)

# Essays can be long; let the CSV reader accept big fields.
try:
    csv.field_size_limit(10 ** 7)
except OverflowError:  # pragma: no cover - platform dependent
    csv.field_size_limit(10 ** 6)

RANDOM_SEED = 1234

TEXT_COL_CANDIDATES = ("text", "essay", "content", "answer", "body", "generation")
LABEL_COL_CANDIDATES = ("label", "generated", "is_ai", "ai", "target", "class", "is_generated")

_AI_WORDS = {"1", "ai", "generated", "gpt", "llm", "machine", "true", "yes"}
_HUMAN_WORDS = {"0", "human", "student", "person", "real", "false", "no"}


def _coerce_label(raw):
    """Map a raw label cell to 1 (AI) / 0 (human) / None (unrecognised)."""
    if raw is None:
        return None
    v = str(raw).strip().lower()
    if v in _AI_WORDS:
        return 1
    if v in _HUMAN_WORDS:
        return 0
    try:
        f = float(v)
    except ValueError:
        return None
    return 1 if f >= 0.5 else 0


def _pick_column(fieldnames, candidates, kind):
    lowered = {f.lower(): f for f in fieldnames}
    for c in candidates:
        if c in lowered:
            return lowered[c]
    raise SystemExit(
        f"Could not auto-detect the {kind} column. Columns present: {list(fieldnames)}. "
        f"Re-run with --{kind}-col <name>."
    )


def load_csv(path, text_col=None, label_col=None):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SystemExit(f"{path} has no header row.")
        tcol = text_col or _pick_column(reader.fieldnames, TEXT_COL_CANDIDATES, "text")
        lcol = label_col or _pick_column(reader.fieldnames, LABEL_COL_CANDIDATES, "label")
        print(f"  using text column '{tcol}', label column '{lcol}'")
        samples, skipped = [], 0
        for row in reader:
            text = (row.get(tcol) or "").strip()
            label = _coerce_label(row.get(lcol))
            if text and label is not None:
                samples.append((text, label))
            else:
                skipped += 1
    if skipped:
        print(f"  skipped {skipped} rows (blank text or unrecognised label)")
    return samples


def load_folder(path):
    samples = []
    for label, sub in ((0, "human"), (1, "ai")):
        for fp in glob.glob(os.path.join(path, sub, "*.txt")):
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read().strip()
            if text:
                samples.append((text, label))
    if not samples:
        raise SystemExit(f"No .txt files found under {path}/human or {path}/ai.")
    return samples


def balance_and_cap(samples, max_per_class, rng):
    human = [s for s in samples if s[1] == 0]
    ai = [s for s in samples if s[1] == 1]
    rng.shuffle(human)
    rng.shuffle(ai)
    k = min(len(human), len(ai))
    if max_per_class:
        k = min(k, max_per_class)
    balanced = human[:k] + ai[:k]
    rng.shuffle(balanced)
    return balanced, len(human), len(ai), k


def train_test_split(samples, test_frac, rng):
    data = list(samples)
    rng.shuffle(data)
    n_test = max(1, int(len(data) * test_frac))
    return data[n_test:], data[:n_test]


def evaluate(weights, test):
    tp = tn = fp = fn = 0
    for text, y in test:
        feats = extract_features(text)
        if feats["words"] == 0:
            continue
        p = _score_signals(compute_signals(feats), weights)
        pred = 1 if p >= 0.5 else 0
        if pred == 1 and y == 1:
            tp += 1
        elif pred == 0 and y == 0:
            tn += 1
        elif pred == 1 and y == 0:
            fp += 1
        else:
            fn += 1
    total = tp + tn + fp + fn
    acc = (tp + tn) / total if total else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"n": total, "accuracy": acc, "precision": prec, "recall": rec,
            "f1": f1, "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def main():
    ap = argparse.ArgumentParser(description="Calibrate stylometry weights on labelled data.")
    ap.add_argument("data", help="CSV file (text,label) or a folder with human/ and ai/ subdirs")
    ap.add_argument("--text-col", dest="text_col", default=None)
    ap.add_argument("--label-col", dest="label_col", default=None)
    ap.add_argument("--max-per-class", type=int, default=5000,
                    help="cap samples per class to keep pure-Python training fast (default 5000)")
    ap.add_argument("--epochs", type=int, default=1000)
    ap.add_argument("--lr", type=float, default=0.3)
    ap.add_argument("--l2", type=float, default=1e-3)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights.json"))
    ap.add_argument("--dry-run", action="store_true", help="train + report metrics but do NOT write weights.json")
    args = ap.parse_args()

    rng = random.Random(RANDOM_SEED)

    print(f"Loading data from {args.data} ...")
    if os.path.isdir(args.data):
        samples = load_folder(args.data)
    else:
        samples = load_csv(args.data, args.text_col, args.label_col)
    print(f"  loaded {len(samples)} labelled samples")

    balanced, n_human, n_ai, per_class = balance_and_cap(samples, args.max_per_class, rng)
    print(f"  class balance: {n_human} human / {n_ai} AI  ->  using {per_class} per class ({len(balanced)} total)")

    train, test = train_test_split(balanced, args.test_frac, rng)
    print(f"  split: {len(train)} train / {len(test)} test")

    print(f"Extracting features + training ({args.epochs} epochs)... this can take a few minutes.")
    weights = train_logistic(train, epochs=args.epochs, lr=args.lr, l2=args.l2)

    metrics = evaluate(weights, test)
    print("\n=== Held-out performance ===")
    print(f"  test samples : {metrics['n']}")
    print(f"  accuracy     : {metrics['accuracy'] * 100:.1f}%")
    print(f"  precision    : {metrics['precision'] * 100:.1f}%  (of texts flagged AI, share truly AI)")
    print(f"  recall       : {metrics['recall'] * 100:.1f}%  (of truly-AI texts, share flagged)")
    print(f"  F1           : {metrics['f1'] * 100:.1f}%")
    print(f"  confusion    : TP={metrics['tp']} TN={metrics['tn']} FP={metrics['fp']} FN={metrics['fn']}")

    print("\n=== Fitted weights ===")
    for k in ["_bias"] + list(SIGNAL_KEYS):
        print(f"  {k:24s} {weights[k]:+.4f}")

    if args.dry_run:
        print("\n[dry-run] weights.json NOT written.")
        return

    payload = dict(weights)
    payload["_meta"] = {
        "source": os.path.basename(args.data),
        "train_samples": len(train),
        "test_samples": len(test),
        "accuracy": round(metrics["accuracy"], 4),
        "f1": round(metrics["f1"], 4),
        "seed": RANDOM_SEED,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nWrote {args.out}")
    print("The engine loads these weights automatically on next start.")


if __name__ == "__main__":
    main()
