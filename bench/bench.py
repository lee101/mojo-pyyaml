"""End-to-end parse and emit benchmarks against PyYAML."""

from __future__ import annotations

import cProfile
import math
import os
import platform
import pstats
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

import mojopyyaml  # noqa: E402
import yaml  # noqa: E402


def best_time(function, repeat: int = 3) -> float:
    best = math.inf
    for _ in range(repeat):
        start = time.perf_counter()
        function()
        best = min(best, time.perf_counter() - start)
    return best


def machine() -> str:
    cpu = platform.processor()
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return f"{cpu or platform.machine()}, {platform.system()} {platform.release()}"


def main() -> None:
    flat_yaml = "".join(f"key_{i}: {i}\n" for i in range(25_000))
    records_yaml = "items:\n" + "".join(
        f"  - id: {i}\n    name: item-{i}\n    enabled: true\n"
        for i in range(5_000)
    )
    mapping = {f"key_{i}": i for i in range(25_000)}
    large_text = ("The quick brown fox jumps over the lazy dog. " * 45_000) + "\n"
    flow_yaml = "[" + ", ".join(str(i) for i in range(25_000)) + "]\n"
    quoted_values = [f"value: {i}" for i in range(25_000)]
    quoted_yaml = yaml.safe_dump(large_text)

    cases = [
        (
            "load flat mapping (25k pairs)",
            lambda: mojopyyaml.safe_load(flat_yaml),
            lambda: yaml.safe_load(flat_yaml),
        ),
        (
            "load records (5k mappings)",
            lambda: mojopyyaml.safe_load(records_yaml),
            lambda: yaml.safe_load(records_yaml),
        ),
        (
            "dump flat mapping (25k pairs)",
            lambda: mojopyyaml.safe_dump(mapping),
            lambda: yaml.safe_dump(mapping),
        ),
        (
            "dump quoted scalar (2.0 MB)",
            lambda: mojopyyaml.safe_dump(large_text),
            lambda: yaml.safe_dump(large_text),
        ),
        (
            "load flow sequence (25k scalars)",
            lambda: mojopyyaml.safe_load(flow_yaml),
            lambda: yaml.safe_load(flow_yaml),
        ),
        (
            "load quoted scalar (2.0 MB)",
            lambda: mojopyyaml.safe_load(quoted_yaml),
            lambda: yaml.safe_load(quoted_yaml),
        ),
        (
            "dump quoted sequence (25k scalars)",
            lambda: mojopyyaml.safe_dump(quoted_values),
            lambda: yaml.safe_dump(quoted_values),
        ),
    ]

    print(f"Machine: {machine()}")
    print()
    print("| case | mojo-pyyaml | PyYAML | speedup |")
    print("| --- | ---: | ---: | ---: |")
    for name, ours, upstream in cases:
        ours_result = ours()
        upstream_result = upstream()
        if name.startswith("load"):
            assert ours_result == upstream_result
        else:
            assert yaml.safe_load(ours_result) == mojopyyaml.safe_load(upstream_result)
        mojo_seconds = best_time(ours)
        upstream_seconds = best_time(upstream)
        ratio = upstream_seconds / mojo_seconds
        print(
            f"| {name} | {mojo_seconds * 1e3:.1f} ms | "
            f"{upstream_seconds * 1e3:.1f} ms | {ratio:.2f}x |"
        )

    if os.environ.get("MOJO_PYYAML_PROFILE"):
        profiles = [
            ("load flat mapping", lambda: mojopyyaml.safe_load(flat_yaml)),
            ("load records", lambda: mojopyyaml.safe_load(records_yaml)),
            ("load quoted scalar", lambda: mojopyyaml.safe_load(quoted_yaml)),
        ]
        for name, function in profiles:
            profiler = cProfile.Profile()
            profiler.enable()
            function()
            profiler.disable()
            print(f"\nProfile: {name}")
            pstats.Stats(profiler).sort_stats("tottime").print_stats(20)


if __name__ == "__main__":
    main()
