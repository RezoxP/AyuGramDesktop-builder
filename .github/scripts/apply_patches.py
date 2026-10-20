#!/usr/bin/env python3
"""
apply_patches.py — Consolidated, robust source patcher for AyuGramDesktop CI.

Applies:
1. update-url       (critical): Rewrites AyuGram auto-update manifest URL to this repository.
2. prefix-override  (critical): Neutralizes legacy ayugram.one prefix in local storage.
3. manifest-url     (critical): Allows absolute HTTP/HTTPS links in update manifest.
4. zip-updates      (critical): Enables plain .zip update extraction via minizip, anti-bloat stale
                                file purge, zip-slip protection, version/ready markers, and Unix permissions.
5. mac-updater      (macOS):    Dynamically resolves AyuGram.app bundle in checkReadyUpdate instead of Telegram.app.
6. tg-owt-win       (Windows):  Fixes upstream Windows cmd line continuation bug (\\ -> ^) in tg_owt stage.
7. msys2-ucrt64     (Windows):  Migrates MSYS2 to UCRT64 toolchain and updates installer URL to 2026-09-27.
8. qt-release-only  (Windows):  Builds Qt in release-only mode, halving Windows library build time.
9. tlottie-rust     (Linux):    Resolves tlottie / tdesktop_rust consolidated library in Docker centos_env.
10. cmake-options   (Windows):  Disables debug scheme and enforces C++20.
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

TARGET_UPDATER = "Telegram/SourceFiles/core/update_checker.cpp"
TARGET_LOCALSTORAGE = "Telegram/SourceFiles/storage/localstorage.cpp"
TARGET_PREPARE = "Telegram/build/prepare/prepare.py"
TARGET_TLOTTIE = "cmake/external/tlottie/CMakeLists.txt"
TARGET_OPTIONS_WIN = "cmake/options_win.cmake"
TARGET_VARIABLES = "cmake/variables.cmake"

SENTINEL_INCLUDE = "#include <minizip/unzip.h>"
SENTINEL_MARKER = "RezoxP patch: plain-zip update support"

FUNC_SIG_RE = re.compile(
    r"bool\s+UnpackUpdate\s*\(\s*const\s+QString\s*&\s*filepath\s*\)\s*\{\s*\r?\n\s*#ifndef\s+TDESKTOP_DISABLE_AUTOUPDATE"
)

PATCH_BLOCK_TEMPLATE = '''bool UnpackUpdate(const QString &filepath) {
#ifndef TDESKTOP_DISABLE_AUTOUPDATE
\t// === RezoxP patch: plain-zip update support ===
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
\t\t\t\t\t\tif (info.absoluteFilePath() != filepath) {
\t\t\t\t\t\t\tQFile::remove(info.absoluteFilePath());
\t\t\t\t\t\t}
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\tbase::Platform::DeleteDirectory(tempDirPath);
\t\t\t\tQDir().mkpath(tempDirPath);

\t\t\t\tauto cleanupOnFailure = [&]() {
\t\t\t\t\tQFile::remove(filepath);
\t\t\t\t\tbase::Platform::DeleteDirectory(tempDirPath);
\t\t\t\t};

\t\t\t\t// Extract the zip into tempDirPath via minizip.
\t\t\t\tunzFile uz = unzOpen(QFile::encodeName(filepath).constData());
\t\t\t\tif (!uz) {
\t\t\t\t\tLOG(("Update Error: plain-zip: unzOpen failed for '%1'").arg(filepath));
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
\t\t\t\t\tchar filenameBuf[4096];
\t\t\t\t\tunz_file_info info;
\t\t\t\t\tif (unzGetCurrentFileInfo(
\t\t\t\t\t\t\tuz, &info,
\t\t\t\t\t\t\tfilenameBuf, sizeof(filenameBuf),
\t\t\t\t\t\t\tnullptr, 0,
\t\t\t\t\t\t\tnullptr, 0) != UNZ_OK) {
\t\t\t\t\t\tLOG(("Update Error: plain-zip: unzGetCurrentFileInfo failed"));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\tQString relName = QString::fromUtf8(filenameBuf);
\t\t\t\t\t// Security & anti-bloat:
\t\t\t\t\t// 1. Guard against path traversal (Zip Slip)
\t\t\t\t\tif (relName.startsWith('/') || relName.startsWith('\\\\')
\t\t\t\t\t\t|| relName.contains(u"../"_q) || relName.contains(u"..\\\\"_q)) {
\t\t\t\t\t\tLOG(("Update Error: plain-zip: insecure path in archive: '%1'").arg(relName));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\t// 2. Skip directory entries, OS metadata, and Mac archive junk
\t\t\t\t\tif (relName.endsWith('/') || relName.startsWith(u"__MACOSX/"_q) || relName.endsWith(u".DS_Store"_q)) {
\t\t\t\t\t\tif (unzGoToNextFile(uz) != UNZ_OK) break;
\t\t\t\t\t\tcontinue;
\t\t\t\t\t}
\t\t\t\t\tconst QString outPath = tempDirPath + '/' + relName;
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
\t\t\t\t\tQFile out(outPath);
\t\t\t\t\tif (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
\t\t\t\t\t\tunzCloseCurrentFile(uz);
\t\t\t\t\t\tLOG(("Update Error: plain-zip: cannot open '%1' for writing").arg(outPath));
\t\t\t\t\t\textractSuccess = false;
\t\t\t\t\t\tbreak;
\t\t\t\t\t}
\t\t\t\t\tchar buf[16384];
\t\t\t\t\tint r;
\t\t\t\t\tbool writeOk = true;
\t\t\t\t\twhile ((r = unzReadCurrentFile(uz, buf, sizeof(buf))) > 0) {
\t\t\t\t\t\tif (out.write(buf, r) != r) {
\t\t\t\t\t\t\tLOG(("Update Error: plain-zip: write failed for '%1'").arg(outPath));
\t\t\t\t\t\t\twriteOk = false;
\t\t\t\t\t\t\tbreak;
\t\t\t\t\t}
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
\t\t\t\t\tif (((info.external_fa >> 16) & 0100)
\t\t\t\t\t\t|| relName == u"AyuGram"_q
\t\t\t\t\t\t|| relName == u"Telegram"_q
\t\t\t\t\t\t|| relName == u"Updater"_q
\t\t\t\t\t\t|| relName.contains(u"MacOS/AyuGram"_q)
\t\t\t\t\t\t|| relName.contains(u"MacOS/Telegram"_q)
\t\t\t\t\t\t|| relName.contains(u"Contents/Frameworks/Updater"_q)
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

\t\t\t\t// Write tdata/version sentinel
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

\t\t\t\tLOG(("Update Info: plain-zip update installed cleanly without storage bloat"));
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


def patch_update_url(root: Path, manifest_url: str, res: PatchResult, dry: bool):
    fid = "update-url"
    path = root / TARGET_LOCALSTORAGE
    if not path.exists():
        res.fail(fid, TARGET_LOCALSTORAGE, "file not found")
        return

    content, is_crlf = read_file(path)
    if f'AutoupdatePrefix("{manifest_url}")' in content:
        res.ok(fid, TARGET_LOCALSTORAGE, "already patched with manifest URL")
        return

    new_content, n = re.subn(r"https://update\.ayugram\.one/", manifest_url, content)
    if n == 0:
        res.fail(fid, TARGET_LOCALSTORAGE, "no 'https://update.ayugram.one/' anchor found")
        return

    if not dry:
        write_file(path, new_content, is_crlf)
    res.ok(fid, TARGET_LOCALSTORAGE, f"rewrote {n} URL site(s) -> {manifest_url}")


def patch_prefix_override(root: Path, res: PatchResult, dry: bool):
    fid = "prefix-override"
    path = root / TARGET_LOCALSTORAGE
    if not path.exists():
        res.fail(fid, TARGET_LOCALSTORAGE, "file not found")
        return

    content, is_crlf = read_file(path)
    sentinel = '!value.contains("ayugram.one")'
    if sentinel in content:
        res.ok(fid, TARGET_LOCALSTORAGE, "already ignores cached ayugram.one prefix")
        return

    old = "if (!value.isEmpty()) {"
    new = 'if (!value.isEmpty() && !value.contains("ayugram.one")) {'
    if old not in content:
        res.warn(fid, TARGET_LOCALSTORAGE, "could not find 'if (!value.isEmpty()) {' anchor")
        return

    if not dry:
        content = content.replace(old, new, 1)
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_LOCALSTORAGE, "cached ayugram.one prefix neutralized")


def patch_manifest_url(root: Path, res: PatchResult, dry: bool):
    fid = "manifest-url"
    path = root / TARGET_UPDATER
    if not path.exists():
        res.fail(fid, TARGET_UPDATER, "file not found")
        return

    content, is_crlf = read_file(path)
    if 'bestLink.startsWith(QLatin1String("http"))' in content:
        res.ok(fid, TARGET_UPDATER, "already accepts absolute URLs")
        return

    pattern = re.compile(r"Local::readAutoupdatePrefix\(\)\s*\+\s*bestLink\)")
    replacement = 'bestLink.startsWith(QLatin1String("http")) ? bestLink : (Local::readAutoupdatePrefix() + bestLink))'
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
    patch_block = PATCH_BLOCK_TEMPLATE.replace("\r\n", "\n").replace("\n", newline)

    # 1. Ensure minizip include
    if SENTINEL_INCLUDE not in content:
        lines = content.splitlines()
        insert_at = None
        for i, line in enumerate(lines):
            if line.strip().startswith("#include"):
                insert_at = i + 1
                break
        if insert_at is None:
            res.fail(fid, TARGET_UPDATER, "no #include line to anchor minizip")
            return
        lines.insert(insert_at, SENTINEL_INCLUDE)
        content = newline.join(lines) + newline

    # 2. Insert plain zip handler
    if SENTINEL_MARKER not in content:
        match = FUNC_SIG_RE.search(content)
        if not match:
            res.fail(fid, TARGET_UPDATER, f"UnpackUpdate() signature not found with regex: {FUNC_SIG_RE.pattern}")
            return
        content = content[:match.start()] + patch_block + content[match.end():]

    if not dry:
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_UPDATER, "plain .zip anti-bloat update extraction installed")


def patch_mac_updater(root: Path, res: PatchResult, dry: bool):
    fid = "mac-updater-path"
    path = root / TARGET_UPDATER
    if not path.exists():
        res.warn(fid, TARGET_UPDATER, "update_checker.cpp not found")
        return

    content, is_crlf = read_file(path)
    if "u\"tupdates/temp/\"_q + appBundle" in content or "cExeName().endsWith(u\".app\"_q)" in content:
        res.ok(fid, TARGET_UPDATER, "already patched for dynamic app bundle updater path")
        return

    old = 'QString curUpdater = (cExeDir() + cExeName() + u"/Contents/Frameworks/Updater"_q);\n\tQFileInfo updater(cWorkingDir() + u"tupdates/temp/Telegram.app/Contents/Frameworks/Updater"_q);'
    new = (
        'const auto appBundle = cExeName().endsWith(u".app"_q) ? cExeName() : (cExeName() + u".app"_q);\n'
        '\tQString curUpdater = (cExeDir() + appBundle + u"/Contents/Frameworks/Updater"_q);\n'
        '\tQFileInfo updater(cWorkingDir() + u"tupdates/temp/"_q + appBundle + u"/Contents/Frameworks/Updater"_q);\n'
        '\tif (!updater.exists()) {\n'
        '\t\tupdater.setFile(cWorkingDir() + u"tupdates/temp/AyuGram.app/Contents/Frameworks/Updater"_q);\n'
        '\t}'
    )

    if old not in content:
        old_crlf = old.replace('\n', '\r\n')
        new_crlf = new.replace('\n', '\r\n')
        if old_crlf in content:
            if not dry:
                content = content.replace(old_crlf, new_crlf, 1)
                write_file(path, content, is_crlf)
            res.ok(fid, TARGET_UPDATER, "patched macOS updater to dynamically resolve AyuGram.app bundle")
            return
        res.warn(fid, TARGET_UPDATER, "anchor for macOS Telegram.app updater path not found")
        return

    if not dry:
        content = content.replace(old, new, 1)
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_UPDATER, "patched macOS updater to dynamically resolve AyuGram.app bundle")


def patch_prepare_dav1d_mirror(root: Path, res: PatchResult, dry: bool):
    fid = "dav1d-mirror"
    path = root / TARGET_PREPARE
    if not path.exists():
        res.warn(fid, TARGET_PREPARE, "prepare.py not found")
        return

    content, is_crlf = read_file(path)
    old = "https://code.videolan.org/videolan/dav1d.git"
    new = "https://github.com/videolan/dav1d.git"

    if new in content:
        res.ok(fid, TARGET_PREPARE, "already using GitHub mirror for dav1d")
        return

    if old not in content:
        res.warn(fid, TARGET_PREPARE, f"anchor '{old}' not found")
        return

    if not dry:
        content = content.replace(old, new)
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_PREPARE, "mirrored dav1d to GitHub (fixes code.videolan.org DNS/uptime failures)")


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


def patch_msys2_ucrt64(root: Path, res: PatchResult, dry: bool):
    fid = "msys2-ucrt64"
    path = root / TARGET_PREPARE
    if not path.exists():
        res.warn(fid, TARGET_PREPARE, "prepare.py not found")
        return

    content, is_crlf = read_file(path)
    modified = False

    old_url = "https://github.com/msys2/msys2-installer/releases/download/2025-08-30/msys2-base-x86_64-20250830.sfx.exe"
    new_url = "https://github.com/msys2/msys2-installer/releases/download/2026-09-27/msys2-base-x86_64-20260927.sfx.exe"
    if old_url in content:
        content = content.replace(old_url, new_url)
        modified = True

    if "'ThirdParty\\\\msys64\\\\mingw64\\\\bin'" in content:
        content = content.replace("'ThirdParty\\\\msys64\\\\mingw64\\\\bin'", "'ThirdParty\\\\msys64\\\\ucrt64\\\\bin'")
        modified = True

    for pkg in ["diffutils", "gperf", "nasm", "perl", "pkgconf"]:
        old_pkg = f"mingw-w64-x86_64-{pkg}"
        new_pkg = f"mingw-w64-ucrt-x86_64-{pkg}"
        if old_pkg in content:
            content = content.replace(old_pkg, new_pkg)
            modified = True

    if "if build_debug:" in content:
        content = content.replace("if build_debug:", "if False:")
        modified = True

    if modified:
        if not dry:
            write_file(path, content, is_crlf)
        res.ok(fid, TARGET_PREPARE, "migrated to MSYS2 UCRT64 toolchain & 2026 installer")
    else:
        res.ok(fid, TARGET_PREPARE, "already updated to MSYS2 UCRT64")


def patch_qt_release_only(root: Path, res: PatchResult, dry: bool):
    fid = "qt-release-only"
    path = root / TARGET_PREPARE
    if not path.exists():
        res.warn(fid, TARGET_PREPARE, "prepare.py not found")
        return

    content, is_crlf = read_file(path)
    old = "SET CONFIGURATIONS=-debug-and-release"
    new = "SET CONFIGURATIONS=-release"

    if new in content and old not in content:
        res.ok(fid, TARGET_PREPARE, "already configured Qt release-only")
        return

    if old not in content:
        res.warn(fid, TARGET_PREPARE, f"anchor '{old}' not found")
        return

    if not dry:
        content = content.replace(old, new)
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_PREPARE, "configured Qt release-only (halves Qt compilation time)")


def patch_tlottie_rust(root: Path, res: PatchResult, dry: bool):
    fid = "tlottie-rust"
    path = root / TARGET_TLOTTIE
    if not path.exists():
        res.warn(fid, TARGET_TLOTTIE, "tlottie CMakeLists.txt not found")
        return

    content, is_crlf = read_file(path)
    old = "find_library(DESKTOP_APP_TLOTTIE_LIBRARY tlottie REQUIRED)"
    new = "find_library(DESKTOP_APP_TLOTTIE_LIBRARY NAMES tlottie tdesktop_rust REQUIRED)"

    if new in content:
        res.ok(fid, TARGET_TLOTTIE, "already supports tdesktop_rust library")
        return

    if old not in content:
        res.warn(fid, TARGET_TLOTTIE, "find_library tlottie anchor not found")
        return

    content = content.replace(old, new)
    if not dry:
        write_file(path, content, is_crlf)
    res.ok(fid, TARGET_TLOTTIE, "enabled tdesktop_rust fallback for tlottie")


def patch_cmake_windows(root: Path, res: PatchResult, dry: bool):
    fid = "cmake-windows"
    opt_path = root / TARGET_OPTIONS_WIN
    if opt_path.exists():
        content, is_crlf = read_file(opt_path)
        content = content.replace("init_target(Telegram)", "init_target(Telegram disable_debug_scheme)")
        content = content.replace("enable_warnings(Telegram)", "")
        if not dry:
            write_file(opt_path, content, is_crlf)
        res.ok(fid, TARGET_OPTIONS_WIN, "applied disable_debug_scheme & disabled enable_warnings")

    var_path = root / TARGET_VARIABLES
    if var_path.exists():
        content, is_crlf = read_file(var_path)
        if "CMAKE_CXX_STANDARD 20" not in content:
            new_content, n = re.subn(
                r"set\(CMAKE_CXX_STANDARD_REQUIRED ON\)",
                "set(CMAKE_CXX_STANDARD_REQUIRED ON)\nset(CMAKE_CXX_STANDARD 20)",
                content,
                count=1
            )
            if n > 0 and not dry:
                write_file(var_path, new_content, is_crlf)
            res.ok(fid, TARGET_VARIABLES, "enforced C++20 standard")


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

    args = parser.parse_args()
    root = Path(args.source).resolve()

    if not root.is_dir() or not (root / "Telegram").is_dir():
        print(f"::error::'{root}' is not a valid AyuGramDesktop checkout (missing Telegram/ dir)", file=sys.stderr)
        return 2

    res = PatchResult()
    print(f"=== Applying AyuGramDesktop Patches ===")
    print(f"Source Root:   {root}")
    print(f"Target OS:     {args.platform}")
    print(f"Manifest URL:  {args.manifest_url}")
    print(f"Dry Run:       {args.check}\n")

    # 1. Critical common patches
    patch_update_url(root, args.manifest_url, res, args.check)
    patch_prefix_override(root, res, args.check)
    patch_manifest_url(root, res, args.check)
    patch_zip_updates(root, res, args.check)
    patch_prepare_dav1d_mirror(root, res, args.check)

    # 2. macOS specific patches
    if args.platform in ("macos", "all"):
        patch_mac_updater(root, res, args.check)

    # 3. Windows patches
    if args.platform in ("windows", "all"):
        patch_prepare_tg_owt(root, res, args.check)
        patch_msys2_ucrt64(root, res, args.check)
        patch_cmake_windows(root, res, args.check)
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
