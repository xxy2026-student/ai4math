"""Run bounded randomized counterexample search from a versioned JSON spec.

This driver produces *bounded empirical evidence*.  ``VERDICT: PASS`` means
only that all declared samples passed the predicate; it is not a proof.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import posixpath
import random
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import write_evidence, verdict


ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


class SpecError(ValueError):
    """Raised when a search spec is unsafe or internally inconsistent."""


def _safe_rel(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SpecError(f"{label} must be a non-empty repository-relative path")
    value = raw.strip().replace("\\", "/")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise SpecError(f"{label} must be repository-relative")
    rel = posixpath.normpath(value)
    if rel in {"", ".", ".."} or rel.startswith("../"):
        raise SpecError(f"{label} escapes the repository")
    root = os.path.realpath(os.getcwd())
    absolute = os.path.realpath(os.path.join(root, *rel.split("/")))
    try:
        inside = os.path.commonpath((root, absolute)) == root
    except ValueError:
        inside = False
    if not inside:
        raise SpecError(f"{label} escapes the repository")
    return rel


def _load_spec(path: str) -> tuple[str, dict[str, Any]]:
    spec_rel = _safe_rel(path, "spec path")
    try:
        with open(spec_rel, encoding="utf-8-sig") as handle:
            spec = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"cannot read spec: {exc}") from exc
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")

    claim_id = spec.get("conjecture")
    problem = spec.get("problem")
    if not isinstance(claim_id, str) or not ID_RE.fullmatch(claim_id):
        raise SpecError("spec conjecture must be a valid claim id")
    if not isinstance(problem, str) or not problem or "/" in problem or "\\" in problem:
        raise SpecError("spec problem must be one problem-directory name")
    expected_spec_prefix = f"problems/{problem}/specs/"
    if not spec_rel.startswith(expected_spec_prefix) or not spec_rel.endswith(".json"):
        raise SpecError(f"spec path must be a JSON file below {expected_spec_prefix}")

    predicate = _safe_rel(spec.get("predicate"), "predicate")
    predicate_prefix = f"problems/{problem}/predicates/"
    if not predicate.startswith(predicate_prefix) or not predicate.endswith(".py"):
        raise SpecError(f"predicate must be a Python file below {predicate_prefix}")
    if not os.path.isfile(predicate):
        raise SpecError(f"predicate does not exist: {predicate}")

    evidence = _safe_rel(spec.get("evidence"), "evidence")
    evidence_prefix = f"problems/{problem}/results/"
    if not evidence.startswith(evidence_prefix) or not evidence.endswith(".json"):
        raise SpecError(f"evidence must be a JSON file below {evidence_prefix}")

    samples = spec.get("n_samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise SpecError("n_samples must be an integer >= 1")
    seed = spec.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SpecError("seed must be an integer")

    params = spec.get("params")
    if not isinstance(params, dict) or not params:
        raise SpecError("params must be a non-empty object")
    for name, bounds in params.items():
        if not isinstance(name, str) or not name:
            raise SpecError("every parameter name must be a non-empty string")
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise SpecError(f"parameter {name!r} bounds must be [lower, upper]")
        lower, upper = bounds
        if (
            isinstance(lower, bool)
            or isinstance(upper, bool)
            or not isinstance(lower, (int, float))
            or not isinstance(upper, (int, float))
            or not math.isfinite(float(lower))
            or not math.isfinite(float(upper))
            or float(lower) > float(upper)
        ):
            raise SpecError(f"parameter {name!r} has invalid finite ordered bounds")

    normalised = dict(spec)
    normalised.update(
        {
            "predicate": predicate,
            "evidence": evidence,
            "n_samples": samples,
            "seed": seed,
        }
    )
    return spec_rel, normalised


def load_predicate(path: str):
    module_spec = importlib.util.spec_from_file_location("ai4research_claim_predicate", path)
    if module_spec is None or module_spec.loader is None:
        raise SpecError(f"cannot load predicate module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    check = getattr(module, "check", None)
    if not callable(check):
        raise SpecError("predicate module must define callable check(params)")
    return check


def _base_evidence(spec_rel: str, spec: dict[str, Any]) -> dict[str, Any]:
    claim_id = spec["conjecture"]
    def digest(path: str) -> str:
        with open(path, "rb") as handle:
            return "sha256:" + hashlib.sha256(handle.read()).hexdigest()

    return {
        "claim_id": claim_id,
        "conjecture": claim_id,
        "problem": spec["problem"],
        "spec": spec_rel,
        "predicate": spec["predicate"],
        "spec_sha256": digest(spec_rel),
        "predicate_sha256": digest(spec["predicate"]),
        "verifier_sha256": digest(os.path.abspath(__file__)),
        "evidence": spec["evidence"],
        "seed": spec["seed"],
        "n_samples": spec["n_samples"],
        "method": "bounded-random-search",
    }


def run(spec_rel: str, spec: dict[str, Any]) -> int:
    check = load_predicate(spec["predicate"])
    rng = random.Random(spec["seed"])
    names = list(spec["params"])
    samples = spec["n_samples"]
    base = _base_evidence(spec_rel, spec)

    for index in range(samples):
        params = {
            name: rng.uniform(float(spec["params"][name][0]), float(spec["params"][name][1]))
            for name in names
        }
        try:
            passed = bool(check(params))
        except Exception as exc:  # the evidence record must preserve predicate failures
            write_evidence(
                spec["evidence"],
                {
                    **base,
                    "result": "ERROR",
                    "checked": index,
                    "at_sample": index + 1,
                    "params": params,
                    "error": repr(exc),
                },
            )
            verdict("ERROR", at=index + 1, error=type(exc).__name__)
            return 1
        if not passed:
            write_evidence(
                spec["evidence"],
                {
                    **base,
                    "result": "REFUTED",
                    "checked": index + 1,
                    "counterexample": params,
                },
            )
            print("counterexample:", json.dumps(params, ensure_ascii=False, sort_keys=True))
            verdict("REFUTED", checked=index + 1)
            return 0

    write_evidence(
        spec["evidence"], {**base, "result": "PASS", "checked": samples}
    )
    verdict("PASS", checked=samples)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    args = parser.parse_args(argv)
    try:
        spec_rel, spec = _load_spec(args.spec)
        return run(spec_rel, spec)
    # A missing predicate dependency (or another load-time failure) must still
    # end in one machine-readable ERROR verdict rather than a bare traceback.
    except Exception as exc:
        verdict("ERROR", reason=type(exc).__name__)
        sys.stderr.write(f"counterexample_search: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
