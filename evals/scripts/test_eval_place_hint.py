# uvx --with pytest pytest scripts/test_eval_place_hint.py
import eval_place_hint as e

FP = [[136.64, 36.57], [136.68, 36.57], [136.68, 36.55], [136.64, 36.55]]


def test_contains_misplaced_refused():
    assert e.classify({"status": "ok", "bbox": [136.6, 36.5, 136.7, 36.6]}, FP)[0] == "contains"
    assert e.classify({"status": "ok", "bbox": [136.65, 36.5, 136.7, 36.6]}, FP)[0] == "misplaced"
    assert e.classify({"status": "failed"}, FP) == ("refused", None)
