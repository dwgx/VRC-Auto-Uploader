# VRChat Avatar Auto Uploader

A robust, out-of-the-box automated CLI tool for batch uploading VRChat `.unitypackage` avatars. 

This project solves the pain point of importing and uploading avatars manually by using a **Python Orchestrator** and **Unity's native C# Batchmode** to do the heavy lifting silently in the background.

## 🚀 Why this over GUI Automation (like AppAgent)?
You might have heard of advanced GUI-to-CLI AI agents (like the open-source projects from Hong Kong University) that simulate mouse clicks to automate software. **While those are cutting-edge, they are NOT the right tool for Unity.**

UI automation is brittle, resolution-dependent, and prone to breaking when menus change. Unity, however, natively supports `-batchmode`, allowing us to execute C# code directly without any UI rendering. This is the industry-standard approach for CI/CD pipelines, making it **1000x more reliable and faster** than simulating mouse clicks.

## ✨ Features
- **Zero Contamination**: Dynamically provisions a brand-new, clean Unity project for every upload using VRChat's official `vrc-get` CLI.
- **Dependency Injection**: Automatically pre-installs the `VRChat SDK`, `lilToon`, and `Modular Avatar` to prevent shader errors (pink materials) upon import.
- **Anti-Blueprint Collision**: Automatically scans imported prefabs, finds the `VRCAvatarDescriptor`, and **clears the original author's Blueprint ID**. This prevents the "Cannot overwrite another user's avatar" error.
- **2FA Support**: Pauses gracefully and prompts the user in the CLI if VRChat Two-Factor Authentication is required.

## 🛠️ Prerequisites
- **Python 3.8+**
- **Unity 2022.3.22f1** (Installed via Unity Hub in the default `C:\Program Files\Unity\Hub\Editor\...` path)
- **vrc-get** CLI (A standalone rust binary used for VRC package management. The script assumes it exists or will try to find it).

## 📦 Usage

1. Open your terminal.
2. Run the orchestrator script:

```bash
python main.py --package "C:\Path\To\Your\Avatar.unitypackage" --username "YourVrcUsername" --password "YourVrcPassword"
```

3. **Sit back and watch.** The script will:
   - Spin up a temporary Unity project.
   - Install SDKs and Shaders.
   - Boot Unity in headless mode (no window).
   - Inject the C# `AutoUploader.cs` script.
   - Import your package, authenticate, and upload.

*Note: If 2FA is enabled on your account, the CLI will pause and ask you to type in the code sent to your email or Authenticator app.*

## 💻 Architecture
1. **`main.py`**: The Python orchestrator. Manages directories, invokes `vrc-get`, launches `Unity.exe` with specific CLI arguments, and tails the Unity `Editor.log` to stream progress to your terminal.
2. **`UnityScripts/AutoUploader.cs`**: The C# brain. It hooks into `EditorApplication.update` to handle the asynchronous nature of `AssetDatabase.ImportPackage`, logs into the `VRC.Core.APIUser`, strips out old blueprint IDs, and interfaces with the VRCSDK Builder APIs.

---
*Disclaimer: This is an educational tool. Ensure you have the rights to upload the avatars you process.*