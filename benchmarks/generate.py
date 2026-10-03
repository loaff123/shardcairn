"""Original-synthetic-v1 portable fixtures. Development only; no product imports."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

VERSION = "original-synthetic-v1"
SEEDS = (0, 1, 2, 3, 5, 8, 13, 21, 34, 55)
BASIS = "exclusive-additive-once-per-shard-v1"
SAFE = 9007199254740991
HERE = Path(__file__).resolve().parent


class LCG:
    def __init__(self, state: int):
        self.state = state & 0xFFFFFFFF
        self.draw_count = 0

    def draw(self) -> int:
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        self.draw_count += 1
        return self.state

    def below(self, bound: int) -> int:
        if bound <= 0:
            raise ValueError("positive bound required")
        return self.draw() % bound


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def generate_case(base_seed: int, case_index: int, family: str) -> tuple[dict, dict]:
    j = case_index
    if family == "tiny" and 0 <= j < 20:
        n, k, s, offset = 4 + j % 6, 2 + j % 3, 1 + j % 6, 0
    elif family == "medium" and 0 <= j < 10:
        n = (32, 48, 64, 96, 128, 160, 192, 224, 240, 256)[j]
        k = (2, 3, 4, 6, 8, 10, 12, 14, 16, 16)[j]
        s, offset = 4 + 2 * j, 1000003
    else:
        raise ValueError("unknown family or out-of-range case index")
    initial = (base_seed + 104729 * (j + 1) + offset) & 0xFFFFFFFF
    rng = LCG(initial)
    mode = j % 5
    setups = [] if mode == 0 else [{"id": f"s{x:04d}", "cost_ms": rng.below(200)} for x in range(s)]
    units = []
    for i in range(n):
        p = rng.below(100)
        required: set[int] = set()
        if mode == 1:
            required.add(0)
            if s > 1 and rng.below(2) == 1:
                required.add(1 + rng.below(s - 1))
        elif mode == 2:
            r = rng.below(s)
            required.update((r, (r + 1) % s))
        elif mode == 3:
            required.add(i % s)
            if i % 5 == 0:
                required.add((i + 1) % s)
        elif mode == 4:
            count = rng.below(min(4, s) + 1)
            for _ in range(count):
                required.add(rng.below(s))
        selector_count = 1 + rng.below(3)
        units.append({"id": f"u{i:04d}", "exclusive_cost_ms": p,
                      "setup_ids": [f"s{x:04d}" for x in sorted(required)],
                      "selectors": [f"tests/test_generated.py::test_u{i:04d}_m{m:04d}" for m in range(selector_count)]})
    manifest = {"schema_version": 1, "timing_basis": BASIS, "shards": k, "setups": setups, "units": units}
    ledger = {"case_id": f"{family}-seed-{base_seed}-j-{j:02d}", "protocol_version": VERSION,
              "family": family, "base_seed": base_seed, "case_index": j,
              "initial_state": initial, "final_state": rng.state, "N": n, "K": k, "S": s,
              "declared_setup_count": len(setups), "mode": mode, "draw_count": rng.draw_count,
              "held_out": mode == 4 and base_seed in (34, 55),
              "manifest_sha256": hashlib.sha256(manifest_bytes(manifest)).hexdigest()}
    return manifest, ledger


def generated_cases():
    for family, count in (("tiny", 20), ("medium", 10)):
        for seed in SEEDS:
            for j in range(count):
                yield generate_case(seed, j, family)


def fixed_cases(toy_path: Path = HERE / "toy-manifest.json") -> dict[str, dict]:
    def case(k, costs, setups=(), refs=None):
        return {"schema_version": 1, "timing_basis": BASIS, "shards": k,
                "setups": [{"id": name, "cost_ms": cost} for name, cost in setups],
                "units": [{"id": f"U{i:04d}", "exclusive_cost_ms": cost,
                           "selectors": [f"tests/test_synthetic.py::test_u{i:04d}"],
                           "setup_ids": list(refs[i]) if refs is not None else []}
                          for i, cost in enumerate(costs)]}
    toy = json.loads(toy_path.read_bytes())
    unused = deepcopy(toy)
    unused["setups"].append({"id": "never", "cost_ms": SAFE})
    common = (("x", 7), ("y", 11))
    refs = (("x",), ("x", "y"), ())
    return {
        "setup-reuse-four": toy,
        "local-pair-trap": case(2, (20, 14, 12, 10, 6, 6)),
        "equal-load-not-equivalent": case(2, (5, 0, 0), (("x", 5),), ((), ("x",), ("x",))),
        "no-improvement-equal": case(4, (10,) * 8),
        "no-improvement-common": case(3, (5,) * 6, (("x", 20),), (("x",),) * 6),
        "all-zero": case(4, (0,) * 7, (("x", 0),), tuple(("x",) if i % 2 == 0 else () for i in range(7))),
        "one-shard": case(1, (0, 5, 9), common, refs),
        "one-unit-per-shard": case(3, (0, 5, 9), common, refs),
        "unused-registry": unused,
        "integer-boundary": case(1, (SAFE - 1, 1)),
        "aggregate-overflow-negative-test": case(1, (SAFE - 1, 2)),
    }


def freeze(destination: Path) -> None:
    # Exclusive creation: an existing version is never silently regenerated.
    destination.mkdir(parents=True, exist_ok=False)
    for family in ("tiny", "medium", "fixed"):
        (destination / family).mkdir()
    shutil.copyfile(HERE / "BENCHMARK-PROTOCOL.md", destination / "BENCHMARK-PROTOCOL.md")
    shutil.copyfile(HERE / "golden-records.json", destination / "golden-records.json")
    ledger, membership = [], []
    for manifest, record in generated_cases():
        rel = f"{record['family']}/{record['case_id']}.json"
        (destination / rel).write_bytes(manifest_bytes(manifest))
        ledger.append(record)
        membership.append({**record, "path": rel, "expected_valid": True})
    for name, manifest in fixed_cases().items():
        rel = f"fixed/{name}.json"
        payload = manifest_bytes(manifest)
        (destination / rel).write_bytes(payload)
        membership.append({"case_id": name, "family": "fixed", "base_seed": None, "case_index": None,
                           "mode": None, "held_out": False, "path": rel,
                           "expected_valid": name != "aggregate-overflow-negative-test",
                           "manifest_sha256": hashlib.sha256(payload).hexdigest(),
                           "N": len(manifest["units"]), "K": manifest["shards"], "S": len(manifest["setups"])})
    (destination / "ledger.jsonl").write_bytes(b"".join((json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n").encode() for r in ledger))
    (destination / "membership.json").write_bytes(manifest_bytes({"protocol_version": VERSION, "cases": membership}))
    paths = sorted(p for p in destination.rglob("*") if p.is_file())
    index = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(destination).as_posix()}\n" for p in paths)
    (destination / "SHA256SUMS").write_text(index, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, nargs="?", default=HERE / VERSION)
    freeze(parser.parse_args().destination)
