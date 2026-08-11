#!/usr/bin/env python3
"""
Patch Telegram/AyuGram's update_checker.cpp to support plain .zip update
files, bypassing the SHA1+RSA verification that requires Telegram's
proprietary signed format (128B RSA sig + 20B SHA1 + LZMA-compressed payload).

The patch:
  1. Adds `#include <minizip/unzip.h>` (minizip is already linked via
     desktop-app::external_minizip in Telegram/CMakeLists.txt — no new deps).
  2. Inserts a zip-detection block at the start of UnpackUpdate() that:
       - peeks the first 4 bytes for the PK\x03\x04 magic
       - if matched, extracts the zip directly to tupdates/temp/
       - writes the tdata/version marker (required by checkReadyUpdate())
       - writes the tupdates/temp/ready flag file (required by checkReadyUpdate())
       - deletes the downloaded archive and returns true
       - otherwise falls through to the original Telegram-format code path
         (so official signed updates would still work if you ever ship one)

Usage:
  python patch_updater.py /path/to/AyuGramDesktop

The path should be the root of the AyuGramDesktop source tree (the dir
that contains Telegram/SourceFiles/...). The script will locate and patch
Telegram/SourceFiles/core/update_checker.cpp.

Safe to re-run: if the patch is already applied, the script reports
"already patched" and exits 0.

Intended to be invoked from the "Apply patches" step of
.github/workflows/build.yml in RezoxP/AyuGramDesktop-builder, e.g.:

      - name: Apply patches
        run: |
          python .github/scripts/patch_updater.py AyuGramDesktop
"""

import sys
import shutil
from pathlib import Path

TARGET_REL = "Telegram/SourceFiles/core/update_checker.cpp"

# Sentinel strings — if present, the file is already patched.
SENTINEL_INCLUDE = "#include <minizip/unzip.h>"
SENTINEL_MARKER = "RezoxP patch: plain-zip update support"

# The exact function signature in upstream AyuGram (verified against
# the `dev` branch as of 2026-08).
FUNC_SIG = "bool UnpackUpdate(const QString &filepath) {"

# Block to insert immediately after the opening brace of UnpackUpdate().
# Indentation is TABS to match the upstream file.
PATCH_BLOCK = '''bool UnpackUpdate(const QString &filepath) {
\t// === RezoxP patch: plain-zip update support ===
\t// If the downloaded file is a regular .zip (PK\\x03\\x04 magic), extract it
\t// directly to tupdates/temp/ using minizip, write the version marker + ready
\t// flag that checkReadyUpdate() expects, and skip the SHA1/RSA/LZMA path.
\t// Falls through to the original Telegram-format handling otherwise.
\t// (NOTE: this block lives inside the existing #ifndef TDESKTOP_DISABLE_AUTOUPDATE
\t// gate that wraps the whole function — do not add a duplicate #ifndef here.)
\t{
\t\tQFile peek(filepath);
\t\tif (peek.open(QIODevice::ReadOnly)) {
\t\t\tchar magic[4] = { 0 };
\t\t\tif (peek.peek(magic, 4) == 4
\t\t\t\t&& (uchar)magic[0] == 0x50 && (uchar)magic[1] == 0x4B
\t\t\t\t&& (uchar)magic[2] == 0x03 && (uchar)magic[3] == 0x04) {
\t\t\t\tpeek.close();

\t\t\t\tconst QString tempDirPath = cWorkingDir() + u"tupdates/temp"_q;
\t\t\t\tconst QString readyFilePath = cWorkingDir() + u"tupdates/temp/ready"_q;
\t\t\t\tbase::Platform::DeleteDirectory(tempDirPath);
\t\t\t\tQDir().mkpath(tempDirPath);

\t\t\t\t// Extract the zip into tempDirPath via minizip.
\t\t\t\tunzFile uz = unzOpen(QFile::encodeName(filepath).constData());
\t\t\t\tif (!uz) {
\t\t\t\t\tLOG(("Update Error: plain-zip: unzOpen failed for '%1'").arg(filepath));
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tif (unzGoToFirstFile(uz) != UNZ_OK) {
\t\t\t\t\tunzClose(uz);
\t\t\t\t\tLOG(("Update Error: plain-zip: unzGoToFirstFile failed"));
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tdo {
\t\t\t\t\tchar filenameBuf[4096];
\t\t\t\t\tunz_file_info info;
\t\t\t\t\tif (unzGetCurrentFileInfo(
\t\t\t\t\t\t\tuz, &info,
\t\t\t\t\t\t\tfilenameBuf, sizeof(filenameBuf),
\t\t\t\t\t\t\tnullptr, 0,
\t\t\t\t\t\t\tnullptr, 0) != UNZ_OK) {
\t\t\t\t\t\tunzClose(uz);
\t\t\t\t\t\tLOG(("Update Error: plain-zip: unzGetCurrentFileInfo failed"));
\t\t\t\t\t\treturn false;
\t\t\t\t\t}
\t\t\t\t\tQString relName = QString::fromUtf8(filenameBuf);
\t\t\t\t\t// Skip directory entries (trailing slash).
\t\t\t\t\tif (relName.endsWith('/')) {
\t\t\t\t\t\tif (unzGoToNextFile(uz) != UNZ_OK) break;
\t\t\t\t\t\tcontinue;
\t\t\t\t\t}
\t\t\t\t\tconst QString outPath = tempDirPath + '/' + relName;
\t\t\t\t\tif (!QDir().mkpath(QFileInfo(outPath).absolutePath())) {
\t\t\t\t\t\tunzClose(uz);
\t\t\t\t\t\tLOG(("Update Error: plain-zip: mkpath failed for '%1'").arg(outPath));
\t\t\t\t\t\treturn false;
\t\t\t\t\t}
\t\t\t\t\tif (unzOpenCurrentFile(uz) != UNZ_OK) {
\t\t\t\t\t\tunzClose(uz);
\t\t\t\t\t\tLOG(("Update Error: plain-zip: unzOpenCurrentFile failed for '%1'").arg(relName));
\t\t\t\t\t\treturn false;
\t\t\t\t\t}
\t\t\t\t\tQFile out(outPath);
\t\t\t\t\tif (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
\t\t\t\t\t\tunzCloseCurrentFile(uz);
\t\t\t\t\t\tunzClose(uz);
\t\t\t\t\t\tLOG(("Update Error: plain-zip: cannot open '%1' for writing").arg(outPath));
\t\t\t\t\t\treturn false;
\t\t\t\t\t}
\t\t\t\t\tchar buf[16384];
\t\t\t\t\tint r;
\t\t\t\t\twhile ((r = unzReadCurrentFile(uz, buf, sizeof(buf))) > 0) {
\t\t\t\t\t\tif (out.write(buf, r) != r) {
\t\t\t\t\t\t\tunzCloseCurrentFile(uz);
\t\t\t\t\t\t\tunzClose(uz);
\t\t\t\t\t\t\tLOG(("Update Error: plain-zip: write failed for '%1'").arg(outPath));
\t\t\t\t\t\t\treturn false;
\t\t\t\t\t\t}
\t\t\t\t\t}
\t\t\t\t\tconst int crcErr = unzCloseCurrentFile(uz);
\t\t\t\t\tout.close();
\t\t\t\t\tif (r < 0 || crcErr != UNZ_OK) {
\t\t\t\t\t\tunzClose(uz);
\t\t\t\t\t\tLOG(("Update Error: plain-zip: extract failed for '%1' (read=%2, crc=%3)").arg(relName).arg(r).arg(crcErr));
\t\t\t\t\t\treturn false;
\t\t\t\t\t}
#ifndef Q_OS_WIN
\t\t\t\t\t// external_fa high 16 bits hold the Unix st_mode; bit 0100 = S_IXUSR.
\t\t\t\t\tif ((info.external_fa >> 16) & 0100) {
\t\t\t\t\t\tQFileDevice::Permissions p = out.permissions();
\t\t\t\t\t\tp |= QFileDevice::ExeOwner | QFileDevice::ExeUser | QFileDevice::ExeGroup | QFileDevice::ExeOther;
\t\t\t\t\t\tout.setPermissions(p);
\t\t\t\t\t}
#endif // !Q_OS_WIN
\t\t\t\t\tif (unzGoToNextFile(uz) != UNZ_OK) break;
\t\t\t\t} while (true);
\t\t\t\tunzClose(uz);

\t\t\t\t// Write tdata/version — checkReadyUpdate() refuses to install
\t\t\t\t// without this marker, and the version inside must be strictly
\t\t\t\t// greater than the currently running AppVersion. The manifest
\t\t\t\t// already guaranteed this; we embed AppVersion + 1 as a safe
\t\t\t\t// sentinel that always satisfies the >check.
\t\t\t\tconst QString tdataDir = tempDirPath + u"/tdata"_q;
\t\t\t\tQDir().mkpath(tdataDir);
\t\t\t\tconst auto versionNum = VersionInt(AppVersion + 1);
\t\t\t\tconst auto versionStr = FormatVersionDisplay(AppVersion + 1).toStdWString();
\t\t\t\tconst auto versionLen = VersionInt(versionStr.size() * sizeof(VersionChar));
\t\t\t\tVersionChar versionBuf[32];
\t\t\t\tmemcpy(versionBuf, versionStr.c_str(), versionLen);
\t\t\t\tQFile fVersion(tdataDir + u"/version"_q);
\t\t\t\tif (!fVersion.open(QIODevice::WriteOnly)) {
\t\t\t\t\tLOG(("Update Error: plain-zip: cannot write version file '%1'").arg(tdataDir + u"/version"_q));
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tfVersion.write((const char*)&versionNum, sizeof(VersionInt));
\t\t\t\tfVersion.write((const char*)&versionLen, sizeof(VersionInt));
\t\t\t\tfVersion.write((const char*)&versionBuf[0], versionLen);
\t\t\t\tfVersion.close();

\t\t\t\t// Write tupdates/temp/ready — the sentinel file checkReadyUpdate()
\t\t\t\t// looks for at startup. Content is the single byte "1".
\t\t\t\tQFile readyFile(readyFilePath);
\t\t\t\tif (!readyFile.open(QIODevice::WriteOnly)
\t\t\t\t\t|| !readyFile.write("1", 1)) {
\t\t\t\t\tLOG(("Update Error: plain-zip: cannot write ready file '%1'").arg(readyFilePath));
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\treadyFile.close();

\t\t\t\t// Remove the downloaded archive (matches original behavior).
\t\t\t\tQFile::remove(filepath);

\t\t\t\tLOG(("Update Info: plain-zip update installed to tupdates/temp/"));
\t\t\t\treturn true;
\t\t\t}
\t\t\tpeek.close();
\t\t}
\t}
\t// === end RezoxP patch ===
'''


def find_target(root: Path) -> Path:
    target = root / TARGET_REL
    if not target.exists():
        # Try one level deeper in case the user passed a parent dir.
        alt = root / "AyuGramDesktop" / TARGET_REL
        if alt.exists():
            return alt
        raise FileNotFoundError(
            f"Could not find {TARGET_REL} under {root} "
            f"(also tried {alt}). Pass the AyuGramDesktop source root."
        )
    return target


def patch_file(target: Path) -> bool:
    """Apply the patch in place. Returns True if changes were made."""
    content = target.read_text(encoding="utf-8")
    original = content

    # 1. Add the minizip include if missing.
    if SENTINEL_INCLUDE not in content:
        # Insert after the first existing #include line to keep the include
        # block grouped with the other system/library includes.
        lines = content.split("\n")
        insert_at = None
        for i, line in enumerate(lines):
            if line.startswith("#include"):
                insert_at = i + 1
                break
        if insert_at is None:
            raise RuntimeError("Could not find any #include line to anchor the minizip include against.")
        lines.insert(insert_at, SENTINEL_INCLUDE)
        content = "\n".join(lines)

    # 2. Insert the zip-handling block at the start of UnpackUpdate().
    if SENTINEL_MARKER not in content:
        if FUNC_SIG not in content:
            raise RuntimeError(
                f"Could not find UnpackUpdate() signature: {FUNC_SIG!r}\n"
                "The upstream source may have changed. Inspect "
                "Telegram/SourceFiles/core/update_checker.cpp manually."
            )
        content = content.replace(FUNC_SIG, PATCH_BLOCK, 1)

    if content == original:
        return False

    # Keep a .bak next to the original for easy diffing.
    backup = target.with_suffix(target.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(target, backup)
    target.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python patch_updater.py <AyuGramDesktop-source-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    try:
        target = find_target(root)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Patching: {target}")
    try:
        changed = patch_file(target)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if changed:
        print(f"PATCHED: {target}  (backup at {target}.bak)")
    else:
        print(f"ALREADY PATCHED (or no changes needed): {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
