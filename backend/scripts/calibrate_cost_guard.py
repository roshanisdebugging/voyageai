"""Fit rejection boundaries on calibration data only; never read the test matrix."""

import argparse
import json
from pathlib import Path

from cost_guard import LABELS, POLICY_PATH, ROOT, SemanticClassifier, corpus_fingerprint


def fit_boundaries(rows):
    thresholds = {}
    metrics = {}
    for label in sorted(LABELS):
        # Require an absolute floor and a nonzero competing-class margin even
        # when a small calibration set happens to contain no hard negatives.
        candidates = [r for r in rows if max(r[1], key=r[1].get) == label]
        best = None
        for similarity in [i / 100 for i in range(45, 96)]:
            for margin in [i / 100 for i in range(3, 31)]:
                accepted = [
                    expected for expected, scores in candidates
                    if scores[label] > similarity
                    and scores[label] - max(v for k, v in scores.items() if k != label) > margin
                ]
                tp = sum(expected == label for expected in accepted)
                fp = len(accepted) - tp
                # Zero false class acceptance on calibration is a hard constraint.
                if fp:
                    continue
                rank = (tp, -similarity, -margin)
                if best is None or rank > best[0]:
                    best = (rank, similarity, margin, tp)
        if best is None or best[3] == 0:
            raise ValueError(f"No usable boundary for {label}; improve the model, not the test set")
        _, similarity, margin, tp = best
        thresholds[label] = {"similarity": similarity, "margin": margin}
        metrics[label] = {"accepted_correct": tp, "false_accepts": 0, "total": sum(e == label for e, _ in rows)}
    return thresholds, metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", type=Path, default=POLICY_PATH)
    args = parser.parse_args()
    # A nonexistent path deliberately avoids loading an old policy while fitting.
    classifier = SemanticClassifier(download=args.download, policy_path=ROOT / ".uncalibrated")
    data = json.loads((ROOT / "cost_guard_calibration.json").read_text(encoding="utf-8"))
    examples = [(label, query) for label, queries in data.items() for query in queries]
    anchors = {q for queries in classifier.corpus["anchors"].values() for q in queries}
    if any(query in anchors for _, query in examples):
        raise ValueError("Calibration utterances overlap routing anchors")
    scores = classifier.score_many([query for _, query in examples])
    thresholds, metrics = fit_boundaries([(label, s) for (label, _), s in zip(examples, scores)])
    policy = {
        "fingerprint": corpus_fingerprint(classifier.corpus),
        "artifact_fingerprint": classifier.artifact_fingerprint,
        "thresholds": thresholds,
        "calibration": {"examples": len(examples), "metrics": metrics},
    }
    args.output.write_text(json.dumps(policy, indent=2) + "\n")
    print(json.dumps(policy, indent=2))


if __name__ == "__main__":
    main()
