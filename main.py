import os
import sys
import time
import argparse
import subprocess
import shutil
import threading

def run_command(cmd, cwd=None, ignore_errors=False):
    print(f"[*] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0 and not ignore_errors:
        print(f"[!] Error running command:\n{result.stderr}")
        sys.exit(1)
    return result.stdout

def tail_log(log_path, stop_event, project_path):
    print(f"[*] Tailing Unity log: {log_path}")
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        f.seek(0, 2) # Go to end
        while not stop_event.is_set():
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            
            line = line.strip()
            if "[AutoUploader]" in line:
                print(f"  {line}")
                
            if "[AutoUploader] Awaiting 2FA" in line:
                # Prompt user for 2FA
                code = input("\n[?] Enter VRChat 2FA Code (Email/App): ").strip()
                with open(os.path.join(project_path, "2fa.txt"), 'w', encoding='utf-8') as f2fa:
                    f2fa.write(code)
                print("[*] 2FA code sent to Unity.")

def main():
    parser = argparse.ArgumentParser(description="VRChat Avatar Auto Uploader")
    parser.add_argument("--package", required=True, help="Path to the .unitypackage file")
    parser.add_argument("--username", required=True, help="VRChat Username")
    parser.add_argument("--password", required=True, help="VRChat Password")
    args = parser.parse_args()

    unity_exe = r"C:\Program Files\Unity\Hub\Editor\2022.3.22f1\Editor\Unity.exe"
    vrc_get_exe = r"D:\vrc-get\vrc-get.exe" # Assume it's downloaded here for now
    project_path = os.path.abspath("TempVRCUploadProject")
    
    if not os.path.exists(unity_exe):
        print(f"[!] Unity not found at {unity_exe}")
        sys.exit(1)
    
    package_path = os.path.abspath(args.package)
    if not os.path.exists(package_path):
        print(f"[!] Unity package not found at {package_path}")
        sys.exit(1)

    print("\n=== Phase 1: Environment Provisioning ===")
    if os.path.exists(project_path):
        print("[*] Removing old temp project...")
        shutil.rmtree(project_path, ignore_errors=True)
    
    print("[*] Creating empty Unity project...")
    run_command([unity_exe, "-createProject", project_path, "-batchmode", "-nographics", "-quit"])
    
    print("[*] Installing VRChat SDK and dependencies via vrc-get...")
    run_command([vrc_get_exe, "install", "-p", project_path, "com.vrchat.avatars", "-y"])
    run_command([vrc_get_exe, "install", "-p", project_path, "jp.lilxyzw.liltoon", "-y"])
    run_command([vrc_get_exe, "install", "-p", project_path, "nadena.dev.modular-avatar", "-y"], ignore_errors=True)

    print("\n=== Phase 2: Injecting AutoUploader Script ===")
    editor_dir = os.path.join(project_path, "Assets", "Editor")
    os.makedirs(editor_dir, exist_ok=True)
    script_src = os.path.join(os.path.dirname(__file__), "UnityScripts", "AutoUploader.cs")
    shutil.copy(script_src, os.path.join(editor_dir, "AutoUploader.cs"))
    
    # Pre-create log file
    log_path = os.path.join(project_path, "Editor.log")
    open(log_path, 'w').close()

    print("\n=== Phase 3: Executing Unity Batchmode ===")
    unity_cmd = [
        unity_exe,
        "-projectPath", project_path,
        "-batchmode",
        "-nographics",
        "-logFile", log_path,
        "-executeMethod", "VRCAutoUploader.AutoUploader.Execute",
        "-vrcPackage", package_path,
        "-vrcUser", args.username,
        "-vrcPass", args.password
    ]
    
    stop_event = threading.Event()
    tail_thread = threading.Thread(target=tail_log, args=(log_path, stop_event, project_path))
    tail_thread.daemon = True
    tail_thread.start()
    
    print("[*] Unity process started. Please wait (this can take 5-10 minutes)...")
    subprocess.run(unity_cmd)
    
    stop_event.set()
    print("\n=== Done ===")
    print("[*] Checking logs for success...")
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        log_content = f.read()
        if "UPLOAD_SUCCESS" in log_content:
            print("[+] Upload completed successfully!")
        else:
            print("[-] Upload may have failed. Check Editor.log for details.")
            
if __name__ == "__main__":
    main()
