"""manifest.json must match Seed B's frozen benchmark manifest exactly, and every
committed diff.patch must hash to the patch_sha256 it records (ADR-004 SS6, seed-b's
eval/README.md "Integrity validation")."""

import hashlib
import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).parents[2] / "eval" / "golden"

EXPECTED_BASE_SHA = "fbd4e09643ea61027165fdbfafbb2c3e5edd0153"

EXPECTED_BRANCHES = {
    "feature/analytics-archive": (
        "d5ecfb126399ae9b214500ab71e75e5707a2264d",
        "d406de699c4fc42c3a1cad2a02f49a2e811b8835c13ca33bbffbfb2c37d32207",
    ),
    "feature/email-reminders": (
        "e1732cb7b95d42ad36f1a5b00583fb61bea8c119",
        "4fa76a4edb931b92e5c9eb21a28db8d1d1228db1037013b9f2214ff08a8bfa3a",
    ),
    "feature/lessons-pagination": (
        "386b2e1d2882820c82977cbfd7361d3aea6b6865",
        "0682eebedbc2d3b840b4ce5846c1dc1bbf8e7c31cd0b44be6192b3e12a41909e",
    ),
    "feature/score-validation": (
        "60a6090693bc327d90838943f13890ca803f37a0",
        "edef156d10b2bda7628f4cf54bea09fea4f317978b2d5b3a3122ff48c172a8cb",
    ),
    "feature/streaks": (
        "b5133c29895d6a98ceb2e595b10c4e89093ac71f",
        "5c40733a254dec924ae0545d03f5c6aa7b9642d2968d4da80374edfe4dd4cac9",
    ),
    "feature/support-context": (
        "dfabcaeb1fedc65330928a29271b00efb40c5bce",
        "72380ff6bfde72feaf1cbb307d8d594abe7ef804d75df8625d51ecd92d5be85b",
    ),
    "fix/mobile-sync-visibility": (
        "fa726eb00be931ad67a4b11f1282f1838563975f",
        "4a25d0d6af8cf37eb8ca08def2ac6dca15cb995b49d62e3fa975b867a0ec095f",
    ),
    "fix/progress-percentage": (
        "a620c3832d9a587624814a2f9c0dd9a566345c92",
        "6eae85ee1c133808f8cce0cbbfcee9b2d51dbd3581a26b484da57702d04552e1",
    ),
}


def test_manifest_matches_the_frozen_seed_b_benchmark() -> None:
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["dataset_version"] == "1.0.0"
    assert manifest["base_sha"] == EXPECTED_BASE_SHA
    assert set(manifest["branches"]) == set(EXPECTED_BRANCHES)
    for branch, (head_sha, patch_sha256) in EXPECTED_BRANCHES.items():
        entry = manifest["branches"][branch]
        assert entry["head_sha"] == head_sha
        assert entry["merge_base_sha"] == EXPECTED_BASE_SHA
        assert entry["patch_sha256"] == patch_sha256


def test_every_diff_patch_hashes_to_its_manifest_patch_sha256() -> None:
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    for branch, entry in manifest["branches"].items():
        diff_path = GOLDEN_DIR / branch / "diff.patch"
        digest = hashlib.sha256(diff_path.read_bytes()).hexdigest()
        assert digest == entry["patch_sha256"], f"{branch}: diff.patch does not match manifest"
