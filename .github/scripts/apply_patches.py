#!/usr/bin/env python3
"""
Unified patch applicator for AyuGramDesktop builds on Windows and Linux.

Applies:
1. patch_updater.py: Plain-zip updater support in update_checker.cpp
2. Autoupdate manifest URL redirection in localstorage.cpp and update_checker.cpp
3. Legacy ayugram.one prefix override prevention in localstorage.cpp
4. (Linux) tlottie / tdesktop_rust library resolution in cmake/external/tlottie/CMakeLists.txt
5. (Windows) MSVC build options and C++20 requirement in cmake/options_win.cmake & variables.cmake
6. (Windows) prepare.py MSYS2 UCRT64 migration & installer update
"""

import os
import sys
import re
import argparse
from pathlib import Path

# Import the zip updater patcher
scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(scripts_dir))
import patch_updater


def apply_patch(root: Path, rel_path: str, old: str, new: str, desc: str = "") -> bool:
    full_path = root / rel_path
    if not full_path.exists():
        print(f"  [SKIP] {rel_path} does not exist")
        return False

    raw = full_path.read_bytes()
    is_crlf = b"\r\n" in raw
    content = raw.decode("utf-8")

    if new in content:
        print(f"  [ALREADY APPLIED] {rel_path}: {desc or old[:50]}...")
        return False

    if old not in content:
        print(f"  [NOT FOUND] {rel_path}: {desc or old[:50]}...")
        return False

    content = content.replace(old, new)
    newline = "\r\n" if is_crlf else "\n"
    full_path.write_text(content, encoding="utf-8", newline=newline)
    print(f"  [APPLIED] {rel_path}: {desc or old[:50]}...")
    return True


def apply_patch_re(root: Path, rel_path: str, pattern: str, new: str, desc: str = "") -> bool:
    full_path = root / rel_path
    if not full_path.exists():
        print(f"  [SKIP] {rel_path} does not exist")
        return False

    raw = full_path.read_bytes()
    is_crlf = b"\r\n" in raw
    content = raw.decode("utf-8")

    if new in content:
        print(f"  [ALREADY APPLIED] {rel_path}: {desc or pattern[:50]}...")
        return False

    match = re.search(pattern, content)
    if not match:
        print(f"  [NOT FOUND] {rel_path}: {desc or pattern[:50]}...")
        return False

    content = content[:match.start()] + new + content[match.end():]
    newline = "\r\n" if is_crlf else "\n"
    full_path.write_text(content, encoding="utf-8", newline=newline)
    print(f"  [APPLIED] {rel_path}: {desc or pattern[:50]}...")
    return True


def main():
    parser = argparse.ArgumentParser(description="Apply build patches to AyuGramDesktop source tree")
    parser.add_argument("source_dir", help="Path to AyuGramDesktop root directory")
    parser.add_argument("--platform", choices=["windows", "linux"], required=True, help="Target build platform")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "RezoxP/AyuGramDesktop-builder"),
                        help="GitHub repository (Owner/Repo) for update manifest URL")

    args = parser.parse_args()
    root = Path(args.source_dir).resolve()
    repo = args.repo.strip()
    manifest_url = f"https://raw.githubusercontent.com/{repo}/update-manifest/"

    print(f"=== Applying AyuGramDesktop patches for {args.platform.upper()} ===")
    print(f"Source Root: {root}")
    print(f"Repository:  {repo}")
    print(f"Update URL:  {manifest_url}")

    # 1. Plain zip updater support in update_checker.cpp
    print("\n[1/3] Patching update_checker.cpp for plain-zip update extraction...")
    try:
        target = patch_updater.find_target(root)
        changed = patch_updater.patch_file(target)
        if changed:
            print(f"  [APPLIED] {patch_updater.TARGET_REL} (zip extraction)")
        else:
            print(f"  [ALREADY APPLIED] {patch_updater.TARGET_REL} (zip extraction)")
    except Exception as e:
        print(f"  [ERROR] Failed to patch update_checker for zip updates: {e}", file=sys.stderr)
        return 1

    # 2. Storage & updater network patches (common to both platforms)
    print("\n[2/3] Patching update manifest URLs and prefix handling...")
    apply_patch(
        root,
        "Telegram/SourceFiles/storage/localstorage.cpp",
        'return AutoupdatePrefix("https://update.ayugram.one/");',
        f'return AutoupdatePrefix("{manifest_url}");',
        "AutoupdatePrefix default URL"
    )
    apply_patch(
        root,
        "Telegram/SourceFiles/storage/localstorage.cpp",
        'const auto fixedPrefix = QString::fromStdString("https://update.ayugram.one/");',
        f'const auto fixedPrefix = QString::fromStdString("{manifest_url}");',
        "writeAutoupdatePrefix fixed URL"
    )
    apply_patch(
        root,
        "Telegram/SourceFiles/storage/localstorage.cpp",
        "if (!value.isEmpty()) {",
        'if (!value.isEmpty() && !value.contains("ayugram.one")) {',
        "Ignore obsolete official ayugram.one in tdata/prefix"
    )
    apply_patch(
        root,
        "Telegram/SourceFiles/core/update_checker.cpp",
        "Local::readAutoupdatePrefix() + bestLink)",
        'bestLink.startsWith(QLatin1String("http")) ? bestLink : (Local::readAutoupdatePrefix() + bestLink))',
        "Allow absolute HTTP/HTTPS download link from manifest"
    )

    # 3. Platform-specific patches
    print(f"\n[3/3] Applying {args.platform.upper()}-specific patches...")

    if args.platform == "windows":
        # Windows CMake options
        apply_patch(
            root,
            "cmake/options_win.cmake",
            "init_target(Telegram)",
            "init_target(Telegram disable_debug_scheme)",
            "Disable debug scheme in options_win.cmake"
        )
        apply_patch(
            root,
            "cmake/options_win.cmake",
            "enable_warnings(Telegram)",
            "",
            "Disable enable_warnings in options_win.cmake"
        )
        apply_patch_re(
            root,
            "cmake/variables.cmake",
            r"set\(CMAKE_CXX_STANDARD_REQUIRED ON\)",
            "set(CMAKE_CXX_STANDARD_REQUIRED ON)\nset(CMAKE_CXX_STANDARD 20)",
            "Enforce C++20 standard in variables.cmake"
        )

        # Windows prepare.py fixes
        apply_patch(
            root,
            "Telegram/build/prepare/prepare.py",
            "if build_debug:",
            "if False:",
            "Skip debug build in prepare.py"
        )
        apply_patch(
            root,
            "Telegram/build/prepare/prepare.py",
            "'ThirdParty\\\\msys64\\\\mingw64\\\\bin'",
            "'ThirdParty\\\\msys64\\\\ucrt64\\\\bin'",
            "Update MSYS2 path prefix to ucrt64"
        )
        apply_patch(
            root,
            "Telegram/build/prepare/prepare.py",
            "https://github.com/msys2/msys2-installer/releases/download/2025-08-30/msys2-base-x86_64-20250830.sfx.exe",
            "https://github.com/msys2/msys2-installer/releases/download/2026-09-27/msys2-base-x86_64-20260927.sfx.exe",
            "Update MSYS2 installer URL to 2026-09-27 release"
        )

        # MSYS2 pacman package names migrated from mingw64 to ucrt64
        for pkg in ["diffutils", "gperf", "nasm", "perl", "pkgconf"]:
            apply_patch(
                root,
                "Telegram/build/prepare/prepare.py",
                f"mingw-w64-x86_64-{pkg}",
                f"mingw-w64-ucrt-x86_64-{pkg}",
                f"Migrate MSYS2 {pkg} package to mingw-w64-ucrt-x86_64-{pkg}"
            )

    elif args.platform == "linux":
        # Linux tlottie / tdesktop_rust resolution
        # Upstream tdesktop centos_env Docker image consolidated tlottie & wallet-engine
        # into /usr/local/lib/libtdesktop_rust.a. Ensure CMake searches for both names.
        apply_patch(
            root,
            "cmake/external/tlottie/CMakeLists.txt",
            "find_library(DESKTOP_APP_TLOTTIE_LIBRARY tlottie REQUIRED)",
            "find_library(DESKTOP_APP_TLOTTIE_LIBRARY NAMES tlottie tdesktop_rust REQUIRED)",
            "Support libtdesktop_rust.a in tlottie CMakeLists.txt"
        )

    print("\n=== All patches applied successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
