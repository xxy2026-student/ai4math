"""Regression tests for the claim/evidence boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import unittest
import uuid
from unittest import mock

from verifiers import gate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEARCH_DRIVER = PROJECT_ROOT / "verifiers" / "search" / "counterexample_search.py"

FAKE_DRIVER = r'''import hashlib
import json
import pathlib
import sys
import time

spec_rel = sys.argv[sys.argv.index("--spec") + 1].replace("\\", "/")
with open(spec_rel, encoding="utf-8") as handle:
    spec = json.load(handle)
result = spec.get("_result", "PASS")
checked = spec["n_samples"] if result == "PASS" else 1
payload = {
    "claim_id": spec.get("_evidence_claim_id", spec["conjecture"]),
    "conjecture": spec["conjecture"],
    "problem": spec["problem"],
    "spec": spec_rel,
    "predicate": spec["predicate"],
    "spec_sha256": "sha256:" + hashlib.sha256(pathlib.Path(spec_rel).read_bytes()).hexdigest(),
    "predicate_sha256": "sha256:" + hashlib.sha256(pathlib.Path(spec["predicate"]).read_bytes()).hexdigest(),
    "verifier_sha256": "sha256:" + hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
    "evidence": spec["evidence"],
    "seed": spec.get("seed", 0),
    "n_samples": spec["n_samples"],
    "method": "test-driver",
    "result": result,
    "checked": checked,
    "nonce": time.time_ns(),
}
if result == "REFUTED":
    payload["counterexample"] = {"x": 0.5}
path = pathlib.Path(spec["evidence"])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload), encoding="utf-8")
print("VERDICT:", result)
if spec.get("_double_verdict"):
    print("VERDICT:", result)
'''


class GateTestCase(unittest.TestCase):
    def setUp(self):
        # tempfile.TemporaryDirectory creates a private ACL on Windows.  A
        # UUID-named child of this pre-created fixture root inherits the
        # workspace ACL and therefore also works in a workspace-write sandbox.
        self.root = PROJECT_ROOT / "tests" / ".tmp" / f"gate-{uuid.uuid4().hex}"
        os.makedirs(self.root)
        for relative in (
            "verifiers",
            "problems/demo/conjectures",
            "problems/demo/lemmas",
            "problems/demo/specs",
            "problems/demo/results",
            "problems/demo/predicates",
            "problems/demo/audits",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.driver_rel = "verifiers/test_driver.py"
        (self.root / self.driver_rel).write_text(FAKE_DRIVER, encoding="utf-8")
        self._write_registry([self.driver_rel])
        (self.root / "problems/demo/predicates/p.py").write_text(
            "def check(params):\n    return True\n", encoding="utf-8"
        )
        self.claim_rel = "problems/demo/conjectures/C-1.md"
        self.spec_rel = "problems/demo/specs/c1.json"
        self.evidence_rel = "problems/demo/results/c1.json"
        self.spec = {
            "conjecture": "C-1",
            "problem": "demo",
            "predicate": "problems/demo/predicates/p.py",
            "params": {"x": [0.0, 1.0]},
            "n_samples": 2,
            "seed": 7,
            "evidence": self.evidence_rel,
        }
        self._write_spec()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_registry(self, scripts):
        entries = {
            script: {"kind": "bounded-claim-evidence"} for script in scripts
        }
        (self.root / "verifiers/registry.json").write_text(
            json.dumps({"version": 1, "claim_evidence": entries}), encoding="utf-8"
        )

    def _write_spec(self):
        (self.root / self.spec_rel).write_text(json.dumps(self.spec), encoding="utf-8")

    def _claim(self, status="evidence-supported", **fields):
        values = {
            "id": "C-1",
            "problem": "demo",
            "status": status,
            "script": self.driver_rel,
            "args": f"--spec {self.spec_rel}",
            "evidence": self.evidence_rel,
            "human_disposition": "pending",
            "decision": "null",
            "formal": "not-requested",
        }
        values.update(fields)
        if status in {"evidence-supported", "refuted"}:
            body = f"""---
id: {values['id']}
problem: {values['problem']}
status: {status}
verify:
  script: {values['script']}
  args: {values['args']}
evidence: {values['evidence']}
human_disposition: {values['human_disposition']}
decision: {values['decision']}
formal: {values['formal']}
---

# Test claim
"""
        elif status == "reviewed":
            body = f"""---
id: {values['id']}
problem: {values['problem']}
status: reviewed
audit: {values['audit']}
audit_sha256: {values.get('audit_sha256', '')}
human_disposition: {values['human_disposition']}
decision: {values['decision']}
formal: {values['formal']}
---

# Reviewed claim
"""
        else:
            body = f"""---
id: {values['id']}
problem: {values['problem']}
status: {status}
human_disposition: {values['human_disposition']}
decision: {values['decision']}
formal: {values['formal']}
---

# Claim
"""
        return textwrap.dedent(body)

    def test_rejects_unregistered_arbitrary_script_and_inline_command(self):
        arbitrary = self._claim(script="verifiers/arbitrary.py")
        ok, message = gate.check_text(self.claim_rel, arbitrary, root=self.root)
        self.assertFalse(ok)
        self.assertIn("not a registered", message)

        inline = self._claim(args="-c print('fake')")
        ok, message = gate.check_text(self.claim_rel, inline, root=self.root)
        self.assertFalse(ok)
        self.assertIn("inline commands", message)

    def test_review_requires_structured_pass_bound_to_claim_and_problem(self):
        audit_rel = "problems/demo/audits/C-1.md"
        audit_path = self.root / audit_rel
        audit_path.write_text("PASS\n", encoding="utf-8")
        ok, message = gate.check_text(
            self.claim_rel, self._claim("reviewed", audit=audit_rel), root=self.root
        )
        self.assertFalse(ok)
        self.assertIn("structured frontmatter", message)

        audit_path.write_text(
            "---\nresult: PASS\nclaim_id: C-OTHER\nproblem: demo\n---\n",
            encoding="utf-8",
        )
        ok, message = gate.check_text(
            self.claim_rel, self._claim("reviewed", audit=audit_rel), root=self.root
        )
        self.assertFalse(ok)
        self.assertIn("does not match", message)

        audit_path.write_text(
            "---\nresult: PASS\nclaim_id: C-1\nproblem: demo\n---\n",
            encoding="utf-8",
        )
        reviewed_claim = self._claim(
            "reviewed", audit=audit_rel,
            audit_sha256=gate.file_sha256(str(audit_path)),
        )
        ok, message = gate.check_text(
            self.claim_rel, reviewed_claim, root=self.root
        )
        self.assertFalse(ok)
        self.assertIn("claim_review_hash", message)

        audit_path.write_text(
            "---\nresult: PASS\nclaim_id: C-1\nproblem: demo\n"
            f"claim_review_hash: {gate.claim_review_hash(reviewed_claim)}\n---\n",
            encoding="utf-8",
        )
        reviewed_claim = self._claim(
            "reviewed", audit=audit_rel,
            audit_sha256=gate.file_sha256(str(audit_path)),
        )
        ok, message = gate.check_text(self.claim_rel, reviewed_claim, root=self.root)
        self.assertTrue(ok, message)

        changed = reviewed_claim.replace("# Reviewed claim", "# Materially changed claim")
        ok, message = gate.check_text(self.claim_rel, changed, root=self.root)
        self.assertFalse(ok)
        self.assertIn("claim_review_hash", message)

        audit_path.write_text(
            audit_path.read_text(encoding="utf-8") + "\nmaterial audit change\n",
            encoding="utf-8",
        )
        ok, message = gate.check_text(self.claim_rel, reviewed_claim, root=self.root)
        self.assertFalse(ok)
        self.assertIn("audit_sha256", message)

    def test_rejects_multiple_verdict_lines(self):
        self.spec["_double_verdict"] = True
        self._write_spec()
        ok, message = gate.check_text(
            self.claim_rel, self._claim(), root=self.root
        )
        self.assertFalse(ok)
        self.assertIn("exactly one VERDICT", message)

    def test_rejects_zero_samples_before_running_verifier(self):
        self.spec["n_samples"] = 0
        self._write_spec()
        ok, message = gate.check_text(
            self.claim_rel, self._claim(), root=self.root
        )
        self.assertFalse(ok)
        self.assertIn("n_samples", message)

    def test_counterexample_driver_itself_rejects_zero_samples(self):
        self.spec["n_samples"] = 0
        self._write_spec()
        proc = subprocess.run(
            [sys.executable, "-B", str(SEARCH_DRIVER), "--spec", self.spec_rel],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(gate.VERDICT_RE.findall(combined), ["ERROR"])
        self.assertIn("n_samples must be an integer >= 1", combined)

    def test_counterexample_driver_writes_explicit_bound_identity(self):
        proc = subprocess.run(
            [sys.executable, "-B", str(SEARCH_DRIVER), "--spec", self.spec_rel],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        self.assertEqual(proc.returncode, 0, combined)
        self.assertEqual(gate.VERDICT_RE.findall(combined), ["PASS"])
        evidence = json.loads((self.root / self.evidence_rel).read_text(encoding="utf-8"))
        self.assertEqual(evidence["claim_id"], "C-1")
        self.assertEqual(evidence["problem"], "demo")
        self.assertEqual(evidence["spec"], self.spec_rel)
        self.assertEqual(evidence["predicate"], self.spec["predicate"])
        self.assertEqual(evidence["evidence"], self.evidence_rel)
        self.assertEqual(evidence["result"], "PASS")
        self.assertEqual(evidence["checked"], self.spec["n_samples"])

    def test_rejects_spec_and_evidence_identity_mismatches(self):
        ok, message = gate.check_text(
            self.claim_rel, self._claim(problem="other"), root=self.root
        )
        self.assertFalse(ok)
        self.assertIn("must match path problem", message)

        self.spec["problem"] = "other"
        self._write_spec()
        ok, message = gate.check_text(self.claim_rel, self._claim(), root=self.root)
        self.assertFalse(ok)
        self.assertIn("spec problem", message)

        self.spec["problem"] = "demo"
        self.spec["conjecture"] = "C-OTHER"
        self._write_spec()
        ok, message = gate.check_text(self.claim_rel, self._claim(), root=self.root)
        self.assertFalse(ok)
        self.assertIn("spec conjecture", message)

        self.spec["conjecture"] = "C-1"
        self.spec["_evidence_claim_id"] = "C-OTHER"
        self._write_spec()
        ok, message = gate.check_text(self.claim_rel, self._claim(), root=self.root)
        self.assertFalse(ok)
        self.assertIn("evidence claim_id", message)

        self.spec.pop("_evidence_claim_id")
        self.spec["evidence"] = "problems/demo/results/other.json"
        self._write_spec()
        ok, message = gate.check_text(self.claim_rel, self._claim(), root=self.root)
        self.assertFalse(ok)
        self.assertIn("does not match claim evidence", message)

    def test_legacy_proof_like_statuses_are_rejected(self):
        for status in ("numeric-verified", "proved"):
            with self.subTest(status=status):
                ok, message = gate.check_text(
                    self.claim_rel, self._claim(status), root=self.root
                )
                self.assertFalse(ok)
                self.assertIn("legacy status", message)

    def test_human_and_formal_axes_cannot_be_self_declared(self):
        ok, message = gate.check_text(
            self.claim_rel,
            self._claim("open", human_disposition="accepted-with-scope", decision="null"),
            root=self.root,
        )
        self.assertFalse(ok)
        self.assertIn("decision id", message)

        ok, message = gate.check_text(
            self.claim_rel,
            self._claim(
                "open",
                human_disposition="accepted-with-scope",
                decision="D-fake",
            ),
            root=self.root,
        )
        self.assertFalse(ok)
        self.assertIn("decision record does not prove", message)

        ok, message = gate.check_text(
            self.claim_rel,
            self._claim("open", formal="lean-verified"),
            root=self.root,
        )
        self.assertFalse(ok)
        self.assertIn("not yet machine-validated", message)

    def test_structure_only_check_never_runs_code_and_binds_input_hashes(self):
        claim = self._claim()
        ok, message = gate.check_text(self.claim_rel, claim, root=self.root)
        self.assertTrue(ok, message)
        with mock.patch.object(gate.subprocess, "run") as run:
            ok, message = gate.check_text(
                self.claim_rel, claim, root=self.root, execute_verifiers=False
            )
        self.assertTrue(ok, message)
        run.assert_not_called()

        (self.root / "problems/demo/predicates/p.py").write_text(
            "def check(params):\n    return False\n", encoding="utf-8"
        )
        with mock.patch.object(gate.subprocess, "run") as run:
            ok, message = gate.check_text(
                self.claim_rel, claim, root=self.root, execute_verifiers=False
            )
        self.assertFalse(ok)
        self.assertIn("predicate_sha256", message)
        run.assert_not_called()

    def test_valid_evidence_claim_check_file_and_tree(self):
        claim = self._claim()
        ok, message = gate.check_text(self.claim_rel, claim, root=self.root)
        self.assertTrue(ok, message)
        (self.root / self.claim_rel).write_text(claim, encoding="utf-8")

        ok, message = gate.check_file(self.claim_rel, root=self.root)
        self.assertTrue(ok, message)
        ok, message = gate.check_tree(root=self.root)
        self.assertTrue(ok, message)
        self.assertEqual(gate.main(["--all", "--root", str(self.root)]), 0)
        self.assertEqual(
            gate.main(["--all", "--structure-only", "--root", str(self.root)]), 0
        )

        evidence = json.loads((self.root / self.evidence_rel).read_text(encoding="utf-8"))
        self.assertEqual(evidence["claim_id"], "C-1")
        self.assertEqual(evidence["problem"], "demo")
        self.assertEqual(evidence["spec"], self.spec_rel)
        self.assertEqual(evidence["evidence"], self.evidence_rel)
        self.assertEqual(evidence["checked"], 2)

    def test_valid_refutation_requires_counterexample(self):
        self.spec["_result"] = "REFUTED"
        self._write_spec()
        ok, message = gate.check_text(
            self.claim_rel, self._claim("refuted"), root=self.root
        )
        self.assertTrue(ok, message)


if __name__ == "__main__":
    unittest.main()
