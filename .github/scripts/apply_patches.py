#!/usr/bin/env python3
"""
apply_patches.py — Consolidated, future-proof source patcher for AyuGramDesktop CI.

Applies:
1. update-url        (critical): Rewrites AyuGram auto-update manifest URL to this repository.
2. prefix-override   (critical): Locks local storage autoupdate prefix to builder manifest URL
                                 so stale on-disk tdata/prefix files cannot hijack updates.
3. manifest-url      (critical): Allows absolute HTTP/HTTPS links in update manifest without
                                 prepending readAutoupdatePrefix() (fixes broken double-URL).
4. zip-updates       (critical): Enables plain .zip update extraction via minizip, Unix symlink
                                 restoration (for macOS .app Frameworks), anti-bloat stale file
                                 purge, zip-slip protection, semantic version parsing from the
                                 archive filename, version/ready markers, and Unix permissions.
5. updater-network   (critical): Ignores intermediate 3xx HTTP redirect responses in
                                 HttpLoaderActor (fixes GitHub Releases 302 redirect abort),
                                 preserves '.' in ExtractFilename(), matches 'AyuGram-*' in
                                 FindUpdateFile(), and makes Windows temp Updater.exe cleanup
                                 resilient to transient antivirus file locks.
6. platform-updaters (critical): Calls checkReadyUpdate() in Core::Restart(), skips overwriting
                                 a running Updater binary in updater_win.cpp / updater_linux.cpp
                                 instead of deleting the update, fixes hardcoded 'Telegram'
                                 binary name in updater_linux.cpp -> 'AyuGram', and makes
                                 fchown() in specific_linux.cpp (linuxMoveFile) non-fatal.
7. mirrors           (critical): Mirrors dav1d and breakpad to reliable GitHub repos.
8. mac-updater       (macOS):    Dynamically resolves AyuGram.app bundle in checkReadyUpdate
                                 and guards Xcode 26 folder.iconcomposer.icon behind Xcode >= 26.
9. tg-owt-win        (Windows):  Fixes upstream Windows cmd line continuation bug (\\ -> ^).
10. msys2-ucrt64     (Windows):  Migrates MSYS2 to UCRT64 toolchain, resolves installer dynamically
                                 with pinned fallback, bypasses expired GPG keys, and pins
                                 NASM 2.16.03 (fixes NASM 3.02 crash in libvpx).
11. qt-release-only  (Win/Mac):  Builds Qt in release-only mode on Windows & macOS.
12. tlottie-rust     (Win/Lin):  Ensures standard MSVC Rust targets in prepare.py & tlottie.
13. cmake-options    (Windows):  Adds /FS and gates /Zi & /DEBUG to prevent MSVC PDB RPC errors.
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

TARGET_UPDATER = "Telegram/SourceFiles/core/update_checker.cpp"
TARGET_LOCALSTORAGE = "Telegram/SourceFiles/storage/localstorage.cpp"
TARGET_APPLICATION = "Telegram/SourceFiles/core/application.cpp"
TARGET_UPDATER_WIN = "Telegram/SourceFiles/_other/updater_win.cpp"
TARGET_UPDATER_LINUX = "Telegram/SourceFiles/_other/updater_linux.cpp"
TARGET_UPDATER_OSX = "Telegram/SourceFiles/_other/updater_osx.m"
TARGET_SPECIFIC_LINUX = "Telegram/SourceFiles/platform/linux/specific_linux.cpp"
TARGET_DEDICATED_LOADER_H = "Telegram/SourceFiles/mtproto/dedicated_file_loader.h"
TARGET_PREPARE = "Telegram/build/prepare/prepare.py"
TARGET_TELEGRAM_CMAKE = "Telegram/CMakeLists.txt"
TARGET_TLOTTIE = "cmake/external/tlottie/CMakeLists.txt"
TARGET_OPTIONS_WIN = "cmake/options_win.cmake"
TARGET_VARIABLES = "cmake/variables.cmake"

SENTINEL_INCLUDE = '#include "base/zlib_help.h"'
UNIX_SYMLINK_INCLUDES = """\
#ifndef Q_OS_WIN
#include <unistd.h>
#include <sys/stat.h>
#endif // !Q_OS_WIN"""
SENTINEL_MARKER = "RezoxP patch: plain-zip update support"

UNPACK_ANCHOR_RE = re.compile(
    r"(bool\s+UnpackUpdate\s*\(\s*const\s+QString\s*&\s*filepath\s*\)\s*\{"
    r"[\s\S]*?"
    r"if\s*\(\s*filepath\.isEmpty\s*\(\s*\)\s*\)\s*\{\s*return\s+true\s*;\s*\})"
)

ZIP_PATCH_BLOCK = '''\t// === RezoxP patch: plain-zip update support ===
\t// If the downloaded file is a regular .zip (PK\\x03\\x04 magic), extract it
\t// directly to tupdates/temp/ using minizip, write the version marker + ready
\t// flag that checkReadyUpdate() expects, and skip the SHA1/RSA/LZMA path.
\t// Falls through to the original Telegram-format handling otherwise.
\t{
\t\tQFile peek(filepath);
\t\tif (peek.open(QIODevice::ReadOnly)) {
\t\t\tchar magic[4] = { 0 };
\t\t\tif (peek.peek(magic, 4) == 4
\t\t\t\t&& (uchar)magic[0] == 0x50 && (uchar)magic[1] == 0x4B
\t\t\t\t&& (uchar)magic[2] == 0x03 && (uchar)magic[3] == 0x04) {
\t\t\t\tpeek.close();

\t\t\t\t// Anti-bloat: purge any stale files or partial archives in tupdates/
\t\t\t\tconst QString updatesDirPath = cWorkingDir() + u"tupdates"_q;
\t\t\t\tconst QString tempDirPath = cWorkingDir() + u"tupdates/temp"_q;
\t\t\t\tconst QString readyFilePath = cWorkingDir() + u"tupdates/temp/ready"_q;
\t\t\t\tQDir updatesDir(updatesDirPath);
\t\t\t\tif (updatesDir.exists()) {
\t\t\t\t\tfor (const auto &info : updatesDir.entryInfoList(QDir::Files)) {
\t\t\t\t\t\tif (info.absoluteFilePath() != QFileInfo(filepath).absoluteFilePath()) {
\t\t\t\t\t\t\tQFile::remove(info.absoluteFilePath());
\t\t\t\t\t\t}
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\tQFile::remove(readyFilePath);
\t\t\t\tQDir(tempDirPath).removeRecursively();
\t\t\t\tif (QFile::exists(readyFilePath)) {
\t\t\t\t\tLOG(("Update Error: plain-zip: failed to clear tupdates/temp"));
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tQDir().mkpath(tempDirPath);
\t\t\t\tconst auto cleanTempRoot = QDir::cleanPath(tempDirPath);

\t\t\t\tauto cleanupOnFailure = [&]() {
\t\t\t\t\tQFile::remove(filepath);
\t\t\t\t\tQDir(tempDirPath).removeRecursively();
\t\t\t\t};

\t\t\t\t// Extract the zip into tempDirPath via minizip.
\t\t\t\tunzFile uz = unzOpen64(QFile::encodeName(filepath).constData());
\t\t\t\tif (!uz) {
\t\t\t\t\tuz = unzOpen64(filepath.toUtf8().constData());
\t\t\t\t}
\t\t\t\tif (!uz) {
\t\t\t\t\tLOG(("Update Error: plain-zip: unzOpen64 failed for '%1'").arg(filepath));
\t\t\t\t\tcleanupOnFailure();
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tif (unzGoToFirstFile(uz) != UNZ_OK) {
\t\t\t\t\tunzClose(uz);
\t\t\t\t\tLOG(("Update Error: plain-zip: unzGoToFirstFile failed"));
\t\t\t\t\tcleanupOnFailure();
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tbool extractSuccess = true;
\t\t\t\tdo {
\t\t\t\t\tchar filenameBuf[4096] = {};
\t\t\t\t\tunz_file_info64 info = {};
\t\t\t\t\tif (unzGetCurrentFileInfo64(
\t\t\t\t\t\t\tuz, &info,
\t\t\t\t\t\t\tfilenameBuf, sizeof(filenameBuf) - 1,
\t\t\t\t\t\t\tnullptr, 0,
\t\t\t\t\t\t\tnullptr, 0) != UNZ_OK) {
\t\t\t\t\t\tLOG(("Update Error: plain-zip: unzGetCurrentFileInfo64 failed"));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\tQString relName = QString::fromUtf8(filenameBuf);
\t\t\t\t\tif (relName.isEmpty()) {
\t\t\t\t\t\tif (unzGoToNextFile(uz) != UNZ_OK) break;
\t\t\t\t\t\tcontinue;
\t\t\t\t\t}
\t\t\t\t\t// 1. Guard against path traversal (Zip Slip)
\t\t\t\t\tconst QString outPath = QDir::cleanPath(tempDirPath + '/' + relName);
\t\t\t\t\tif (!outPath.startsWith(cleanTempRoot + '/')) {
\t\t\t\t\t\tLOG(("Update Error: plain-zip: insecure path in archive: '%1'").arg(relName));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\t// 2. Skip directory entries, OS metadata, and Mac archive junk
\t\t\t\t\tif (relName.endsWith('/') || relName.startsWith(u"__MACOSX/"_q) || relName.endsWith(u".DS_Store"_q)) {
\t\t\t\t\t\tif (relName.endsWith('/')) {
\t\t\t\t\t\t\tQDir().mkpath(outPath);
\t\t\t\t\t\t}
\t\t\t\t\t\tif (unzGoToNextFile(uz) != UNZ_OK) break;
\t\t\t\t\t\tcontinue;
\t\t\t\t\t}
\t\t\t\t\tif (!QDir().mkpath(QFileInfo(outPath).absolutePath())) {
\t\t\t\t\t\tLOG(("Update Error: plain-zip: mkpath failed for '%1'").arg(outPath));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\tif (unzOpenCurrentFile(uz) != UNZ_OK) {
\t\t\t\t\t\tLOG(("Update Error: plain-zip: unzOpenCurrentFile failed for '%1'").arg(relName));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
#ifndef Q_OS_WIN
\t\t\t\t\t// Handle Unix symbolic links (S_IFLNK = 0120000) stored by `zip -y` on macOS/Linux
\t\t\t\t\tconst auto unixMode = (info.external_fa >> 16) & 0xFFFF;
\t\t\t\t\tif ((unixMode & 0170000) == 0120000) {
\t\t\t\t\t\tQByteArray linkTarget;
\t\t\t\t\t\tchar linkBuf[4096];
\t\t\t\t\t\tint lr = 0;
\t\t\t\t\t\twhile ((lr = unzReadCurrentFile(uz, linkBuf, sizeof(linkBuf))) > 0) {
\t\t\t\t\t\t\tlinkTarget.append(linkBuf, lr);
\t\t\t\t\t\t}
\t\t\t\t\t\tunzCloseCurrentFile(uz);
\t\t\t\t\t\tif (lr < 0 || linkTarget.isEmpty()) {
\t\t\t\t\t\t\tLOG(("Update Error: plain-zip: failed reading symlink '%1'").arg(relName));
\t\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\t\tQFile::remove(outPath);
\t\t\t\t\t\tif (::symlink(linkTarget.constData(), QFile::encodeName(outPath).constData()) != 0) {
\t\t\t\t\t\t\tLOG(("Update Error: plain-zip: symlink failed for '%1'").arg(relName));
\t\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\t\tif (unzGoToNextFile(uz) != UNZ_OK) break;
\t\t\t\t\t\tcontinue;
\t\t\t\t\t}
#endif // !Q_OS_WIN
\t\t\t\t\tQFile out(outPath);
\t\t\t\t\tif (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
\t\t\t\t\t\tunzCloseCurrentFile(uz);
\t\t\t\t\t\tLOG(("Update Error: plain-zip: cannot open '%1' for writing").arg(outPath));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\tchar buf[65536];
\t\t\t\t\tint r;
\t\t\t\t\tbool writeOk = true;
\t\t\t\t\twhile ((r = unzReadCurrentFile(uz, buf, sizeof(buf))) > 0) {
\t\t\t\t\t\tif (out.write(buf, r) != r) {
\t\t\t\t\t\t\tLOG(("Update Error: plain-zip: write failed for '%1'").arg(outPath));
\t\t\t\t\t\t\twriteOk = false;
\t\t\t\t\t\t\tbreak;
\t\t\t\t\t\t}
\t\t\t\t\t}
\t\t\t\t\tconst int crcErr = unzCloseCurrentFile(uz);
\t\t\t\t\tout.close();
\t\t\t\t\tif (!writeOk || r < 0 || crcErr != UNZ_OK) {
\t\t\t\t\t\tLOG(("Update Error: plain-zip: extract failed for '%1' (read=%2, crc=%3)").arg(relName).arg(r).arg(crcErr));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
#ifndef Q_OS_WIN
\t\t\t\t\t// external_fa high 16 bits hold Unix st_mode; bit 0100 = S_IXUSR.
\t\t\t\t\t// Ensure executables, bundles, and shared libraries are marked executable.
\t\t\t\t\tif (((info.external_fa >> 16) & 0111)
\t\t\t\t\t\t|| relName == u"AyuGram"_q
\t\t\t\t\t\t|| relName == u"Telegram"_q
\t\t\t\t\t\t|| relName == u"Updater"_q
\t\t\t\t\t\t|| relName.endsWith(u"/AyuGram"_q)
\t\t\t\t\t\t|| relName.endsWith(u"/Telegram"_q)
\t\t\t\t\t\t|| relName.endsWith(u"/Updater"_q)
\t\t\t\t\t\t|| relName.contains(u"MacOS/AyuGram"_q)
\t\t\t\t\t\t|| relName.contains(u"MacOS/Telegram"_q)
\t\t\t\t\t\t|| relName.contains(u"Contents/Frameworks/Updater"_q)
\t\t\t\t\t\t|| relName.contains(u"Contents/Helpers/crashpad_handler"_q)
\t\t\t\t\t\t|| relName.endsWith(u".dylib"_q)
\t\t\t\t\t\t|| relName.endsWith(u".so"_q)) {
\t\t\t\t\t\tQFileDevice::Permissions p = out.permissions();
\t\t\t\t\t\tp |= QFileDevice::ExeOwner | QFileDevice::ExeUser | QFileDevice::ExeGroup | QFileDevice::ExeOther;
\t\t\t\t\t\tout.setPermissions(p);
\t\t\t\t\t}
#endif // !Q_OS_WIN
\t\t\t\t\tif (unzGoToNextFile(uz) != UNZ_OK) break;
\t\t\t\t} while (true);
\t\t\t\tunzClose(uz);

\t\t\t\tif (!extractSuccess) {
\t\t\t\t\tcleanupOnFailure();
\t\t\t\t\treturn false;
\t\t\t\t}

\t\t\t\t// Write tdata/version sentinel (parse real X.Y.Z from filename, fallback to AppVersion + 1)
\t\t\t\tconst QString tdataDir = tempDirPath + u"/tdata"_q;
\t\t\t\tQDir().mkpath(tdataDir);
\t\t\t\tauto parsedVersion = VersionInt(AppVersion + 1);
\t\t\t\tconst auto verMatch = QRegularExpression(
\t\t\t\t\tu"(\\\\d+)\\\\.(\\\\d+)(?:\\\\.(\\\\d+))?"_q
\t\t\t\t).match(QFileInfo(filepath).fileName());
\t\t\t\tif (verMatch.hasMatch()) {
\t\t\t\t\tconst auto maj = verMatch.captured(1).toInt();
\t\t\t\t\tconst auto min = verMatch.captured(2).toInt();
\t\t\t\t\tconst auto pat = verMatch.captured(3).isEmpty() ? 0 : verMatch.captured(3).toInt();
\t\t\t\t\tconst auto candidate = VersionInt(maj * 1000000 + min * 1000 + pat);
\t\t\t\t\tif (candidate > AppVersion) {
\t\t\t\t\t\tparsedVersion = candidate;
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\tconst auto versionNum = parsedVersion;
\t\t\t\tconst auto vMaj = versionNum / 1000000;
\t\t\t\tconst auto vMin = (versionNum % 1000000) / 1000;
\t\t\t\tconst auto vPat = versionNum % 1000;
\t\t\t\tconst auto versionQStr = (vPat > 0)
\t\t\t\t\t? QString(u"%1.%2.%3"_q).arg(vMaj).arg(vMin).arg(vPat)
\t\t\t\t\t: QString(u"%1.%2"_q).arg(vMaj).arg(vMin);
\t\t\t\tconst auto versionStr = versionQStr.toStdWString();
\t\t\t\tconst auto versionLen = VersionInt(versionStr.size() * sizeof(VersionChar));
\t\t\t\tVersionChar versionBuf[32] = {};
\t\t\t\tif (versionLen > 0 && versionLen <= VersionInt(sizeof(versionBuf))) {
\t\t\t\t\tmemcpy(versionBuf, versionStr.c_str(), versionLen);
\t\t\t\t}
\t\t\t\tQFile fVersion(tdataDir + u"/version"_q);
\t\t\t\tif (!fVersion.open(QIODevice::WriteOnly)) {
\t\t\t\t\tLOG(("Update Error: plain-zip: cannot write version file '%1'").arg(tdataDir + u"/version"_q));
\t\t\t\t\tcleanupOnFailure();
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\tfVersion.write((const char*)&versionNum, sizeof(VersionInt));
\t\t\t\tfVersion.write((const char*)&versionLen, sizeof(VersionInt));
\t\t\t\tfVersion.write((const char*)&versionBuf[0], versionLen);
\t\t\t\tfVersion.close();

\t\t\t\t// Write tupdates/temp/ready sentinel file
\t\t\t\tQFile readyFile(readyFilePath);
\t\t\t\tif (!readyFile.open(QIODevice::WriteOnly)
\t\t\t\t\t|| !readyFile.write("1", 1)) {
\t\t\t\t\tLOG(("Update Error: plain-zip: cannot write ready file '%1'").arg(readyFilePath));
\t\t\t\t\tcleanupOnFailure();
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\treadyFile.close();

\t\t\t\t// Anti-bloat: Remove downloaded zip payload immediately after extraction
\t\t\t\tQFile::remove(filepath);

\t\t\t\tLOG(("Update Info: plain-zip update installed cleanly (version %1)").arg(versionNum));
\t\t\t\treturn true;
\t\t\t}
\t\t\tpeek.close();
\t\t}
\t}
\t// === end RezoxP patch ===
'''


class PatchResult:
    def __init__(self):
        self.rows = []
        self.had_critical_failure = False

    def ok(self, patch_id, file_path, detail):
        self.rows.append(("OK", patch_id, file_path, detail))

    def skip(self, patch_id, file_path, detail):
        self.rows.append(("SKIP", patch_id, file_path, detail))

    def warn(self, patch_id, file_path, detail):
        print(f"::warning file={file_path}::patch {patch_id}: {detail}")
        self.rows.append(("WARN", patch_id, file_path, detail))

    def fail(self, patch_id, file_path, detail):
        print(f"::error file={file_path}::patch {patch_id}: {detail}")
        self.rows.append(("FAIL", patch_id, file_path, detail))
        self.had_critical_failure = True

    def report(self):
        print("\n=== Patch Summary Report ===")
        w = max(len(r[1]) for r in self.rows) if self.rows else 0
        for status, patch_id, file_path, detail in self.rows:
            print(f"  [{status:<4}] {patch_id:<{w}}  {file_path}  — {detail}")
        print()


def read_file(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    is_crlf = b"\r\n" in raw
    return raw.decode("utf-8"), is_crlf


def write_file(path: Path, content: str, is_crlf: bool, backup: bool = True):
    if backup:
        bak = path.with_suffix(path.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(path, bak)
    newline = "\r\n" if is_crlf else "\n"
    path.write_text(content, encoding="utf-8", newline=newline)


def patch_max_file_size(root: Path, res: PatchResult, dry: bool):
    fid = "max-file-size"
    path = root / TARGET_DEDICATED_LOADER_H
    if not path.exists():
        res.fail(fid, TARGET_DEDICATED_LOADER_H, "file not found")
        return

    content, is_crlf = read_file(path)
    old = "static constexpr auto kMaxFileSize = 256 * 1024 * 1024;"
    new = "static constexpr int64 kMaxFileSize = int64(2048) * 1024 * 1024;"
    if new in content:
        res.ok(fid, TARGET_DEDICATED_LOADER_H, "already raised kMaxFileSize limit to 2GB")
        return
    if old not in content:
        res.fail(fid, TARGET_DEDICATED_LOADER_H, "kMaxFileSize anchor not found")
        return

    if not dry:
        write_file(path, content.replace(old, new, 1), is_crlf)
    res.ok(fid, TARGET_DEDICATED_LOADER_H, "raised dedicated loader kMaxFileSize from 256MB to 2GB")


def patch_update_url(root: Path, manifest_url: str, res: PatchResult, dry: bool):
    fid = "update-url"
    path = root / TARGET_LOCALSTORAGE
    if not path.exists():
        res.fail(fid, TARGET_LOCALSTORAGE, "file not found")
        return

    normalized_url = manifest_url.rstrip("/") + "/"
    content, is_crlf = read_file(path)
    if f'AutoupdatePrefix("{normalized_url}")' in content:
        res.ok(fid, TARGET_LOCALSTORAGE, "already patched with manifest URL")
        return

    new_content, n = re.subn(r"https://update\.ayugram\.[a-zA-Z0-9._-]+/", normalized_url, content)
    if n == 0:
        res.fail(fid, TARGET_LOCALSTORAGE, "no 'https://update.ayugram.*/' anchor found")
        return

    # Residue check for unpatched legacy URLs
    residue = re.findall(r"[\"']https?://(?:update\.)?ayugram\.one[^\"']*[\"']", new_content)
    if residue:
        res.warn(fid, TARGET_LOCALSTORAGE, f"unpatched ayugram.one URLs remain: {residue}")

    if not dry:
        write_file(path, new_content, is_crlf)
    res.ok(fid, TARGET_LOCALSTORAGE, f"rewrote {n} URL site(s) -> {normalized_url}")


def patch_prefix_override(root: Path, manifest_url: str, res: PatchResult, dry: bool):
    fid = "prefix-override"
    path = root / TARGET_LOCALSTORAGE
    if not path.exists():
        res.fail(fid, TARGET_LOCALSTORAGE, "file not found")
        return

    normalized_url = manifest_url.rstrip("/") + "/"
    content, is_crlf = read_file(path)
    sentinel = "// [AyuGramBuilder] Locked autoupdate prefix"
    if sentinel in content:
        res.ok(fid, TARGET_LOCALSTORAGE, "already locked autoupdate prefix")
        return

    old_raw_pattern = re.compile(
        r"const QString &readAutoupdatePrefixRaw\(\) \{\s*"
        r"Expects\(!Core::UpdaterDisabled\(\)\);\s*"
        r"const auto &result = AutoupdatePrefix\(\);\s*"
        r"if \(!result\.isEmpty\(\)\) \{\s*"
        r"return result;\s*"
        r"\}\s*"
        r"QFile f\(autoupdatePrefixFile\(\)\);\s*"
        r"if \(f\.open\(QIODevice::ReadOnly\)\) \{\s*"
        r"const auto value = QString::fromUtf8\(f\.readAll\(\)\);\s*"
        r"if \(!value\.isEmpty\(\)[^)]*\) \{\s*"
        r"return AutoupdatePrefix\(value\);\s*"
        r"\}\s*"
        r"\}\s*"
        r'return AutoupdatePrefix\("([^"]+)"\);\s*'
        r"\}",
        re.DOTALL,
    )

    new_raw_fn = (
        "const QString &readAutoupdatePrefixRaw() {\n"
        "\tExpects(!Core::UpdaterDisabled());\n\n"
        "\t// [AyuGramBuilder] Locked autoupdate prefix\n"
        "\tconst auto &result = AutoupdatePrefix();\n"
        "\tif (!result.isEmpty()) {\n"
        "\t\treturn result;\n"
        "\t}\n"
        f'\treturn AutoupdatePrefix("{normalized_url}");\n'
        "}"
    )

    if old_raw_pattern.search(content):
        if not dry:
            content = old_raw_pattern.sub(lambda _m: new_raw_fn, content, count=1)
            write_file(path, content, is_crlf)
        res.ok(fid, TARGET_LOCALSTORAGE, "locked readAutoupdatePrefixRaw() against stale tdata/prefix")
        return

    old = "if (!value.isEmpty()) {"
    new = 'if (false && !value.isEmpty()) { // [AyuGramBuilder] Locked autoupdate prefix'
    if old not in content:
        res.warn(fid, TARGET_LOCALSTORAGE, "could not find readAutoupdatePrefixRaw() anchor")
        return

    if not dry:
        content = content.replace(old, new, 1)
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_LOCALSTORAGE, "neutralized cached tdata/prefix override")


def patch_manifest_url(root: Path, res: PatchResult, dry: bool):
    fid = "manifest-url"
    path = root / TARGET_UPDATER
    if not path.exists():
        res.fail(fid, TARGET_UPDATER, "file not found")
        return

    content, is_crlf = read_file(path)
    if 'bestLink.startsWith(QLatin1String("http"))' in content or 'bestLink.startsWith(u"http://"_q)' in content:
        res.ok(fid, TARGET_UPDATER, "already accepts absolute URLs")
        return

    pattern = re.compile(r"Local::readAutoupdatePrefix\(\)\s*\+\s*bestLink\)")
    replacement = (
        '(bestLink.startsWith(u"http://"_q) || bestLink.startsWith(u"https://"_q))\n'
        "\t\t\t? bestLink\n"
        "\t\t\t: (Local::readAutoupdatePrefix() + bestLink))"
    )
    new_content, n = pattern.subn(replacement, content, count=1)
    if n == 0:
        res.fail(fid, TARGET_UPDATER, "anchor 'Local::readAutoupdatePrefix() + bestLink)' not found")
        return

    if not dry:
        write_file(path, new_content, is_crlf)
    res.ok(fid, TARGET_UPDATER, "absolute manifest URLs enabled")


def patch_zip_updates(root: Path, res: PatchResult, dry: bool):
    fid = "zip-updates"
    path = root / TARGET_UPDATER
    if not path.exists():
        res.fail(fid, TARGET_UPDATER, "file not found")
        return

    content, is_crlf = read_file(path)
    newline = "\r\n" if is_crlf else "\n"
    patch_block = ZIP_PATCH_BLOCK.replace("\r\n", "\n").replace("\n", newline)

    # 1. Ensure zlib_help.h and Unix symlink headers are included
    if SENTINEL_INCLUDE not in content:
        lines = content.splitlines()
        insert_at = None
        for i, line in enumerate(lines):
            if line.strip().startswith("#include"):
                insert_at = i + 1
                break
        if insert_at is None:
            res.fail(fid, TARGET_UPDATER, "no #include line to anchor zlib_help.h")
            return
        include_lines = [
            SENTINEL_INCLUDE,
            "#ifndef Q_OS_WIN",
            "#include <unistd.h>",
            "#include <sys/stat.h>",
            "#endif // !Q_OS_WIN",
        ]
        lines[insert_at:insert_at] = include_lines
        content = newline.join(lines) + newline

    # 2. Insert plain zip handler inside UnpackUpdate()
    if SENTINEL_MARKER not in content:
        match = UNPACK_ANCHOR_RE.search(content)
        if not match:
            res.fail(fid, TARGET_UPDATER, f"UnpackUpdate() anchor not found with regex: {UNPACK_ANCHOR_RE.pattern}")
            return
        content = (
            content[:match.end()]
            + newline
            + newline
            + patch_block
            + content[match.end():]
        )

    if not dry:
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_UPDATER, "plain .zip anti-bloat update extraction + symlink & version support installed")


def patch_updater_network_and_files(root: Path, res: PatchResult, dry: bool):
    fid = "updater-network"
    path = root / TARGET_UPDATER
    if not path.exists():
        res.fail(fid, TARGET_UPDATER, "file not found")
        return

    content, is_crlf = read_file(path)
    modified = False

    # 1. Ignore intermediate 3xx HTTP redirect responses in HttpLoaderActor::gotMetaData() & partFinished()
    old_got_metadata = "void HttpLoaderActor::gotMetaData() {\n\tconst auto pairs = _reply->rawHeaderPairs();"
    new_got_metadata = (
        "void HttpLoaderActor::gotMetaData() {\n"
        "\tif (!_reply) return;\n"
        "\tconst auto statusCode = _reply->attribute(QNetworkRequest::HttpStatusCodeAttribute);\n"
        "\tif (statusCode.isValid() && statusCode.toInt() >= 300 && statusCode.toInt() < 400) {\n"
        "\t\treturn;\n"
        "\t}\n"
        "\tconst auto pairs = _reply->rawHeaderPairs();"
    )
    if old_got_metadata in content:
        content = content.replace(old_got_metadata, new_got_metadata, 1)
        modified = True

    old_part_status = "\t\tif (status != 200 && status != 206 && status != 416) {"
    new_part_status = (
        "\t\tif (status >= 300 && status < 400) {\n"
        "\t\t\treturn;\n"
        "\t\t}\n"
        "\t\tif (status != 200 && status != 206 && status != 416) {"
    )
    part_fn_tail = content.split("void HttpLoaderActor::partFinished")[-1][:400]
    if old_part_status in content and "status >= 300 && status < 400" not in part_fn_tail:
        content = content.replace(old_part_status, new_part_status, 1)
        modified = True

    # 1b. Support content-length as well as content-range in HttpLoaderActor::gotMetaData()
    old_meta_loop = (
        '\tfor (const auto &pair : pairs) {\n'
        '\t\tif (QString::fromUtf8(pair.first).toLower() == "content-range") {\n'
        '\t\t\tconst auto m = QRegularExpression(u"/(\\\\d+)([^\\\\d]|$)"_q).match(QString::fromUtf8(pair.second));\n'
        '\t\t\tif (m.hasMatch()) {\n'
        '\t\t\t\t_parent->writeChunk({}, m.captured(1).toLongLong());\n'
        '\t\t\t}\n'
        '\t\t}\n'
        '\t}'
    )
    new_meta_loop = (
        '\tfor (const auto &pair : pairs) {\n'
        '\t\tconst auto name = QString::fromUtf8(pair.first).toLower();\n'
        '\t\tif (name == "content-range") {\n'
        '\t\t\tconst auto m = QRegularExpression(u"/(\\\\d+)([^\\\\d]|$)"_q).match(QString::fromUtf8(pair.second));\n'
        '\t\t\tif (m.hasMatch()) {\n'
        '\t\t\t\t_parent->writeChunk({}, m.captured(1).toLongLong());\n'
        '\t\t\t}\n'
        '\t\t} else if (name == "content-length") {\n'
        '\t\t\tconst auto len = QString::fromUtf8(pair.second).toLongLong();\n'
        '\t\t\tif (len > 0) {\n'
        '\t\t\t\t_parent->writeChunk({}, _parent->alreadySize() + len);\n'
        '\t\t\t}\n'
        '\t\t}\n'
        '\t}'
    )
    if old_meta_loop in content:
        content = content.replace(old_meta_loop, new_meta_loop, 1)
        modified = True

    # 2. Preserve '.' in ExtractFilename() so .zip extension is kept
    old_extract_re = 'QRegularExpression(u"[^a-zA-Z0-9_\\\\-]"_q)'
    new_extract_re = 'QRegularExpression(u"[^a-zA-Z0-9_\\\\-\\\\.]"_q)'
    if old_extract_re in content:
        content = content.replace(old_extract_re, new_extract_re, 1)
        modified = True

    # 3. Recognize AyuGram-* archive files in FindUpdateFile()
    old_find_match = (
        "\t\tif (RegExp.match(info.fileName()).hasMatch()\n"
        "\t\t\t|| RegExpV2.match(info.fileName()).hasMatch()) {"
    )
    new_find_match = (
        "\t\tif (RegExp.match(info.fileName()).hasMatch()\n"
        "\t\t\t|| RegExpV2.match(info.fileName()).hasMatch()\n"
        "\t\t\t|| info.fileName().startsWith(u\"AyuGram-\"_q, Qt::CaseInsensitive)) {"
    )
    if old_find_match in content:
        content = content.replace(old_find_match, new_find_match, 1)
        modified = True

    # 4. Make Windows DeleteFile(updater) in checkReadyUpdate() non-fatal if CopyFile already succeeded
    old_win_del = (
        "\tif (DeleteFile(updater.absoluteFilePath().toStdWString().c_str()) == FALSE) {\n"
        "\t\tClearAll();\n"
        "\t\treturn false;\n"
        "\t}"
    )
    new_win_del = (
        "\tif (DeleteFile(updater.absoluteFilePath().toStdWString().c_str()) == FALSE) {\n"
        "\t\tLOG((\"Update Warning: could not delete temp Updater.exe, continuing anyway.\"));\n"
        "\t}"
    )
    if old_win_del in content:
        content = content.replace(old_win_del, new_win_del, 1)
        modified = True

    # 5. Ensure intermediate dir exists before copying current updater in checkReadyUpdate()
    old_chk_copy = (
        "\tif (!updater.exists()) {\n"
        "\t\tQFileInfo current(curUpdater);\n"
        "\t\tif (!current.exists()) {\n"
        "\t\t\tClearAll();\n"
        "\t\t\treturn false;\n"
        "\t\t}\n"
        "\t\tif (!QFile(current.absoluteFilePath()).copy(updater.absoluteFilePath())) {"
    )
    new_chk_copy = (
        "\tif (!updater.exists()) {\n"
        "\t\tQFileInfo current(curUpdater);\n"
        "\t\tif (!current.exists()) {\n"
        "\t\t\tClearAll();\n"
        "\t\t\treturn false;\n"
        "\t\t}\n"
        "\t\tQDir().mkpath(updater.absolutePath());\n"
        "\t\tif (!QFile(current.absoluteFilePath()).copy(updater.absoluteFilePath())) {"
    )
    if old_chk_copy in content:
        content = content.replace(old_chk_copy, new_chk_copy, 1)
        modified = True

    # 6. Fallback platform lookup in ParseCommonMap (e.g. winarm -> win64 -> win; mac <-> armac)
    old_platform_lookup = (
        "\tconst auto platforms = document.object();\n"
        "\tconst auto platform = Platform::AutoUpdateKey();\n"
        "\tconst auto it = platforms.constFind(platform);\n"
        "\tif (it == platforms.constEnd()) {"
    )
    new_platform_lookup = (
        "\tconst auto platforms = document.object();\n"
        "\tauto platform = Platform::AutoUpdateKey();\n"
        "\tauto it = platforms.constFind(platform);\n"
        "\tif (it == platforms.constEnd()) {\n"
        "\t\tif (platform == u\"winarm\"_q) {\n"
        "\t\t\tit = platforms.constFind(u\"win64\"_q);\n"
        "\t\t\tif (it == platforms.constEnd()) {\n"
        "\t\t\t\tit = platforms.constFind(u\"win\"_q);\n"
        "\t\t\t}\n"
        "\t\t} else if (platform == u\"win64\"_q) {\n"
        "\t\t\tit = platforms.constFind(u\"win\"_q);\n"
        "\t\t} else if (platform == u\"armac\"_q) {\n"
        "\t\t\tit = platforms.constFind(u\"mac\"_q);\n"
        "\t\t} else if (platform == u\"mac\"_q) {\n"
        "\t\t\tit = platforms.constFind(u\"armac\"_q);\n"
        "\t\t}\n"
        "\t}\n"
        "\tif (it == platforms.constEnd()) {"
    )
    if old_platform_lookup in content:
        content = content.replace(old_platform_lookup, new_platform_lookup, 1)
        modified = True

    # 7. Fallback to /current on 404/invalid version manifest in HttpChecker::gotResponse() and gotFailure()
    old_got_response = (
        "\tcSetLastUpdateCheck(base::unixtime::now());\n"
        "\tconst auto response = _reply->readAll();\n"
        "\tclearSentRequest();\n"
        "\n"
        "\tif (response.size() >= kMaxResponseSize || !handleResponse(response)) {"
    )
    new_got_response = (
        "\tcSetLastUpdateCheck(base::unixtime::now());\n"
        "\tconst auto statusCode = _reply ? _reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt() : 0;\n"
        "\tconst auto requestUrl = _reply ? _reply->url().toString() : QString();\n"
        "\tconst auto response = _reply->readAll();\n"
        "\tclearSentRequest();\n"
        "\n"
        "\tif (statusCode >= 400 || response.size() >= kMaxResponseSize || !handleResponse(response)) {\n"
        "\t\tLOG((\"Update Error: Bad update map (status: %1, size: %2)\").arg(statusCode).arg(response.size()));\n"
        "\t\tif (!requestUrl.isEmpty() && !requestUrl.endsWith(u\"/current\"_q)) {\n"
        "\t\t\tLOG((\"Update Info: Falling back to universal /current manifest\"));\n"
        "\t\t\tauto url = QUrl(Local::readAutoupdatePrefix() + u\"/current\"_q);\n"
        "\t\t\tauto request = QNetworkRequest(url);\n"
        "\t\t\trequest.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);\n"
        "\t\t\t_manager = std::make_unique<QNetworkAccessManager>();\n"
        "\t\t\t_reply = _manager->get(request);\n"
        "\t\t\t_reply->connect(_reply, &QNetworkReply::finished, [=] {\n"
        "\t\t\t\tgotResponse();\n"
        "\t\t\t});\n"
        "\t\t\t_reply->connect(_reply, &QNetworkReply::errorOccurred, [=](auto e) {\n"
        "\t\t\t\tgotFailure(e);\n"
        "\t\t\t});\n"
        "\t\t\treturn;\n"
        "\t\t}"
    )
    if old_got_response in content:
        content = content.replace(old_got_response, new_got_response, 1)
        modified = True

    old_got_failure = (
        "void HttpChecker::gotFailure(QNetworkReply::NetworkError e) {\n"
        "\tLOG((\"Update Error: \"\n"
        "\t\t\"could not get current version %1\").arg(e));\n"
        "\tif (const auto reply = base::take(_reply)) {\n"
        "\t\treply->deleteLater();\n"
        "\t}\n"
        "\n"
        "\tfail();\n"
        "}"
    )
    new_got_failure = (
        "void HttpChecker::gotFailure(QNetworkReply::NetworkError e) {\n"
        "\tLOG((\"Update Error: \"\n"
        "\t\t\"could not get current version %1\").arg(e));\n"
        "\tif (_reply) {\n"
        "\t\tconst auto requestUrl = _reply->url().toString();\n"
        "\t\tclearSentRequest();\n"
        "\t\tif (!requestUrl.isEmpty() && !requestUrl.endsWith(u\"/current\"_q)) {\n"
        "\t\t\tLOG((\"Update Info: Falling back to universal /current manifest on failure\"));\n"
        "\t\t\tauto url = QUrl(Local::readAutoupdatePrefix() + u\"/current\"_q);\n"
        "\t\t\tauto request = QNetworkRequest(url);\n"
        "\t\t\trequest.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);\n"
        "\t\t\t_manager = std::make_unique<QNetworkAccessManager>();\n"
        "\t\t\t_reply = _manager->get(request);\n"
        "\t\t\t_reply->connect(_reply, &QNetworkReply::finished, [=] {\n"
        "\t\t\t\tgotResponse();\n"
        "\t\t\t});\n"
        "\t\t\t_reply->connect(_reply, &QNetworkReply::errorOccurred, [=](auto err) {\n"
        "\t\t\t\tgotFailure(err);\n"
        "\t\t\t});\n"
        "\t\t\treturn;\n"
        "\t\t}\n"
        "\t} else {\n"
        "\t\tclearSentRequest();\n"
        "\t}\n"
        "\n"
        "\tfail();\n"
        "}"
    )
    if old_got_failure in content:
        content = content.replace(old_got_failure, new_got_failure, 1)
        modified = True

    if modified and not dry:
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_UPDATER, "fallback manifest /current, platform fallback, .zip filenames & 3xx redirect guards")


def patch_platform_updaters(root: Path, res: PatchResult, dry: bool):
    fid = "platform-updaters"

    # 1. application.cpp: ensure checkReadyUpdate() is called inside Core::Restart()
    app_path = root / TARGET_APPLICATION
    if app_path.exists():
        content, is_crlf = read_file(app_path)
        if "&& checkReadyUpdate();" not in content:
            patched, n = re.subn(
                r"(const\s+auto\s+updateReady\s*=\s*!UpdaterDisabled\(\)\s*&&\s*\(UpdateChecker\(\)\.state\(\)\s*==\s*UpdateChecker::State::Ready\));",
                r"\1\n\t   && checkReadyUpdate();",
                content,
                count=1,
            )
            if n > 0 and not dry:
                write_file(app_path, patched, is_crlf)
        res.ok(fid, TARGET_APPLICATION, "Core::Restart() stages ready update via checkReadyUpdate()")

    # 2. updater_win.cpp: skip running Updater.exe instead of aborting update & protect registry
    win_path = root / TARGET_UPDATER_WIN
    if win_path.exists():
        content, is_crlf = read_file(win_path)
        modified = False
        old_win_block = (
            '\t\t\t\tif (equal(tofname, updaterName)) { // bad update - has Updater.exe - delete all dir\n'
            '\t\t\t\t\twriteLog(L"Error: bad update, has Updater.exe! \'" + tofname + L"\' equal \'" + updaterName + L"\'");\n'
            '\t\t\t\t\tdelFolder();\n'
            '\t\t\t\t\treturn false;\n'
            '\t\t\t\t} else if (equal(tofname, updateTo + L"AyuGram.exe") && exeName != L"AyuGram.exe") {\n'
            '\t\t\t\t\twstring fullBinaryPath = updateTo + exeName;\n'
            '\t\t\t\t\twriteLog(L"Target binary found: \'" + tofname + L"\', changing to \'" + fullBinaryPath + L"\'");\n'
            '\t\t\t\t\ttofname = fullBinaryPath;\n'
            '\t\t\t\t}'
        )
        new_win_block = (
            '\t\t\t\tif (equal(tofname, updaterName)) {\n'
            '\t\t\t\t\twriteLog(L"Skipped running Updater.exe: \'" + tofname + L"\'");\n'
            '\t\t\t\t\tcontinue;\n'
            '\t\t\t\t} else if ((equal(tofname, updateTo + L"AyuGram.exe") || equal(tofname, updateTo + L"Telegram.exe")) && exeName != L"AyuGram.exe") {\n'
            '\t\t\t\t\twstring fullBinaryPath = updateTo + exeName;\n'
            '\t\t\t\t\twriteLog(L"Target binary found: \'" + tofname + L"\', changing to \'" + fullBinaryPath + L"\'");\n'
            '\t\t\t\t\ttofname = fullBinaryPath;\n'
            '\t\t\t\t}'
        )
        if old_win_block in content:
            content = content.replace(old_win_block, new_win_block, 1)
            modified = True
        if 'if (installpath == mypath + L"\\\\" || true)' in content:
            content = content.replace(
                'if (installpath == mypath + L"\\\\" || true)',
                'if (installpath == mypath + L"\\\\")',
                1,
            )
            modified = True
        if 'static const WCHAR *_programName = L"Telegram Desktop";' in content:
            content = content.replace(
                'static const WCHAR *_programName = L"Telegram Desktop";',
                'static const WCHAR *_programName = L"AyuGram Desktop";',
                1,
            )
            modified = True
        if modified and not dry:
            write_file(win_path, content, is_crlf)
        res.ok(fid, TARGET_UPDATER_WIN, "hardened Windows Updater.exe self-skip & registry check")

    # 3. updater_linux.cpp: fix hardcoded "Telegram" -> "AyuGram" & skip running Updater
    linux_path = root / TARGET_UPDATER_LINUX
    if linux_path.exists():
        content, is_crlf = read_file(linux_path)
        modified = False
        old_linux_block = (
            '\t\t\t\t\tif (equal(tofname, updaterName)) { // bad update - has Updater - delete all dir\n'
            '\t\t\t\t\t\twriteLog("Error: bad update, has Updater! \'%s\' equal \'%s\'", tofname.c_str(), updaterName.c_str());\n'
            '\t\t\t\t\t\tdelFolder();\n'
            '\t\t\t\t\t\treturn false;\n'
            '\t\t\t\t\t} else if (equal(tofname, exePath + "Telegram") && exeName != "Telegram") {\n'
            '\t\t\t\t\t\tstring fullBinaryPath = exePath + exeName;\n'
            '\t\t\t\t\t\twriteLog("Target binary found: \'%s\', changing to \'%s\'", tofname.c_str(), fullBinaryPath.c_str());\n'
            '\t\t\t\t\t\ttofname = fullBinaryPath;\n'
            '\t\t\t\t\t}'
        )
        new_linux_block = (
            '\t\t\t\t\tif (equal(tofname, updaterName)) {\n'
            '\t\t\t\t\t\twriteLog("Skipped running Updater: \'%s\'", tofname.c_str());\n'
            '\t\t\t\t\t\tcontinue;\n'
            '\t\t\t\t\t} else if ((equal(tofname, exePath + "AyuGram") || equal(tofname, exePath + "Telegram")) && exeName != "AyuGram" && exeName != "Telegram") {\n'
            '\t\t\t\t\t\tstring fullBinaryPath = exePath + exeName;\n'
            '\t\t\t\t\t\twriteLog("Target binary found: \'%s\', changing to \'%s\'", tofname.c_str(), fullBinaryPath.c_str());\n'
            '\t\t\t\t\t\ttofname = fullBinaryPath;\n'
            '\t\t\t\t\t} else if (equal(tofname, exePath + "Telegram") && exeName == "AyuGram") {\n'
            '\t\t\t\t\t\tstring fullBinaryPath = exePath + "AyuGram";\n'
            '\t\t\t\t\t\twriteLog("Target binary found: \'%s\', changing to \'%s\'", tofname.c_str(), fullBinaryPath.c_str());\n'
            '\t\t\t\t\t\ttofname = fullBinaryPath;\n'
            '\t\t\t\t\t}'
        )
        if old_linux_block in content:
            content = content.replace(old_linux_block, new_linux_block, 1)
            modified = True
        if '\texeName = "Telegram";' in content:
            content = content.replace('\texeName = "Telegram";', '\texeName = "AyuGram";')
            modified = True
        if modified and not dry:
            write_file(linux_path, content, is_crlf)
        res.ok(fid, TARGET_UPDATER_LINUX, "fixed Linux Updater target binary Telegram -> AyuGram & self-skip")

    # 4. specific_linux.cpp: make fchown() non-fatal in linuxMoveFile()
    spec_linux_path = root / TARGET_SPECIFIC_LINUX
    if spec_linux_path.exists():
        content, is_crlf = read_file(spec_linux_path)
        old_chown = (
            "\t//update to the same uid/gid\n"
            "\tif (fchown(fileno(fto), fst.st_uid, fst.st_gid) != 0) {\n"
            "\t\tfclose(ffrom);\n"
            "\t\tfclose(fto);\n"
            "\t\treturn false;\n"
            "\t}"
        )
        new_chown = (
            "\t//update to the same uid/gid (best-effort; ignore EPERM on unprivileged mounts)\n"
            "\t(void)fchown(fileno(fto), fst.st_uid, fst.st_gid);"
        )
        if old_chown in content and not dry:
            write_file(spec_linux_path, content.replace(old_chown, new_chown, 1), is_crlf)
        res.ok(fid, TARGET_SPECIFIC_LINUX, "made fchown() non-fatal in linuxMoveFile()")


def patch_mac_updater(root: Path, res: PatchResult, dry: bool):
    fid = "mac-updater-path"
    path = root / TARGET_UPDATER
    if path.exists():
        content, is_crlf = read_file(path)
        if "u\"tupdates/temp/\"_q + appBundle" in content or "cExeName().endsWith(u\".app\"_q)" in content:
            res.ok(fid, TARGET_UPDATER, "already patched for dynamic app bundle updater path")
        else:
            old = 'QString curUpdater = (cExeDir() + cExeName() + u"/Contents/Frameworks/Updater"_q);\n\tQFileInfo updater(cWorkingDir() + u"tupdates/temp/Telegram.app/Contents/Frameworks/Updater"_q);'
            new = (
                'const auto appBundle = cExeName().endsWith(u".app"_q) ? cExeName() : (cExeName() + u".app"_q);\n'
                '\tQString curUpdater = (cExeDir() + appBundle + u"/Contents/Frameworks/Updater"_q);\n'
                '\tQFileInfo updater(cWorkingDir() + u"tupdates/temp/"_q + appBundle + u"/Contents/Frameworks/Updater"_q);\n'
                '\tif (!updater.exists()) {\n'
                '\t\tupdater.setFile(cWorkingDir() + u"tupdates/temp/AyuGram.app/Contents/Frameworks/Updater"_q);\n'
                '\t}\n'
                '\tif (!updater.exists()) {\n'
                '\t\tupdater.setFile(cWorkingDir() + u"tupdates/temp/Telegram.app/Contents/Frameworks/Updater"_q);\n'
                '\t}\n'
                '\tif (!updater.exists()) {\n'
                '\t\tupdater.setFile(cWorkingDir() + u"tupdates/temp/Updater"_q);\n'
                '\t}'
            )
            if old in content:
                if not dry:
                    write_file(path, content.replace(old, new, 1), is_crlf)
                res.ok(fid, TARGET_UPDATER, "patched macOS updater to dynamically resolve AyuGram.app bundle")
            elif old.replace('\n', '\r\n') in content:
                if not dry:
                    write_file(path, content.replace(old.replace('\n', '\r\n'), new.replace('\n', '\r\n'), 1), is_crlf)
                res.ok(fid, TARGET_UPDATER, "patched macOS updater to dynamically resolve AyuGram.app bundle")
            else:
                res.warn(fid, TARGET_UPDATER, "anchor for macOS Telegram.app updater path not found")

    # Guard Xcode 26 folder.iconcomposer.icon in Telegram/CMakeLists.txt
    cmake_path = root / TARGET_TELEGRAM_CMAKE
    if cmake_path.exists():
        c_content, c_crlf = read_file(cmake_path)
        old_icon = (
            "    set(icons_path ${CMAKE_CURRENT_SOURCE_DIR}/Telegram/Images.xcassets)\n"
            "    if (CMAKE_GENERATOR STREQUAL Xcode)"
        )
        new_icon = (
            "    set(icons_path ${CMAKE_CURRENT_SOURCE_DIR}/Telegram/Images.xcassets)\n"
            "    if (CMAKE_GENERATOR STREQUAL Xcode AND XCODE_VERSION VERSION_GREATER_EQUAL 26.0)"
        )
        if old_icon in c_content:
            if not dry:
                write_file(cmake_path, c_content.replace(old_icon, new_icon, 1), c_crlf)
            res.ok("mac-xcode-icon", TARGET_TELEGRAM_CMAKE, "guarded folder.iconcomposer.icon behind Xcode >= 26.0")
        elif "XCODE_VERSION VERSION_GREATER_EQUAL 26.0" in c_content:
            res.ok("mac-xcode-icon", TARGET_TELEGRAM_CMAKE, "Xcode >= 26.0 icon guard already applied")

    # Hardened updater_osx.m bundle resolution and non-fatal Updater copy
    osx_path = root / TARGET_UPDATER_OSX
    if osx_path.exists():
        content_osx, crlf_osx = read_file(osx_path)
        modified_osx = False
        old_osx_copy = (
            '\t\tif (![fileManager fileExistsAtPath:newVersionUpdaterPath]) {\n'
            '\t\t\tif (![fileManager copyItemAtPath:oldVersionUpdaterPath toPath:newVersionUpdaterPath error:nil]) {\n'
            '\t\t\t\twriteLog([[NSArray arrayWithObjects: @"Failed to copy file from ", oldVersionUpdaterPath, @" to ", newVersionUpdaterPath, nil] componentsJoinedByString:@""]);\n'
            '\t\t\t\tdelFolder();\n'
            '\t\t\t\treturn -1;\n'
            '\t\t\t}\n'
            '\t\t}'
        )
        new_osx_copy = (
            '\t\tif (![fileManager fileExistsAtPath:newVersionUpdaterPath]) {\n'
            '\t\t\t[fileManager createDirectoryAtPath:[newVersionUpdaterPath stringByDeletingLastPathComponent] withIntermediateDirectories:YES attributes:nil error:nil];\n'
            '\t\t\tif ([fileManager fileExistsAtPath:oldVersionUpdaterPath]) {\n'
            '\t\t\t\tif (![fileManager copyItemAtPath:oldVersionUpdaterPath toPath:newVersionUpdaterPath error:nil]) {\n'
            '\t\t\t\t\twriteLog([[NSArray arrayWithObjects: @"Warning: Failed to copy file from ", oldVersionUpdaterPath, @" to ", newVersionUpdaterPath, nil] componentsJoinedByString:@""]);\n'
            '\t\t\t\t}\n'
            '\t\t\t}\n'
            '\t\t}'
        )
        if old_osx_copy in content_osx:
            content_osx = content_osx.replace(old_osx_copy, new_osx_copy, 1)
            modified_osx = True

        old_osx_bundle = (
            '\t\t\tNSString *pathPart = [srcPath substringFromIndex:r.length];\n'
            '\t\t\tr = [pathPart rangeOfString:appName];\n'
            '\t\t\tif (r.location != 0) {\n'
            '\t\t\t\twriteLog([@"Skipping not app file " stringByAppendingString:srcPath]);\n'
            '\t\t\t\tcontinue;\n'
            '\t\t\t}\n'
            '\t\t\tNSString *dstPath = [appDirFull stringByAppendingString:[pathPart substringFromIndex:r.length]];'
        )
        new_osx_bundle = (
            '\t\t\tNSString *pathPart = [srcPath substringFromIndex:r.length];\n'
            '\t\t\tNSString *bundlePrefix = nil;\n'
            '\t\t\tif ([pathPart hasPrefix:@"AyuGram.app"]) {\n'
            '\t\t\t\tbundlePrefix = @"AyuGram.app";\n'
            '\t\t\t} else if ([pathPart hasPrefix:@"Telegram.app"]) {\n'
            '\t\t\t\tbundlePrefix = @"Telegram.app";\n'
            '\t\t\t} else if ([pathPart hasPrefix:appName]) {\n'
            '\t\t\t\tbundlePrefix = appName;\n'
            '\t\t\t}\n'
            '\t\t\tif (!bundlePrefix) {\n'
            '\t\t\t\twriteLog([@"Skipping not app file " stringByAppendingString:srcPath]);\n'
            '\t\t\t\tcontinue;\n'
            '\t\t\t}\n'
            '\t\t\tNSString *dstPath = [appDirFull stringByAppendingString:[pathPart substringFromIndex:[bundlePrefix length]]];'
        )
        if old_osx_bundle in content_osx:
            content_osx = content_osx.replace(old_osx_bundle, new_osx_bundle, 1)
            modified_osx = True

        if modified_osx and not dry:
            write_file(osx_path, content_osx, crlf_osx)
        res.ok(fid, TARGET_UPDATER_OSX, "hardened macOS Updater binary copy & bundle prefix handling")


GIT_MIRRORS = {
    "https://code.videolan.org/videolan/dav1d.git": "https://github.com/videolan/dav1d.git",
    "https://chromium.googlesource.com/breakpad/breakpad": "https://github.com/google/breakpad.git",
}


def patch_git_mirrors(root: Path, res: PatchResult, dry: bool):
    fid = "git-mirrors"
    path = root / TARGET_PREPARE
    if not path.exists():
        res.warn(fid, TARGET_PREPARE, "prepare.py not found")
        return

    content, is_crlf = read_file(path)
    replaced = []
    for old, new in GIT_MIRRORS.items():
        if old in content:
            content = content.replace(old, new)
            replaced.append(old.split("/")[-1].replace(".git", ""))

    if replaced:
        if not dry:
            write_file(path, content, is_crlf)
        res.ok(fid, TARGET_PREPARE, f"mirrored {', '.join(replaced)} to reliable GitHub remotes")
    else:
        res.ok(fid, TARGET_PREPARE, "all git mirrors already applied or up to date")


def patch_prepare_tg_owt(root: Path, res: PatchResult, dry: bool):
    fid = "tg-owt-win-syntax"
    path = root / TARGET_PREPARE
    if not path.exists():
        res.warn(fid, TARGET_PREPARE, "prepare.py not found")
        return

    content, is_crlf = read_file(path)
    idx = content.find("stage('tg_owt'")
    if idx == -1:
        res.warn(fid, TARGET_PREPARE, "stage('tg_owt') not found in prepare.py")
        return

    idx2 = content.find("cmake -B out", idx)
    if idx2 == -1:
        res.warn(fid, TARGET_PREPARE, "cmake -B out not found in stage('tg_owt')")
        return

    end_idx = content.find("cmake --build out", idx2)
    if end_idx == -1:
        res.warn(fid, TARGET_PREPARE, "cmake --build out not found in stage('tg_owt')")
        return

    chunk = content[idx2:end_idx]
    if "cmake -B out ^" in chunk:
        res.ok(fid, TARGET_PREPARE, "already patched tg_owt Windows cmd syntax")
        return

    fixed_chunk = re.sub(r'\\\s*(\r?\n)', r'^\1', chunk)
    if fixed_chunk == chunk:
        res.ok(fid, TARGET_PREPARE, "no backslash continuation found in tg_owt stage")
        return

    new_content = content[:idx2] + fixed_chunk + content[end_idx:]
    if not dry:
        write_file(path, new_content, is_crlf)
    res.ok(fid, TARGET_PREPARE, "fixed tg_owt Windows cmd line continuations (\\ -> ^)")


# Pinned MSYS2 installer used when dynamic lookup fails (offline runners, API hiccups).
PINNED_MSYS2_URL = "https://github.com/msys2/msys2-installer/releases/download/2026-09-27/msys2-base-x86_64-20260927.sfx.exe"
MSYS2_URL_RE = re.compile(
    r"https://github\.com/msys2/msys2-installer/releases/download/[^/\s\"']+/msys2-base-x86_64-[0-9]+\.sfx\.exe"
)
_msys2_url_cache = None


def resolve_msys2_url() -> str:
    """Return the newest msys2-base installer URL, preferring a live lookup
    of the latest msys2-installer release so the pinned keyring never rots.

    Never raises: falls back to PINNED_MSYS2_URL on any failure."""
    global _msys2_url_cache
    if _msys2_url_cache is not None:
        return _msys2_url_cache
    url = PINNED_MSYS2_URL
    try:
        import json as _json
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/msys2/msys2-installer/releases/latest",
            headers={"User-Agent": "AyuGramDesktop-builder", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            release = _json.loads(resp.read().decode("utf-8"))
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if re.fullmatch(r"msys2-base-x86_64-[0-9]+\.sfx\.exe", name):
                url = asset["browser_download_url"]
                break
    except Exception as e:
        print(f"::notice::msys2 latest-release lookup failed ({e}); using pinned installer")
    _msys2_url_cache = url
    return url


def patch_msys2_ucrt64(root: Path, res: PatchResult, dry: bool):
    fid = "msys2-ucrt64"
    path = root / TARGET_PREPARE
    if not path.exists():
        res.warn(fid, TARGET_PREPARE, "prepare.py not found")
        return

    content, is_crlf = read_file(path)
    if "nasm-2.16.03-win64.zip" in content and "ThirdParty\\\\msys64\\\\ucrt64" in content:
        res.ok(fid, TARGET_PREPARE, "already updated to MSYS2 UCRT64 + SigLevel bypass + NASM 2.16.03")
        return

    new_url = resolve_msys2_url()
    patched = content.replace(
        "'ThirdParty\\\\msys64\\\\mingw64\\\\bin'",
        "'ThirdParty\\\\msys64\\\\ucrt64\\\\bin'",
    )

    msys_stage_re = re.compile(
        r'(powershell -Command "iwr -OutFile \./msys64\.exe https://github\.com/msys2/msys2-installer/releases/download/)[^"]+("\s+'
        r'msys64\.exe\s+'
        r'del msys64\.exe\s+)'
        r'bash -c "pacman-key --init; pacman-key --populate; pacman -Syu --noconfirm"\s+'
        r'pacman -S(?:yu)?(?: --needed)? --noconfirm \^\s+'
        r'make \^\s+'
        r'mingw-w64-(?:ucrt-)?x86_64-diffutils \^\s+'
        r'mingw-w64-(?:ucrt-)?x86_64-gperf \^\s+'
        r'mingw-w64-(?:ucrt-)?x86_64-nasm \^\s+'
        r'mingw-w64-(?:ucrt-)?x86_64-perl \^\s+'
        r'mingw-w64-(?:ucrt-)?x86_64-pkgconf',
        re.DOTALL,
    )

    def _build_msys_replacement(m: re.Match) -> str:
        # Extract release path after /releases/download/
        rel_path = new_url.split("/releases/download/", 1)[-1] if "/releases/download/" in new_url else "2026-09-27/msys2-base-x86_64-20260927.sfx.exe"
        return (
            m.group(1)
            + rel_path
            + m.group(2)
            + 'bash -c "sed -i \'s/^SigLevel.*/SigLevel = Never/\' /etc/pacman.conf; '
            "pacman -Sy --noconfirm msys2-keyring; pacman-key --init; pacman-key --populate; "
            'pacman -Su --noconfirm"\n'
            "    pacman -S --needed --noconfirm ^\n"
            "        make ^\n"
            "        mingw-w64-ucrt-x86_64-diffutils ^\n"
            "        mingw-w64-ucrt-x86_64-gperf ^\n"
            "        mingw-w64-ucrt-x86_64-nasm ^\n"
            "        mingw-w64-ucrt-x86_64-perl ^\n"
            "        mingw-w64-ucrt-x86_64-pkgconf\n"
            '    powershell -Command "iwr -OutFile ./nasm.zip https://www.nasm.us/pub/nasm/releasebuilds/2.16.03/win64/nasm-2.16.03-win64.zip; '
            "Expand-Archive -Force ./nasm.zip ./nasm_tmp; "
            "Copy-Item -Force ./nasm_tmp/nasm-2.16.03/nasm.exe %THIRDPARTY_DIR%\\\\msys64\\\\ucrt64\\\\bin\\\\nasm.exe; "
            "Copy-Item -Force ./nasm_tmp/nasm-2.16.03/ndisasm.exe %THIRDPARTY_DIR%\\\\msys64\\\\ucrt64\\\\bin\\\\ndisasm.exe; "
            'Remove-Item -Recurse -Force ./nasm.zip, ./nasm_tmp"'
        )

    patched, count = msys_stage_re.subn(_build_msys_replacement, patched, count=1)
    if count == 0:
        # Fallback: substitute URL and packages individually
        patched = MSYS2_URL_RE.sub(new_url, patched)
        for pkg in ["diffutils", "gperf", "nasm", "perl", "pkgconf"]:
            patched = patched.replace(f"mingw-w64-x86_64-{pkg}", f"mingw-w64-ucrt-x86_64-{pkg}")

    if "if build_debug:" in patched:
        patched = patched.replace("if build_debug:", "if False:")

    if not dry:
        write_file(path, patched, is_crlf)
    res.ok(fid, TARGET_PREPARE, f"migrated to MSYS2 UCRT64 ({new_url.rsplit('/', 2)[-2]}), SigLevel bypass & pinned NASM 2.16.03")


def patch_qt_release_only(root: Path, res: PatchResult, dry: bool):
    fid = "qt-release-only"
    path = root / TARGET_PREPARE
    if not path.exists():
        res.warn(fid, TARGET_PREPARE, "prepare.py not found")
        return

    content, is_crlf = read_file(path)
    patched = content.replace(
        "SET CONFIGURATIONS=-debug-and-release",
        "SET CONFIGURATIONS=-release",
    ).replace(
        "CONFIGURATIONS=-debug-and-release",
        "CONFIGURATIONS=-release",
    )

    old_qt6_win_build = (
        "    cmake --build . --config Debug\n"
        "    cmake --install . --config Debug\n"
        "    cmake --build .\n"
        "    cmake --install ."
    )
    new_qt6_win_build = (
        "    cmake --build . --config Release\n"
        "    cmake --install . --config Release"
    )
    if old_qt6_win_build in patched:
        patched = patched.replace(old_qt6_win_build, new_qt6_win_build, 1)

    if patched == content:
        res.ok(fid, TARGET_PREPARE, "already configured Qt release-only")
        return

    if not dry:
        write_file(path, patched, is_crlf)
    res.ok(fid, TARGET_PREPARE, "configured Qt release-only for Windows & macOS")


def patch_tlottie_rust(root: Path, res: PatchResult, dry: bool):
    fid = "tlottie-rust"
    prep_path = root / TARGET_PREPARE
    if prep_path.exists():
        content, is_crlf = read_file(prep_path)
        old_rustup = "--target aarch64-pc-windows-msvc"
        new_rustup = (
            "--target aarch64-pc-windows-msvc ^\n"
            "        --target x86_64-pc-windows-msvc ^\n"
            "        --target i686-pc-windows-msvc"
        )
        if old_rustup in content and "--target x86_64-pc-windows-msvc" not in content:
            if not dry:
                write_file(prep_path, content.replace(old_rustup, new_rustup, 1), is_crlf)
            res.ok(fid, TARGET_PREPARE, "added x86_64/i686-pc-windows-msvc targets to rust stage")

    path = root / TARGET_TLOTTIE
    if not path.exists():
        return

    content, is_crlf = read_file(path)
    patched = content.replace(
        "find_library(DESKTOP_APP_TLOTTIE_LIBRARY tlottie REQUIRED)",
        "find_library(DESKTOP_APP_TLOTTIE_LIBRARY NAMES tlottie tdesktop_rust REQUIRED)",
    ).replace(
        "i686-win7-windows-msvc", "i686-pc-windows-msvc"
    ).replace(
        "x86_64-win7-windows-msvc", "x86_64-pc-windows-msvc"
    ).replace(
        "-Z build-std=std,panic_abort", ""
    )

    if patched != content and not dry:
        write_file(path, patched, is_crlf)
    res.ok(fid, TARGET_TLOTTIE, "enabled tdesktop_rust & standard MSVC target fallback for tlottie")


def patch_cmake_windows(root: Path, res: PatchResult, dry: bool):
    fid = "cmake-windows"
    opt_path = root / TARGET_OPTIONS_WIN
    if opt_path.exists():
        content, is_crlf = read_file(opt_path)
        modified = False
        if "/FS" not in content and "/MP" in content:
            content = content.replace("/MP", "/MP\n        /FS", 1)
            modified = True
        if "$<IF:$<BOOL:${DESKTOP_APP_DISABLE_CRASH_REPORTS}>,,/Zi>" not in content:
            content, n1 = re.subn(
                r"^(\s*)/Zi$",
                r"\1$<IF:$<BOOL:${DESKTOP_APP_DISABLE_CRASH_REPORTS}>,,/Zi>",
                content,
                flags=re.MULTILINE,
            )
            content, n2 = re.subn(
                r"^(\s*)/DEBUG$",
                r"\1$<IF:$<BOOL:${DESKTOP_APP_DISABLE_CRASH_REPORTS}>,,/DEBUG>",
                content,
                flags=re.MULTILINE,
            )
            if n1 > 0 or n2 > 0:
                modified = True
        if modified and not dry:
            write_file(opt_path, content, is_crlf)
        res.ok(fid, TARGET_OPTIONS_WIN, "added /FS & gated /Zi and /DEBUG behind NOT DESKTOP_APP_DISABLE_CRASH_REPORTS")

    var_path = root / TARGET_VARIABLES
    if var_path.exists():
        content, is_crlf = read_file(var_path)
        modified = False
        if "CMAKE_CXX_STANDARD 20" not in content:
            content, n = re.subn(
                r"set\(CMAKE_CXX_STANDARD_REQUIRED ON\)",
                "set(CMAKE_CXX_STANDARD_REQUIRED ON)\nset(CMAKE_CXX_STANDARD 20)",
                content,
                count=1,
            )
            if n > 0:
                modified = True
        old_fmt = 'set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "$<$<CONFIG:Debug,RelWithDebInfo>:Embedded>$<$<CONFIG:Release>:ProgramDatabase>")'
        new_fmt = (
            'if (DESKTOP_APP_DISABLE_CRASH_REPORTS)\n'
            '    set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "")\n'
            'else()\n'
            '    set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "$<$<CONFIG:Debug,RelWithDebInfo>:Embedded>$<$<CONFIG:Release>:ProgramDatabase>")\n'
            'endif()'
        )
        if old_fmt in content and "if (DESKTOP_APP_DISABLE_CRASH_REPORTS)" not in content:
            content = content.replace(old_fmt, new_fmt, 1)
            modified = True
        if modified and not dry:
            write_file(var_path, content, is_crlf)
        res.ok(fid, TARGET_VARIABLES, "enforced C++20 & disabled Release PDB generation when crash reports are OFF")


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolidated patch applicator for AyuGramDesktop CI")
    parser.add_argument("source", help="Path to AyuGramDesktop root source directory")
    parser.add_argument("--platform", choices=["windows", "linux", "macos", "all"], default="all",
                        help="Target OS platform (default: all)")
    parser.add_argument("--manifest-url",
                        default=os.environ.get("MANIFEST_URL", "https://raw.githubusercontent.com/RezoxP/AyuGramDesktop-builder/update-manifest/"),
                        help="Full URL prefix for update manifest")
    parser.add_argument("--no-optional", action="store_true", help="Skip optional optimization patches")
    parser.add_argument("--check", action="store_true", help="Dry run: inspect what would change without modifying files")
    parser.add_argument("extra_url", nargs="?", default=None, help="Optional positional manifest URL")

    args = parser.parse_args()
    root = Path(args.source).resolve()
    manifest_url = args.extra_url or args.manifest_url

    if not root.is_dir() or not (root / "Telegram").is_dir():
        print(f"::error::'{root}' is not a valid AyuGramDesktop checkout (missing Telegram/ dir)", file=sys.stderr)
        return 2

    res = PatchResult()
    print("=== Applying AyuGramDesktop Patches ===")
    print(f"Source Root:   {root}")
    print(f"Target OS:     {args.platform}")
    print(f"Manifest URL:  {manifest_url}")
    print(f"Dry Run:       {args.check}\n")

    # 1. Critical common patches
    patch_max_file_size(root, res, args.check)
    patch_update_url(root, manifest_url, res, args.check)
    patch_prefix_override(root, manifest_url, res, args.check)
    patch_manifest_url(root, res, args.check)
    patch_zip_updates(root, res, args.check)
    patch_updater_network_and_files(root, res, args.check)
    patch_platform_updaters(root, res, args.check)
    patch_git_mirrors(root, res, args.check)

    # 2. macOS specific patches
    if args.platform in ("macos", "all"):
        patch_mac_updater(root, res, args.check)
        if not args.no_optional:
            patch_qt_release_only(root, res, args.check)

    # 3. Windows patches
    if args.platform in ("windows", "all"):
        patch_prepare_tg_owt(root, res, args.check)
        patch_msys2_ucrt64(root, res, args.check)
        patch_cmake_windows(root, res, args.check)
        patch_tlottie_rust(root, res, args.check)
        if not args.no_optional:
            patch_qt_release_only(root, res, args.check)

    # 4. Linux patches
    if args.platform in ("linux", "all"):
        patch_tlottie_rust(root, res, args.check)

    res.report()

    if res.had_critical_failure:
        print("::error::CRITICAL PATCH FAILURE — upstream source changes broke critical updater anchors.", file=sys.stderr)
        return 1

    print("All required patches applied successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
