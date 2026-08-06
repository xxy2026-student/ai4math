"""AI4Research claim/evidence gate (standard library only).

The gate deliberately checks *provenance and consistency*, not mathematical
truth.  In particular, ``evidence-supported`` means that a registered evidence
driver reproduced a bounded PASS result; it never means "proved".  Likewise,
``reviewed`` means that a structured independent audit reports PASS; it does
not encode a human CLAIM_GATE or RELEASE_GATE decision.

Public API:

``check_text(path, text, root='.')``
    Validate prospective contents before a write is committed.
``check_file(path, root='.')``
    Validate an existing claim file.
``check_tree(root='.')``
    Validate every managed claim file below ``problems/``.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
from typing import Any


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


ALLOWED = {"open", "evidence-supported", "reviewed", "refuted", "abandoned"}
EVIDENCE_STATUSES = {"evidence-supported": "PASS", "refuted": "REFUTED"}
LEGACY_STATUSES = {
    "numeric-verified": "evidence-supported",
    "proved": "reviewed (or evidence-supported, depending on what was actually checked)",
}
REGISTRY_PATH = "verifiers/registry.json"
VERDICT_RE = re.compile(
    r"^[ \t]*VERDICT:[ \t]*(PASS|REFUTED|ERROR)(?:[ \t]+[^\r\n]*)?[ \t]*$",
    re.MULTILINE,
)
CLAIM_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
HUMAN_DISPOSITIONS = {"pending", "accepted-with-scope", "revise", "reject"}
FORMAL_STATES = {"not-requested", "lean-verified", "failed"}


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    """Parse the tiny YAML subset used by claim/audit frontmatter.

    Supported syntax is deliberately small: top-level ``key: value`` pairs and
    one nested mapping level.  This keeps the gate dependency-free and makes
    the accepted metadata format explicit.
    """
    if not text.startswith("---"):
        return None
    match = re.search(r"\n---\s*(\n|$)", text[3:])
    if not match:
        return None
    data: dict[str, Any] = {}
    current: str | None = None
    for line in text[3 : 3 + match.start()].splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        item = re.match(r"^(\s*)([A-Za-z_][\w.-]*):\s*(.*?)\s*$", line)
        if not item:
            continue
        indent, key, value = item.groups()
        value = value.strip('"').strip("'")
        if indent and current is not None:
            nested = data.get(current)
            if isinstance(nested, dict):
                nested[key] = value
        elif not indent:
            if value == "":
                data[key] = {}
                current = key
            else:
                data[key] = value
                current = None
    return data


def claim_review_hash(text: str) -> str:
    """Bind an audit to the claim while allowing workflow-only transitions.

    Audits are normally written while a claim is still open. Moving that exact
    claim to ``reviewed`` adds status/audit and later a human disposition, so
    those control fields are excluded. The body, assumptions, dependencies,
    evidence references and all other metadata remain bound.
    """
    data = parse_frontmatter(text)
    if data is None:
        raise ValueError("claim review hash requires frontmatter")
    match = re.search(r"\n---\s*(\n|$)", text[3:])
    if match is None:
        raise ValueError("claim review hash cannot find closing frontmatter")
    body = text[3 + match.end() :].replace("\r\n", "\n").replace("\r", "\n")
    ignored = {"status", "audit", "audit_sha256", "human_disposition", "decision"}
    bound = {key: value for key, value in data.items() if key not in ignored}
    payload = json.dumps(
        {"frontmatter": bound, "body": body},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def venv_python(root: str) -> str:
    """Return the repository venv interpreter, or this interpreter."""
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        path = os.path.join(root, ".venv", *rel)
        if os.path.exists(path):
            return path
    return sys.executable


def _normalise_rel(raw: Any, root: str, label: str) -> tuple[str, str]:
    """Return a safe repository-relative POSIX path and its absolute path."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty repository-relative path")
    value = raw.strip().replace("\\", "/")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"{label} must be repository-relative: {raw!r}")
    rel = posixpath.normpath(value)
    if rel in {"", ".", ".."} or rel.startswith("../"):
        raise ValueError(f"{label} escapes the repository: {raw!r}")
    root_real = os.path.realpath(root)
    absolute = os.path.realpath(os.path.join(root_real, *rel.split("/")))
    try:
        inside = os.path.commonpath((root_real, absolute)) == root_real
    except ValueError:
        inside = False
    if not inside:
        raise ValueError(f"{label} escapes the repository: {raw!r}")
    return rel, absolute


def _managed_location(path: Any, root: str) -> tuple[str, str | None]:
    """Return ``(repo_relative_path, problem_name_or_none)``."""
    root_abs = os.path.abspath(root)
    path_abs = os.path.abspath(path if os.path.isabs(str(path)) else os.path.join(root_abs, str(path)))
    try:
        rel = os.path.relpath(path_abs, root_abs).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/"), None
    parts = rel.split("/")
    lowered = [part.lower() for part in parts]
    if len(parts) >= 4 and lowered[0] == "problems" and lowered[2] in {
        "conjectures",
        "lemmas",
    } and rel.lower().endswith(".md"):
        return rel, parts[1]
    return rel, None


def _load_json(path: str, label: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label} as JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _load_registry(root: str) -> dict[str, dict[str, Any]]:
    _, path = _normalise_rel(REGISTRY_PATH, root, "verifier registry")
    registry = _load_json(path, "verifier registry")
    entries = registry.get("claim_evidence")
    if not isinstance(entries, dict):
        raise ValueError("verifier registry must contain a claim_evidence object")
    clean: dict[str, dict[str, Any]] = {}
    for raw_path, config in entries.items():
        rel, _ = _normalise_rel(raw_path, root, "registered verifier")
        if not rel.startswith("verifiers/") or rel == REGISTRY_PATH:
            raise ValueError(f"registered verifier is outside verifiers/: {raw_path!r}")
        if not isinstance(config, dict):
            raise ValueError(f"registry entry for {rel} must be an object")
        clean[rel] = config
    return clean


def _read_signature(path: str) -> tuple[int, int, str] | None:
    try:
        stat = os.stat(path)
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        return stat.st_mtime_ns, stat.st_size, digest
    except OSError:
        return None


def _parse_verify_args(raw: Any) -> list[str]:
    if not isinstance(raw, str):
        raise ValueError("verify.args must be a string")
    try:
        args = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise ValueError(f"cannot parse verify.args: {exc}") from exc
    if any(arg in {"-c", "--command"} for arg in args):
        raise ValueError("inline commands (-c/--command) are forbidden")
    if len(args) != 2 or args[0] != "--spec":
        raise ValueError("registered claim verifiers require exactly: --spec <spec.json>")
    return args


def _validate_spec(
    data: dict[str, Any], problem: str, claim_id: str, root: str
) -> tuple[str, str, dict[str, Any]]:
    verify = data.get("verify")
    if not isinstance(verify, dict):
        raise ValueError("evidence status requires a verify mapping")
    script_rel, script_abs = _normalise_rel(verify.get("script"), root, "verify.script")
    registry = _load_registry(root)
    config = registry.get(script_rel)
    if config is None or config.get("kind") != "bounded-claim-evidence":
        raise ValueError(f"verify.script is not a registered claim-evidence driver: {script_rel}")
    if not os.path.isfile(script_abs):
        raise ValueError(f"registered verifier does not exist: {script_rel}")

    args = _parse_verify_args(verify.get("args", ""))
    spec_rel, spec_abs = _normalise_rel(args[1], root, "--spec")
    expected_spec_prefix = f"problems/{problem}/specs/"
    if not spec_rel.startswith(expected_spec_prefix) or not spec_rel.endswith(".json"):
        raise ValueError(f"spec must be a JSON file below {expected_spec_prefix}")
    spec = _load_json(spec_abs, "spec")
    if spec.get("conjecture") != claim_id:
        raise ValueError(
            f"spec conjecture {spec.get('conjecture')!r} does not match claim id {claim_id!r}"
        )
    if spec.get("problem") != problem:
        raise ValueError(
            f"spec problem {spec.get('problem')!r} does not match claim problem {problem!r}"
        )
    samples = spec.get("n_samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("spec n_samples must be an integer >= 1")

    predicate_rel, predicate_abs = _normalise_rel(
        spec.get("predicate"), root, "spec predicate"
    )
    expected_predicate_prefix = f"problems/{problem}/predicates/"
    if not predicate_rel.startswith(expected_predicate_prefix) or not predicate_rel.endswith(
        ".py"
    ):
        raise ValueError(
            f"predicate must be a Python file below {expected_predicate_prefix}"
        )
    if not os.path.isfile(predicate_abs):
        raise ValueError(f"spec predicate does not exist: {predicate_rel}")
    spec = dict(spec)
    spec["predicate"] = predicate_rel

    evidence_rel, _ = _normalise_rel(data.get("evidence"), root, "claim evidence")
    spec_evidence_rel, _ = _normalise_rel(spec.get("evidence"), root, "spec evidence")
    expected_evidence_prefix = f"problems/{problem}/results/"
    if not evidence_rel.startswith(expected_evidence_prefix) or not evidence_rel.endswith(".json"):
        raise ValueError(f"evidence must be a JSON file below {expected_evidence_prefix}")
    if spec_evidence_rel != evidence_rel:
        raise ValueError(
            f"spec evidence {spec_evidence_rel!r} does not match claim evidence {evidence_rel!r}"
        )
    return script_rel, spec_rel, spec


def _validate_evidence(
    *,
    data: dict[str, Any],
    problem: str,
    claim_id: str,
    spec_rel: str,
    spec: dict[str, Any],
    script_rel: str,
    expected_result: str,
    root: str,
) -> None:
    evidence_rel, evidence_abs = _normalise_rel(data.get("evidence"), root, "claim evidence")
    evidence = _load_json(evidence_abs, "evidence")
    _, spec_abs = _normalise_rel(spec_rel, root, "evidence spec")
    _, predicate_abs = _normalise_rel(spec.get("predicate"), root, "evidence predicate")
    _, script_abs = _normalise_rel(script_rel, root, "evidence verifier")
    if evidence.get("claim_id") != claim_id:
        raise ValueError(
            f"evidence claim_id {evidence.get('claim_id')!r} does not match {claim_id!r}"
        )
    if "conjecture" in evidence and evidence.get("conjecture") != claim_id:
        raise ValueError("evidence conjecture alias does not match claim id")
    if evidence.get("problem") != problem:
        raise ValueError(
            f"evidence problem {evidence.get('problem')!r} does not match {problem!r}"
        )
    try:
        evidence_spec_rel, _ = _normalise_rel(evidence.get("spec"), root, "evidence spec")
        evidence_self_rel, _ = _normalise_rel(
            evidence.get("evidence"), root, "evidence self path"
        )
    except ValueError as exc:
        raise ValueError(f"invalid evidence identity: {exc}") from exc
    if evidence_spec_rel != spec_rel:
        raise ValueError(f"evidence spec {evidence_spec_rel!r} does not match {spec_rel!r}")
    if evidence_self_rel != evidence_rel:
        raise ValueError(
            f"evidence self path {evidence_self_rel!r} does not match {evidence_rel!r}"
        )
    if evidence.get("predicate") != spec.get("predicate"):
        raise ValueError("evidence predicate does not match the spec predicate")
    expected_hashes = {
        "spec_sha256": file_sha256(spec_abs),
        "predicate_sha256": file_sha256(predicate_abs),
        "verifier_sha256": file_sha256(script_abs),
    }
    for key, expected_hash in expected_hashes.items():
        if evidence.get(key) != expected_hash:
            raise ValueError(
                f"evidence {key} does not bind current content; expected {expected_hash}"
            )
    if evidence.get("result") != expected_result:
        raise ValueError(
            f"evidence result {evidence.get('result')!r} does not match {expected_result!r}"
        )
    checked = evidence.get("checked")
    samples = spec["n_samples"]
    if isinstance(checked, bool) or not isinstance(checked, int) or checked < 1:
        raise ValueError("evidence checked must be an integer >= 1")
    if checked > samples:
        raise ValueError("evidence checked exceeds spec n_samples")
    if expected_result == "PASS" and checked != samples:
        raise ValueError("PASS evidence must check exactly spec n_samples samples")
    if expected_result == "REFUTED" and "counterexample" not in evidence:
        raise ValueError("REFUTED evidence must include a counterexample")


def _validate_review(
    data: dict[str, Any], problem: str, claim_id: str, text: str, root: str
) -> None:
    audit_rel, audit_abs = _normalise_rel(data.get("audit"), root, "audit")
    expected_prefix = f"problems/{problem}/audits/"
    if not audit_rel.startswith(expected_prefix):
        raise ValueError(f"audit must be below {expected_prefix}")
    if not os.path.isfile(audit_abs):
        raise ValueError(f"audit file does not exist: {audit_rel}")
    if audit_rel.endswith(".json"):
        audit = _load_json(audit_abs, "audit")
    elif audit_rel.endswith(".md"):
        try:
            with open(audit_abs, encoding="utf-8-sig") as handle:
                audit = parse_frontmatter(handle.read())
        except OSError as exc:
            raise ValueError(f"cannot read audit: {exc}") from exc
        if audit is None:
            raise ValueError("Markdown audit must contain structured frontmatter")
    else:
        raise ValueError("audit must be a .json or frontmatter-bearing .md file")
    if audit.get("result") != "PASS":
        raise ValueError("reviewed status requires structured audit result: PASS")
    if audit.get("claim_id") != claim_id:
        raise ValueError(
            f"audit claim_id {audit.get('claim_id')!r} does not match {claim_id!r}"
        )
    if audit.get("problem") != problem:
        raise ValueError(
            f"audit problem {audit.get('problem')!r} does not match {problem!r}"
        )
    expected_audit_hash = file_sha256(audit_abs)
    if data.get("audit_sha256") != expected_audit_hash:
        raise ValueError(
            "reviewed claim audit_sha256 does not bind the exact audit file; "
            f"expected {expected_audit_hash}"
        )
    expected_hash = claim_review_hash(text)
    if audit.get("claim_review_hash") != expected_hash:
        raise ValueError(
            "audit claim_review_hash does not bind this exact claim version; "
            f"expected {expected_hash}"
        )
    evidence_value = data.get("evidence")
    if evidence_value:
        evidence_rel, evidence_abs = _normalise_rel(
            evidence_value, root, "reviewed claim evidence"
        )
        expected_evidence_hash = file_sha256(evidence_abs)
        if audit.get("evidence") != evidence_rel \
                or audit.get("evidence_sha256") != expected_evidence_hash:
            raise ValueError(
                "audit must bind the reviewed evidence path and exact evidence_sha256"
            )


def _run_evidence_check(
    data: dict[str, Any], problem: str, claim_id: str, status: str, root: str
) -> None:
    script_rel, spec_rel, spec = _validate_spec(data, problem, claim_id, root)
    _, script_abs = _normalise_rel(script_rel, root, "verify.script")
    evidence_rel, evidence_abs = _normalise_rel(data.get("evidence"), root, "claim evidence")
    before = _read_signature(evidence_abs)
    cmd = [venv_python(root), script_abs, "--spec", spec_rel]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            cwd=os.path.abspath(root),
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"registered verifier timed out after 240s: {script_rel}") from exc
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    verdicts = VERDICT_RE.findall(output)
    if len(verdicts) != 1:
        raise ValueError(
            f"registered verifier must emit exactly one VERDICT line; got {len(verdicts)}\n"
            f"output tail:\n{output[-800:]}"
        )
    if proc.returncode != 0:
        raise ValueError(
            f"registered verifier exited {proc.returncode} with VERDICT: {verdicts[0]}\n"
            f"output tail:\n{output[-800:]}"
        )
    expected = EVIDENCE_STATUSES[status]
    if verdicts[0] != expected:
        raise ValueError(
            f"status {status!r} requires VERDICT: {expected}, got VERDICT: {verdicts[0]}"
        )
    after = _read_signature(evidence_abs)
    if after is None:
        raise ValueError(f"registered verifier did not create evidence: {evidence_rel}")
    if before is not None and after == before:
        raise ValueError("registered verifier did not refresh the declared evidence file")
    _validate_evidence(
        data=data,
        problem=problem,
        claim_id=claim_id,
        spec_rel=spec_rel,
        spec=spec,
        script_rel=script_rel,
        expected_result=expected,
        root=root,
    )


def check_text(path: Any, text: str, root: str = ".",
               execute_verifiers: bool = True) -> tuple[bool, str]:
    """Validate prospective claim text, optionally refreshing executable evidence."""
    norm, path_problem = _managed_location(path, root)
    if path_problem is None:
        return True, ""
    data = parse_frontmatter(text)
    if data is None:
        return False, (
            f"{norm}: missing YAML frontmatter; managed claims require id/problem/status metadata"
        )

    claim_id = data.get("id")
    if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id):
        return False, f"{norm}: id must match {CLAIM_ID_RE.pattern!r}, got {claim_id!r}"
    problem = data.get("problem")
    if problem != path_problem:
        return False, (
            f"{norm}: frontmatter problem {problem!r} must match path problem {path_problem!r}"
        )
    status = data.get("status")
    if isinstance(status, str) and status in LEGACY_STATUSES:
        return False, (
            f"{norm}: legacy status {status!r} is forbidden; use {LEGACY_STATUSES[status]}. "
            "No research evidence status means theorem proof."
        )
    if not isinstance(status, str) or status not in ALLOWED:
        return False, f"{norm}: status must be one of {sorted(ALLOWED)}, got {status!r}"

    disposition = data.get("human_disposition")
    if disposition not in HUMAN_DISPOSITIONS:
        return False, (
            f"{norm}: human_disposition must be one of "
            f"{sorted(HUMAN_DISPOSITIONS)}, got {disposition!r}"
        )
    decision = data.get("decision")
    if disposition == "pending":
        if decision not in {None, "", "null"}:
            return False, f"{norm}: pending human_disposition requires decision: null"
    elif not isinstance(decision, str) or not decision or decision == "null":
        return False, f"{norm}: non-pending human_disposition requires a decision id"
    else:
        try:
            from runner import decisions as decision_records

            decision_records.validate_claim_disposition(
                decision, disposition, root=root, subject_path=norm
            )
        except (ImportError, OSError, ValueError, json.JSONDecodeError) as exc:
            return False, (
                f"{norm}: decision record does not prove the declared "
                f"human_disposition: {exc}"
            )

    formal = data.get("formal")
    if formal not in FORMAL_STATES:
        return False, f"{norm}: formal must be one of {sorted(FORMAL_STATES)}, got {formal!r}"
    if formal == "lean-verified":
        return False, (
            f"{norm}: formal: lean-verified is reserved but not yet machine-validated; "
            "keep formal: not-requested (or failed) until a Lean compiler evidence channel exists"
        )

    try:
        if status in EVIDENCE_STATUSES:
            if execute_verifiers:
                _run_evidence_check(data, problem, claim_id, status, root)
            else:
                script_rel, spec_rel, spec = _validate_spec(
                    data, problem, claim_id, root
                )
                _validate_evidence(
                    data=data,
                    problem=problem,
                    claim_id=claim_id,
                    spec_rel=spec_rel,
                    spec=spec,
                    script_rel=script_rel,
                    expected_result=EVIDENCE_STATUSES[status],
                    root=root,
                )
        elif status == "reviewed":
            _validate_review(data, problem, claim_id, text, root)
    except (OSError, ValueError) as exc:
        return False, f"{norm}: {exc}"
    return True, ""


def check_file(path: Any, root: str = ".",
               execute_verifiers: bool = True) -> tuple[bool, str]:
    """Validate an existing file; non-managed paths are ignored."""
    _, problem = _managed_location(path, root)
    if problem is None:
        return True, ""
    absolute = str(path) if os.path.isabs(str(path)) else os.path.join(root, str(path))
    if not os.path.exists(absolute):
        return True, ""
    try:
        with open(absolute, encoding="utf-8-sig") as handle:
            text = handle.read()
    except OSError as exc:
        return False, f"{path}: cannot read managed claim: {exc}"
    return check_text(path, text, root=root, execute_verifiers=execute_verifiers)


def check_tree(root: str = ".", execute_verifiers: bool = True) -> tuple[bool, str]:
    """Validate all managed claim files below ``problems/``."""
    problems = os.path.join(os.path.abspath(root), "problems")
    if not os.path.isdir(problems):
        return True, ""
    failures: list[str] = []
    paths: list[str] = []
    for directory, _, files in os.walk(problems):
        marker = os.path.basename(directory).lower()
        if marker not in {"conjectures", "lemmas"}:
            continue
        for name in files:
            if name.lower().endswith(".md"):
                absolute = os.path.join(directory, name)
                paths.append(os.path.relpath(absolute, root).replace("\\", "/"))
    for rel in sorted(paths):
        ok, message = check_file(
            rel, root=root, execute_verifiers=execute_verifiers
        )
        if not ok:
            failures.append(message)
    if failures:
        return False, "\n".join(f"- {failure}" for failure in failures)
    return True, ""


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="AI4Research claim/evidence gate")
    parser.add_argument("path", nargs="?", help="one managed claim file")
    parser.add_argument("--all", action="store_true", help="check all managed claim files")
    parser.add_argument(
        "--structure-only", action="store_true",
        help="validate identities and content hashes without executing verifier Python",
    )
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    if args.all == bool(args.path):
        parser.error("choose exactly one of PATH or --all")
    execute_verifiers = not args.structure_only
    ok, message = check_tree(
        args.root, execute_verifiers=execute_verifiers
    ) if args.all else check_file(
        args.path, args.root, execute_verifiers=execute_verifiers
    )
    if not ok:
        sys.stderr.write("[gate] " + message + "\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
