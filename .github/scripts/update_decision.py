#!/usr/bin/env python3
"""
update_decision.py — Decision engine for the AyuGramDesktop-builder auto-updater.

Given the current upstream version, the latest released version in this
repository, the in-app update manifest (current4), and workflow-run state,
decide whether a build should be dispatched and for which platforms:

  * full  — a brand new upstream version was published: build everything.
  * retry — the latest version is released but some manifest platforms are
            stale (failed platform, interrupted manifest push): rebuild only
            the stale platforms, after a quiet period so a persistently
            failing platform cannot burn CI minutes in a tight loop.
  * none  — everything is up to date, or a build is already running/queued.

The logic lives in this standalone script so it can be unit-tested locally
(via --selftest) instead of hiding inside YAML.

Usage:
    python3 update_decision.py --input state.json [--quiet-period-minutes 240]
        Reads the state JSON from a file and prints the decision JSON.
    python3 update_decision.py --selftest
        Runs the built-in self tests.
"""

import argparse
import json
import re
import sys

# Manifest platform key -> build.yml dispatch input flag
PLATFORM_FLAG = {
    "win64": "build_windows_x64",
    "win": "build_windows_x86",
    "mac": "build_macos",
    "armac": "build_macos",
    "linux": "build_linux_x64",
}

DEFAULT_QUIET_MINUTES = 240


def version_to_num(version: str) -> int:
    """'7.2.9' -> 7002009, matching Telegram's AppVersion numbering."""
    if not version:
        return 0
    clean = re.sub(r"[^0-9.]", "", version.strip().split()[0])
    parts = [int(p) for p in clean.split(".") if p.isdigit()]
    while len(parts) < 3:
        parts.append(0)
    return parts[0] * 1_000_000 + parts[1] * 1_000 + parts[2]


def parse_manifest_version(value) -> int:
    """Read a manifest 'released' value ('7002009' or 7002009) -> int."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        head = value.split(":", 1)[0].strip()
        return int(head) if head.isdigit() else 0
    return 0


def decide(
    upstream_version: str,
    latest_release_version: str,
    manifest,
    busy_count: int,
    minutes_since_last_build,
    quiet_period_minutes: int = DEFAULT_QUIET_MINUTES,
) -> dict:
    """Pure decision function — no I/O, fully unit-testable."""
    all_flags = {
        "build_windows_x64": True,
        "build_windows_x86": True,
        "build_linux_x64": True,
        "build_macos": True,
    }

    upstream_num = version_to_num(upstream_version)
    release_num = version_to_num(latest_release_version) if latest_release_version else 0

    if busy_count and busy_count > 0:
        return {
            "action": "none",
            "platforms": {},
            "reason": f"a build is already running or queued ({busy_count} active)",
        }

    # Brand new upstream version or fresh repository with no release
    if not latest_release_version or upstream_num > release_num:
        return {
            "action": "full",
            "platforms": dict(all_flags),
            "reason": (
                f"new upstream version {upstream_version} "
                f"(released: {latest_release_version or 'none'})"
            ),
        }

    # Release is strictly ahead of upstream (e.g. manual custom release)
    if release_num > upstream_num:
        return {
            "action": "none",
            "platforms": {},
            "reason": (
                f"latest release {latest_release_version} is ahead of upstream {upstream_version}"
            ),
        }

    # Latest release matches upstream — check every platform we support.
    # An unreachable/empty manifest (None) means users cannot update at all: rebuild everything.
    if manifest is None:
        stale_keys = sorted(PLATFORM_FLAG.keys())
    else:
        platforms = manifest if isinstance(manifest, dict) else {}
        stale_keys = []
        for key in sorted(PLATFORM_FLAG.keys()):
            entry = platforms.get(key)
            released = 0
            if isinstance(entry, dict):
                stable = entry.get("stable")
                if isinstance(stable, dict):
                    released = parse_manifest_version(stable.get("released"))
                else:
                    released = parse_manifest_version(entry.get("released"))
            if released < upstream_num:
                stale_keys.append(key)

    if not stale_keys:
        return {
            "action": "none",
            "platforms": {},
            "reason": f"all manifest platforms are up to date at {upstream_version}",
        }

    if (
        minutes_since_last_build is not None
        and minutes_since_last_build < quiet_period_minutes
    ):
        return {
            "action": "none",
            "platforms": {},
            "reason": (
                f"stale platforms ({', '.join(stale_keys)}) but the last build "
                f"finished {int(minutes_since_last_build)} min ago "
                f"(< {quiet_period_minutes} min quiet period)"
            ),
        }

    retry_flags = {flag: False for flag in all_flags}
    for key in stale_keys:
        retry_flags[PLATFORM_FLAG[key]] = True

    return {
        "action": "retry",
        "platforms": retry_flags,
        "reason": (
            f"rebuilding stale platforms for {upstream_version}: "
            f"{', '.join(sorted(set(PLATFORM_FLAG[k] for k in stale_keys)))}"
        ),
    }


def _selftest() -> int:
    cases = [
        # (name, args, expected_action, expected_reason_substring)
        ("new version -> full build",
         dict(upstream_version="7.2.10", latest_release_version="7.2.9",
              manifest={"win64": {"stable": {"released": "7002009", "link": "x"}}},
              busy_count=0, minutes_since_last_build=5),
         "full", "new upstream version"),
        ("no release at all -> full build",
         dict(upstream_version="7.2.9", latest_release_version="",
              manifest=None, busy_count=0, minutes_since_last_build=None),
         "full", "none"),
        ("busy -> wait",
         dict(upstream_version="7.2.10", latest_release_version="7.2.9",
              manifest=None, busy_count=2, minutes_since_last_build=1),
         "none", "already running"),
        ("up to date -> none",
         dict(upstream_version="7.2.9", latest_release_version="7.2.9",
              manifest={"win64": {"stable": {"released": "7002009"}},
                        "win": {"stable": {"released": "7002009"}},
                        "mac": {"stable": {"released": "7002009"}},
                        "armac": {"stable": {"released": "7002009"}},
                        "linux": {"stable": {"released": "7002009"}}},
              busy_count=0, minutes_since_last_build=10),
         "none", "up to date"),
        ("mac stale, quiet period not over -> wait",
         dict(upstream_version="7.2.9", latest_release_version="7.2.9",
              manifest={"win64": {"stable": {"released": "7002009"}},
                        "win": {"stable": {"released": "7002009"}},
                        "mac": {"stable": {"released": "7000009"}},
                        "armac": {"stable": {"released": "7000009"}},
                        "linux": {"stable": {"released": "7002009"}}},
              busy_count=0, minutes_since_last_build=30),
         "none", "quiet period"),
        ("mac stale, quiet period over -> retry mac only",
         dict(upstream_version="7.2.9", latest_release_version="7.2.9",
              manifest={"win64": {"stable": {"released": "7002009"}},
                        "win": {"stable": {"released": "7002009"}},
                        "mac": {"stable": {"released": "7000009"}},
                        "armac": {"stable": {"released": "7000009"}},
                        "linux": {"stable": {"released": "7002009"}}},
              busy_count=0, minutes_since_last_build=300),
         "retry", "build_macos"),
        ("multiple stale platforms -> retry both",
         dict(upstream_version="7.2.9", latest_release_version="7.2.9",
              manifest={"win64": {"stable": {"released": "7002009"}},
                        "win": {"stable": {"released": "7000009"}},
                        "mac": {"stable": {"released": "7002009"}},
                        "armac": {"stable": {"released": "7002009"}},
                        "linux": {"stable": {"released": "7000009"}}},
              busy_count=0, minutes_since_last_build=9999),
         "retry", "build_linux_x64"),
        ("manifest unreachable -> retry everything",
         dict(upstream_version="7.2.9", latest_release_version="7.2.9",
              manifest=None, busy_count=0, minutes_since_last_build=9999),
         "retry", "build_windows_x64"),
        ("manifest numeric released values",
         dict(upstream_version="7.2.9", latest_release_version="7.2.9",
              manifest={"win64": {"stable": {"released": 7002009}},
                        "win": {"stable": {"released": 7002009}},
                        "mac": {"stable": {"released": 7002009}},
                        "armac": {"stable": {"released": 7002009}},
                        "linux": {"stable": {"released": 7002009}}},
              busy_count=0, minutes_since_last_build=9999),
         "none", "up to date"),
        ("released ahead of upstream ignored",
         dict(upstream_version="7.2.9", latest_release_version="7.3.0",
              manifest={"win64": {"stable": {"released": "7003000"}}},
              busy_count=0, minutes_since_last_build=9999),
         "none", "ahead of upstream"),
        ("version with extra channel word",
         dict(upstream_version="7.3.0 beta", latest_release_version="7.2.9",
              manifest={}, busy_count=0, minutes_since_last_build=1),
         "full", "new upstream version"),
    ]

    failures = 0
    for name, args, want_action, want_reason in cases:
        got = decide(**args)
        ok = got["action"] == want_action and want_reason in got["reason"]
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"  [{status}] {name}: action={got['action']} reason={got['reason']}")
        if not ok:
            print(f"         expected action={want_action}, reason~{want_reason!r}")
    print()
    print(f"{len(cases) - failures}/{len(cases)} self tests passed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-update dispatch decision engine")
    parser.add_argument("--input", help="Path to a JSON state file (or '-' for stdin)")
    parser.add_argument("--quiet-period-minutes", type=int, default=DEFAULT_QUIET_MINUTES)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    if not args.input:
        parser.error("--input is required (or use --selftest)")

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    state = json.loads(raw)
    decision = decide(
        upstream_version=state.get("upstream_version", ""),
        latest_release_version=state.get("latest_release_version", ""),
        manifest=state.get("manifest"),
        busy_count=int(state.get("busy_count", 0) or 0),
        minutes_since_last_build=state.get("minutes_since_last_build"),
        quiet_period_minutes=args.quiet_period_minutes,
    )
    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
