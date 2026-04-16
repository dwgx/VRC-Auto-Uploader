"""
VRC Auto Uploader — Configuration & Environment Detection
Handles finding Unity installations, vrc-get, and persistent settings.
"""

import os
import sys
import json
import glob
import shutil
import platform
import subprocess
import urllib.request

CONFIG_FILE = "config.json"
VRC_GET_VERSION = "v1.9.1"
VRC_GET_URL = f"https://github.com/vrc-get/vrc-get/releases/download/{VRC_GET_VERSION}/x86_64-pc-windows-msvc-vrc-get.exe"

# Standard Unity Hub install paths on Windows
UNITY_SEARCH_PATHS = [
    r"C:\Program Files\Unity\Hub\Editor",
    r"D:\Program Files\Unity\Hub\Editor",
    r"E:\Program Files\Unity\Hub\Editor",
    os.path.expandvars(r"%LOCALAPPDATA%\Unity\Hub\Editor"),
]

# VRChat currently requires this specific Unity version
REQUIRED_UNITY_VERSION = "2022.3.22f1"


def find_unity_exe() -> str | None:
    """Search common paths for the required Unity editor version."""
    for base in UNITY_SEARCH_PATHS:
        candidate = os.path.join(base, REQUIRED_UNITY_VERSION, "Editor", "Unity.exe")
        if os.path.isfile(candidate):
            return candidate
    # Fallback: search all Unity versions installed
    for base in UNITY_SEARCH_PATHS:
        if os.path.isdir(base):
            for version_dir in os.listdir(base):
                if version_dir.startswith("2022.3"):
                    candidate = os.path.join(base, version_dir, "Editor", "Unity.exe")
                    if os.path.isfile(candidate):
                        return candidate
    return None


def find_vrc_get(tool_dir: str) -> str | None:
    """Find vrc-get.exe: check tool_dir, PATH, then common locations."""
    # 1. Check our own tools directory
    local = os.path.join(tool_dir, "vrc-get.exe")
    if os.path.isfile(local):
        return local

    # 2. Check PATH
    found = shutil.which("vrc-get")
    if found:
        return found

    # 3. Known locations from previous Gemini setup
    known = [r"D:\vrc-get\vrc-get.exe", r"C:\vrc-get\vrc-get.exe"]
    for p in known:
        if os.path.isfile(p):
            return p

    return None


def download_vrc_get(dest_dir: str) -> str:
    """Download the vrc-get binary from GitHub releases."""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "vrc-get.exe")
    print(f"[setup] Downloading vrc-get {VRC_GET_VERSION}...")
    urllib.request.urlretrieve(VRC_GET_URL, dest)
    # Verify it runs
    result = subprocess.run([dest, "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Downloaded vrc-get failed to execute: {result.stderr}")
    print(f"[setup] vrc-get {result.stdout.strip()} ready at {dest}")
    return dest


class Config:
    """Manages persistent configuration and runtime environment state."""

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)
        self.config_path = os.path.join(self.project_root, CONFIG_FILE)
        self.tools_dir = os.path.join(self.project_root, "tools")
        self._data = {}
        self.load()

    def load(self):
        if os.path.isfile(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def save(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    @property
    def unity_exe(self) -> str | None:
        return self._data.get("unity_exe")

    @unity_exe.setter
    def unity_exe(self, value):
        self._data["unity_exe"] = value

    @property
    def vrc_get_exe(self) -> str | None:
        return self._data.get("vrc_get_exe")

    @vrc_get_exe.setter
    def vrc_get_exe(self, value):
        self._data["vrc_get_exe"] = value

    @property
    def temp_project_dir(self) -> str:
        return self._data.get("temp_project_dir",
                              os.path.join(self.project_root, "TempVRCProject"))

    @temp_project_dir.setter
    def temp_project_dir(self, value):
        self._data["temp_project_dir"] = value

    def detect_environment(self) -> bool:
        """Auto-detect Unity and vrc-get. Returns True if all found."""
        ok = True

        # Unity
        if not self.unity_exe or not os.path.isfile(self.unity_exe):
            found = find_unity_exe()
            if found:
                self.unity_exe = found
                print(f"[setup] Found Unity: {found}")
            else:
                print(f"[setup] ERROR: Unity {REQUIRED_UNITY_VERSION} not found!")
                print(f"        Install it via Unity Hub or set 'unity_exe' in {CONFIG_FILE}")
                ok = False
        else:
            print(f"[setup] Unity: {self.unity_exe}")

        # vrc-get
        if not self.vrc_get_exe or not os.path.isfile(self.vrc_get_exe):
            found = find_vrc_get(self.tools_dir)
            if found:
                self.vrc_get_exe = found
                print(f"[setup] Found vrc-get: {found}")
            else:
                try:
                    self.vrc_get_exe = download_vrc_get(self.tools_dir)
                except Exception as e:
                    print(f"[setup] ERROR: Could not get vrc-get: {e}")
                    ok = False
        else:
            print(f"[setup] vrc-get: {self.vrc_get_exe}")

        self.save()
        return ok

    def validate(self) -> bool:
        """Check that all required tools exist. Auto-heals by re-running detect_environment()."""
        needs_unity = not self.unity_exe or not os.path.isfile(self.unity_exe)
        needs_vrcget = not self.vrc_get_exe or not os.path.isfile(self.vrc_get_exe)

        if needs_unity or needs_vrcget:
            print("[*] Some tools not found — running auto-detection...")
            self.detect_environment()

        errors = []
        if not self.unity_exe or not os.path.isfile(self.unity_exe):
            errors.append(f"Unity {REQUIRED_UNITY_VERSION} not found. Install via Unity Hub.")
        if not self.vrc_get_exe or not os.path.isfile(self.vrc_get_exe):
            errors.append("vrc-get could not be found or downloaded. Check your internet connection.")
        for e in errors:
            print(f"[!] {e}")
        return len(errors) == 0
