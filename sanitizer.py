"""
VRC Auto Uploader — UnityPackage Sanitizer
Physically removes C# scripts, DLLs, and ASMDEFs from UnityPackages to prevent Safe Mode compilation hangs.
"""

import os
import sys
import tarfile
import tempfile
import shutil

BAD_EXTENSIONS = {".cs", ".dll", ".asmdef", ".js"}

def is_malicious_path(path_str: str) -> bool:
    """Check if the extracted pathname belongs to a banned filetype."""
    path_str = path_str.strip().lower()
    for ext in BAD_EXTENSIONS:
        if path_str.endswith(ext):
            return True
    return False

def sanitize_package(src_path: str, dst_path: str) -> int:
    """
    Strips scripts from a UnityPackage to prevent Unity Safe Mode errors.
    Returns the number of scripts removed.
    """
    skip_guids = set()

    # Pass 1: Identify all GUIDs that contain banned file extensions
    try:
        with tarfile.open(src_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("pathname"):
                    # Extract just this file into memory to read the intended path
                    f = tar.extractfile(member)
                    if f is not None:
                        try:
                            # Unity paths are utf-8 or ascii
                            intended_path = f.read().decode('utf-8', errors='ignore').strip()
                            if is_malicious_path(intended_path):
                                guid = member.name.split("/")[0]
                                skip_guids.add(guid)
                        except Exception as e:
                            print(f"[sanitizer] Warning: Could not read pathname {member.name}: {e}")
    except tarfile.ReadError:
        print(f"[sanitizer] FATAL: {src_path} is not a valid tar.gz package.")
        shutil.copy2(src_path, dst_path)
        return 0

    if not skip_guids:
        # Optimization: If it's clean, just copy the file
        shutil.copy2(src_path, dst_path)
        return 0

    # Pass 2: Repackage everything EXCEPT the banned GUIDs
    print(f"[sanitizer] Found {len(skip_guids)} dangerous scripts. Stripping from package...")
    with tarfile.open(src_path, "r:gz") as tar_in:
        with tarfile.open(dst_path, "w:gz") as tar_out:
            for member in tar_in.getmembers():
                guid = member.name.split("/")[0]
                if guid not in skip_guids:
                    if member.isreg():
                        f = tar_in.extractfile(member)
                        tar_out.addfile(member, f)
                    else:
                        tar_out.addfile(member)

    return len(skip_guids)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python sanitizer.py <input.unitypackage> <output.unitypackage>")
        sys.exit(1)
    
    removed = sanitize_package(sys.argv[1], sys.argv[2])
    print(f"Removed {removed} hazardous files.")
