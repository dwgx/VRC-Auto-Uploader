"""
VRC Auto Uploader — Smart Archive Extractor
Extracts .unitypackage files from nested archives with intelligent filtering.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# Packages matching these patterns are shader/plugin dependencies, not model bodies
EXCLUDE_PATTERNS = [
    re.compile(r"poiyomi", re.IGNORECASE),
    re.compile(r"poi[_\s]?toon", re.IGNORECASE),
    re.compile(r"liltoon", re.IGNORECASE),
    re.compile(r"lilxyzw", re.IGNORECASE),
    re.compile(r"dynamic[_\s]?bone", re.IGNORECASE),
    re.compile(r"modular[_\s]?avatar", re.IGNORECASE),
    re.compile(r"gesture[_\s]?manager", re.IGNORECASE),
    re.compile(r"av3[_\s]?manager", re.IGNORECASE),
    re.compile(r"vrcsdk", re.IGNORECASE),
    re.compile(r"vrc[_\s]?sdk", re.IGNORECASE),
    re.compile(r"avatar[_\s]?3\.0", re.IGNORECASE),
]

ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}


def is_shader_or_plugin(filename: str) -> bool:
    """Check if a .unitypackage is likely a shader/plugin rather than a model."""
    stem = Path(filename).stem
    return any(p.search(stem) for p in EXCLUDE_PATTERNS)


def find_existing_packages(directory: str) -> list[str]:
    """Find all .unitypackage files already present in a directory tree."""
    results = []
    for root, _, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(".unitypackage"):
                results.append(os.path.join(root, f))
    return results


def find_archives(directory: str) -> list[str]:
    """Find all archive files in a directory tree."""
    results = []
    for root, _, files in os.walk(directory):
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in ARCHIVE_EXTENSIONS:
                results.append(os.path.join(root, f))
    return results


def extract_archive(archive_path: str, dest_dir: str) -> bool:
    """Extract an archive using Windows built-in tar or 7z if available."""
    os.makedirs(dest_dir, exist_ok=True)
    ext = Path(archive_path).suffix.lower()

    # Try tar first (built into Windows 10/11, supports zip and some others)
    if ext == ".zip":
        try:
            result = subprocess.run(
                ["tar", "-xf", archive_path, "-C", dest_dir],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Try PowerShell Expand-Archive for .zip
    if ext == ".zip":
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f'Expand-Archive -Path "{archive_path}" -DestinationPath "{dest_dir}" -Force'],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Try 7z for .rar and .7z (and as fallback for .zip)
    for sevenzip in ["7z", r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]:
        try:
            result = subprocess.run(
                [sevenzip, "x", archive_path, f"-o{dest_dir}", "-y", "-bso0"],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    # Last resort: tar for anything
    try:
        result = subprocess.run(
            ["tar", "-xf", archive_path, "-C", dest_dir],
            capture_output=True, text=True, timeout=600
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def pick_best_package(packages: list[str]) -> str | None:
    """From a list of .unitypackage files, pick the most likely model body.
    
    Strategy:
    1. Filter out known shader/plugin packages
    2. From remaining, pick the largest file (model bodies are usually the biggest)
    """
    # Filter out dependencies
    candidates = [p for p in packages if not is_shader_or_plugin(os.path.basename(p))]

    # If all were filtered out, fall back to all of them
    if not candidates:
        candidates = packages

    # Pick largest
    if not candidates:
        return None

    return max(candidates, key=lambda p: os.path.getsize(p))


def extract_model_dir(model_dir: str) -> dict:
    """Process a single model directory: find or extract .unitypackage files.
    
    Returns a result dict with:
        - name: directory basename
        - status: 'found' | 'extracted' | 'no_archive' | 'extract_failed' | 'no_package'
        - package: path to best .unitypackage (if found)
        - all_packages: list of all .unitypackage paths found
    """
    name = os.path.basename(model_dir)
    result = {"name": name, "status": "unknown", "package": None, "all_packages": []}

    # 1. Check for existing .unitypackage files
    existing = find_existing_packages(model_dir)
    if existing:
        best = pick_best_package(existing)
        # Move to model root if nested
        if best and os.path.dirname(best) != model_dir:
            dest = os.path.join(model_dir, os.path.basename(best))
            if not os.path.exists(dest):
                shutil.move(best, dest)
            best = dest
        result["status"] = "found"
        result["package"] = best
        result["all_packages"] = existing
        return result

    # 2. Look for archives
    archives = find_archives(model_dir)
    if not archives:
        result["status"] = "no_archive"
        return result

    # Sort by size descending, try largest first
    archives.sort(key=lambda p: os.path.getsize(p), reverse=True)

    for archive in archives:
        temp_dir = os.path.join(model_dir, "_temp_extract")
        try:
            if not extract_archive(archive, temp_dir):
                continue

            # Search extracted content for .unitypackage
            extracted = find_existing_packages(temp_dir)
            if extracted:
                best = pick_best_package(extracted)
                if best:
                    dest = os.path.join(model_dir, os.path.basename(best))
                    if os.path.exists(dest):
                        # Avoid overwrite, add suffix
                        stem = Path(dest).stem
                        dest = os.path.join(model_dir, f"{stem}_extracted.unitypackage")
                    shutil.move(best, dest)
                    result["status"] = "extracted"
                    result["package"] = dest
                    result["all_packages"] = [dest]
                    return result

            # Check for nested archives inside the extraction
            nested_archives = find_archives(temp_dir)
            for nested in nested_archives:
                nested_temp = os.path.join(temp_dir, "_nested")
                if extract_archive(nested, nested_temp):
                    nested_pkgs = find_existing_packages(nested_temp)
                    if nested_pkgs:
                        best = pick_best_package(nested_pkgs)
                        if best:
                            dest = os.path.join(model_dir, os.path.basename(best))
                            shutil.move(best, dest)
                            result["status"] = "extracted"
                            result["package"] = dest
                            result["all_packages"] = [dest]
                            return result
                try:
                    shutil.rmtree(nested_temp, ignore_errors=True)
                except Exception:
                    pass

        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    result["status"] = "extract_failed"
    return result


def scan_model_directory(base_dir: str) -> list[dict]:
    """Scan an entire model directory and process each subdirectory."""
    results = []
    if not os.path.isdir(base_dir):
        print(f"[extractor] Directory not found: {base_dir}")
        return results

    subdirs = sorted([
        d for d in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, d))
        and not d.startswith(".")
        and not d.startswith("_")
        and d not in ("TempVRCProject", "VRC-Auto-Uploader", "tools")
    ])

    total = len(subdirs)
    for i, dirname in enumerate(subdirs, 1):
        dirpath = os.path.join(base_dir, dirname)
        print(f"[{i}/{total}] Processing: {dirname}...", end=" ")
        result = extract_model_dir(dirpath)
        if result["status"] == "found":
            print(f"✓ found: {os.path.basename(result['package'])}")
        elif result["status"] == "extracted":
            print(f"✓ extracted: {os.path.basename(result['package'])}")
        elif result["status"] == "no_archive":
            print("⚠ no archives or packages found")
        elif result["status"] == "extract_failed":
            print("✗ extraction failed")
        else:
            print(f"? {result['status']}")
        results.append(result)

    return results
