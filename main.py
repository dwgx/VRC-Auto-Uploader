"""
VRC Auto Uploader — Main Orchestrator
Manages the full pipeline: extract → provision → inject → launch Unity → monitor.

Usage:
    python main.py setup                          # First-time environment detection
    python main.py upload --package FILE          # Upload a single .unitypackage
    python main.py batch  --dir DIR               # Extract & upload all models in DIR
    python main.py extract --dir DIR              # Extract only (no upload)
"""

import os
import sys
import io
import time
import json
import argparse
import subprocess
import shutil
import threading
import signal
from pathlib import Path

# Fix Unicode output on Chinese Windows (GBK console)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from config import Config
from extractor import scan_model_directory, extract_model_dir


# ─── Constants ───────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UNITY_SCRIPTS_DIR = os.path.join(SCRIPT_DIR, "UnityScripts")

# Required VPM packages to install in every temp project
VPM_PACKAGES = [
    ("com.vrchat.avatars", True),       # Core SDK — mandatory
    ("jp.lilxyzw.liltoon", True),       # lilToon shader — most JP models need this
    ("nadena.dev.modular-avatar", False), # Modular Avatar — nice to have
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: str | None = None, check: bool = True,
        timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a subprocess with nice logging."""
    cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    print(f"  $ {cmd_str}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                            timeout=timeout)
    if check and result.returncode != 0:
        print(f"  [!] Command failed (exit {result.returncode})")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[:10]:
                print(f"      {line}")
        raise RuntimeError(f"Command failed: {cmd[0]}")
    return result


def tail_unity_log(log_path: str, stop_event: threading.Event):
    """Tail the Unity Editor.log, printing [AutoUploader] lines in real-time."""
    # Wait for log file to appear
    for _ in range(120):
        if os.path.isfile(log_path) or stop_event.is_set():
            break
        time.sleep(1)

    if not os.path.isfile(log_path):
        return

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            # Start from beginning to catch early messages
            while not stop_event.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.3)
                    continue
                line = line.rstrip()
                if "[AutoUploader]" in line:
                    # Color coding
                    if "ERROR" in line or "FAIL" in line:
                        print(f"  \033[91m{line}\033[0m")
                    elif "SUCCESS" in line:
                        print(f"  \033[92m{line}\033[0m")
                    elif "WARNING" in line or "WARN" in line:
                        print(f"  \033[93m{line}\033[0m")
                    else:
                        print(f"  \033[96m{line}\033[0m")
    except Exception:
        pass


# ─── Project Provisioning ────────────────────────────────────────────────────

def provision_project(cfg: Config) -> str:
    """Create a fresh Unity project with VRChat SDK + dependencies installed.
    
    Returns the path to the project directory.
    """
    project_path = cfg.temp_project_dir
    
    print("\n╔══════════════════════════════════════════╗")
    print("║   Phase 1: Environment Provisioning      ║")
    print("╚══════════════════════════════════════════╝\n")

    # Clean up previous project
    if os.path.isdir(project_path):
        print("[1/3] Cleaning old temp project...")
        shutil.rmtree(project_path, ignore_errors=True)
        time.sleep(1)

    # Create empty Unity project
    print("[1/3] Creating empty Unity project (this takes ~1 minute)...")
    run([cfg.unity_exe, "-createProject", project_path,
         "-batchmode", "-nographics", "-quit"], timeout=300)

    # Install VPM packages
    print("[2/3] Installing VRChat SDK & dependencies via vrc-get...")
    for pkg_id, required in VPM_PACKAGES:
        try:
            run([cfg.vrc_get_exe, "install", "-p", project_path, pkg_id, "-y"],
                timeout=120)
            print(f"       ✓ {pkg_id}")
        except RuntimeError:
            if required:
                raise
            print(f"       ⚠ {pkg_id} (optional, skipped)")

    # Inject our C# scripts
    print("[3/3] Injecting AutoUploader scripts...")
    editor_dir = os.path.join(project_path, "Assets", "Editor", "VRCAutoUploader")
    os.makedirs(editor_dir, exist_ok=True)

    for cs_file in Path(UNITY_SCRIPTS_DIR).glob("*.cs"):
        dest = os.path.join(editor_dir, cs_file.name)
        shutil.copy2(str(cs_file), dest)
        print(f"       → {cs_file.name}")

    print(f"\n[✓] Project ready at: {project_path}")
    return project_path


# ─── Upload Execution ────────────────────────────────────────────────────────

def prepare_task_file(project_path: str, packages: list[dict]):
    """Write the upload task list as JSON for the C# script to consume."""
    tasks = []
    for pkg in packages:
        if pkg.get("package"):
            tasks.append({
                "name": pkg["name"],
                "packagePath": os.path.abspath(pkg["package"]),
                "avatarName": pkg["name"],
            })

    task_file = os.path.join(project_path, "upload_tasks.json")
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump({"tasks": tasks}, f, indent=2, ensure_ascii=False)

    print(f"[✓] Task file written: {len(tasks)} avatar(s) queued")
    return task_file


def launch_unity_upload(cfg: Config, project_path: str) -> bool:
    """Launch Unity in GUI mode (minimized) to execute the upload.
    
    IMPORTANT: We do NOT use -batchmode or -nographics because the VRChat SDK
    requires the Editor GUI to be initialized for VRCSdkControlPanel to work.
    We use -executeMethod to trigger our script on startup.
    """
    print("\n╔══════════════════════════════════════════╗")
    print("║   Phase 3: Unity Upload Execution        ║")
    print("╚══════════════════════════════════════════╝\n")

    # Determine log path
    log_path = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Unity", "Editor", "Editor.log"
    )
    # Also write to a project-local log for our scripts
    local_log = os.path.join(project_path, "autouploader.log")

    print(f"[*] Launching Unity (GUI mode, may take 2-5 minutes to open)...")
    print(f"[*] Monitoring log: {log_path}")
    print(f"[*] ────────────────────────────────────────")
    print(f"[*] IMPORTANT: If this is your first time, Unity will open the")
    print(f"[*] VRChat SDK Control Panel. You MUST log in manually once.")
    print(f"[*] After login, the upload will proceed automatically.")
    print(f"[*] ────────────────────────────────────────\n")

    # Start log tail thread
    stop_event = threading.Event()
    tail_thread = threading.Thread(
        target=tail_unity_log,
        args=(log_path, stop_event),
        daemon=True
    )
    tail_thread.start()

    # Launch Unity — NOT in batchmode! SDK needs the GUI.
    unity_cmd = [
        cfg.unity_exe,
        "-projectPath", project_path,
        "-executeMethod", "VRCAutoUploader.AutoUploader.Execute",
    ]

    try:
        process = subprocess.Popen(unity_cmd)
        print(f"[*] Unity PID: {process.pid}")
        print(f"[*] Waiting for Unity to finish...\n")
        process.wait()
    except KeyboardInterrupt:
        print("\n[!] Interrupted — terminating Unity...")
        process.terminate()
        process.wait(timeout=30)
    finally:
        stop_event.set()
        tail_thread.join(timeout=5)

    # Check results
    result_file = os.path.join(project_path, "upload_results.json")
    if os.path.isfile(result_file):
        with open(result_file, "r", encoding="utf-8") as f:
            results = json.load(f)
        
        print("\n╔══════════════════════════════════════════╗")
        print("║           Upload Results                  ║")
        print("╚══════════════════════════════════════════╝\n")
        
        success = 0
        failed = 0
        for r in results.get("results", []):
            status = r.get("status", "unknown")
            name = r.get("name", "?")
            if status == "success":
                print(f"  ✓ {name}")
                success += 1
            else:
                print(f"  ✗ {name}: {r.get('error', 'unknown error')}")
                failed += 1
        
        print(f"\n  Total: {success} succeeded, {failed} failed")
        return failed == 0
    else:
        print("\n[!] No result file found. Check Unity console for errors.")
        return False


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_setup(args):
    """First-time setup: detect environment."""
    cfg = Config(SCRIPT_DIR)
    print("\n╔══════════════════════════════════════════╗")
    print("║   VRC Auto Uploader — Setup              ║")
    print("╚══════════════════════════════════════════╝\n")

    ok = cfg.detect_environment()
    if ok:
        print("\n[✓] All prerequisites found! You're ready to go.")
        print("    Use 'python main.py upload --package FILE' to upload a single avatar")
        print("    Use 'python main.py batch --dir DIR' to batch process a directory")
    else:
        print("\n[!] Some prerequisites are missing. Fix the errors above and re-run setup.")
    return 0 if ok else 1


def cmd_extract(args):
    """Extract .unitypackage files from a model directory."""
    target_dir = os.path.abspath(args.dir)
    print(f"\n[*] Scanning directory: {target_dir}\n")
    results = scan_model_directory(target_dir)

    found = sum(1 for r in results if r["package"])
    total = len(results)
    print(f"\n[✓] Extraction complete: {found}/{total} models have .unitypackage files")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"    Results saved to: {args.output}")

    return 0


def cmd_upload(args):
    """Upload a single .unitypackage file."""
    cfg = Config(SCRIPT_DIR)
    if not cfg.validate():
        return 1

    package_path = os.path.abspath(args.package)
    if not os.path.isfile(package_path):
        print(f"[!] File not found: {package_path}")
        return 1

    name = Path(package_path).stem

    # Provision project
    project_path = provision_project(cfg)

    # Prepare task
    print("\n╔══════════════════════════════════════════╗")
    print("║   Phase 2: Preparing Upload Task         ║")
    print("╚══════════════════════════════════════════╝\n")

    prepare_task_file(project_path, [{"name": name, "package": package_path}])

    # Launch Unity
    success = launch_unity_upload(cfg, project_path)

    # Cleanup
    if success and not args.keep_project:
        print("[*] Cleaning up temp project...")
        shutil.rmtree(project_path, ignore_errors=True)

    return 0 if success else 1


def cmd_batch(args):
    """Batch process: extract all archives in a directory, then upload all found packages."""
    cfg = Config(SCRIPT_DIR)
    if not cfg.validate():
        return 1

    target_dir = os.path.abspath(args.dir)

    # Phase 0: Extract
    print(f"\n[*] Scanning and extracting from: {target_dir}\n")
    results = scan_model_directory(target_dir)

    packages = [r for r in results if r["package"]]
    if not packages:
        print("[!] No .unitypackage files found. Nothing to upload.")
        return 1

    print(f"\n[✓] Found {len(packages)} uploadable models")

    if args.extract_only:
        print("[*] --extract-only specified, skipping upload.")
        return 0

    # Confirm with user
    print("\nModels to upload:")
    for i, pkg in enumerate(packages, 1):
        print(f"  {i}. {pkg['name']} → {os.path.basename(pkg['package'])}")

    if not args.yes:
        resp = input(f"\nProceed with uploading {len(packages)} avatar(s)? [y/N] ").strip()
        if resp.lower() != "y":
            print("[*] Cancelled.")
            return 0

    # Provision
    project_path = provision_project(cfg)

    # Prepare tasks
    print("\n╔══════════════════════════════════════════╗")
    print("║   Phase 2: Preparing Upload Tasks        ║")
    print("╚══════════════════════════════════════════╝\n")

    prepare_task_file(project_path, packages)

    # Launch
    success = launch_unity_upload(cfg, project_path)

    # Cleanup
    if success and not args.keep_project:
        print("[*] Cleaning up temp project...")
        shutil.rmtree(project_path, ignore_errors=True)

    return 0 if success else 1


# ─── CLI Entry Point ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="VRChat Avatar Auto Uploader — Batch upload .unitypackage avatars",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py setup                                    # First-time setup
  python main.py upload --package "D:\\Model\\Azuki\\Azuki.unitypackage"
  python main.py batch --dir "D:\\Model"                   # Upload all models in dir
  python main.py extract --dir "D:\\Model"                 # Extract only, no upload
        """
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # setup
    sub.add_parser("setup", help="Detect and configure environment")

    # upload
    p_upload = sub.add_parser("upload", help="Upload a single .unitypackage")
    p_upload.add_argument("--package", required=True, help="Path to .unitypackage file")
    p_upload.add_argument("--keep-project", action="store_true",
                          help="Don't delete temp Unity project after upload")

    # batch
    p_batch = sub.add_parser("batch", help="Batch extract and upload from a directory")
    p_batch.add_argument("--dir", required=True, help="Directory containing model folders")
    p_batch.add_argument("--extract-only", action="store_true",
                         help="Only extract archives, don't upload")
    p_batch.add_argument("--yes", "-y", action="store_true",
                         help="Skip confirmation prompt")
    p_batch.add_argument("--keep-project", action="store_true",
                         help="Don't delete temp Unity project after upload")

    # extract
    p_extract = sub.add_parser("extract", help="Extract .unitypackage from model archives")
    p_extract.add_argument("--dir", required=True, help="Directory to scan")
    p_extract.add_argument("--output", "-o", help="Save results to JSON file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "setup": cmd_setup,
        "upload": cmd_upload,
        "batch": cmd_batch,
        "extract": cmd_extract,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
