/*
 * VRC Auto Uploader — Unity Editor Script
 * 
 * This script runs inside the Unity Editor (NOT batchmode) and handles:
 *   1. Reading the task list (upload_tasks.json) from the project root
 *   2. Opening the VRChat SDK Control Panel (required for builder API)
 *   3. Importing each .unitypackage
 *   4. Finding the avatar prefab and instantiating it in a scene
 *   5. Clearing old Blueprint IDs (so it uploads as a new avatar)
 *   6. Building and uploading via IVRCSdkAvatarBuilderApi
 *   7. Writing results to upload_results.json
 *
 * ARCHITECTURE NOTE:
 *   The VRChat SDK's BuildAndUpload pipeline REQUIRES the Unity Editor GUI
 *   to be running. VRCSdkControlPanel.TryGetBuilder() will return false in
 *   -batchmode because the SDK panel never initializes. This is why we run
 *   Unity in normal (GUI) mode and use [InitializeOnLoad] + delayCall.
 *
 * Reference implementation: I5UCC/VRCMultiUploader (GPL-3.0)
 */

using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using VRC.Core;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3A.Editor;
using VRC.SDKBase.Editor;
using VRC.SDKBase.Editor.Api;

namespace VRCAutoUploader
{
    // ─── Data Models ────────────────────────────────────────────────────────

    [Serializable]
    public class UploadTask
    {
        public string name;
        public string packagePath;
        public string avatarName;
    }

    [Serializable]
    public class UploadTaskList
    {
        public UploadTask[] tasks;
    }

    [Serializable]
    public class UploadResult
    {
        public string name;
        public string status; // "success", "failed", "skipped"
        public string error;
        public string blueprintId;
    }

    [Serializable]
    public class UploadResultList
    {
        public List<UploadResult> results = new List<UploadResult>();
    }

    // ─── Main Controller ────────────────────────────────────────────────────

    [InitializeOnLoad]
    public static class AutoUploader
    {
        private static readonly string ProjectRoot = Directory.GetCurrentDirectory();
        private static readonly string TaskFilePath = Path.Combine(ProjectRoot, "upload_tasks.json");
        private static readonly string ResultFilePath = Path.Combine(ProjectRoot, "upload_results.json");
        private static readonly string LockFilePath = Path.Combine(ProjectRoot, "autouploader.lock");

        private static UploadTaskList _taskList;
        private static UploadResultList _resultList;
        private static int _currentTaskIndex = -1;
        private static bool _isRunning = false;
        private static bool _sdkReady = false;
        private static IVRCSdkAvatarBuilderApi _builder;

        static AutoUploader()
        {
            // Only auto-start if invoked via -executeMethod
            // Check if task file exists — this is our signal to run
            if (!File.Exists(TaskFilePath))
                return;

            // Prevent double-execution
            if (File.Exists(LockFilePath))
            {
                var lockTime = File.GetLastWriteTime(LockFilePath);
                if ((DateTime.Now - lockTime).TotalMinutes < 30)
                {
                    Log("Lock file exists and is recent — another instance may be running. Aborting.");
                    return;
                }
            }
            File.WriteAllText(LockFilePath, DateTime.Now.ToString());

            Log("=== VRC Auto Uploader Initialized ===");
            Log($"Task file: {TaskFilePath}");

            // Use delayCall to let Unity fully initialize first
            EditorApplication.delayCall += OnEditorReady;
        }

        /// <summary>
        /// Alternative entry point for -executeMethod invocation.
        /// </summary>
        public static void Execute()
        {
            Log("Execute() called via -executeMethod");
            // The static constructor already handles startup via [InitializeOnLoad].
            // This method exists as a fallback entry point.
            if (!_isRunning && File.Exists(TaskFilePath))
            {
                EditorApplication.delayCall += OnEditorReady;
            }
        }

        // ─── Lifecycle ──────────────────────────────────────────────────────

        private static void OnEditorReady()
        {
            if (_isRunning) return;
            _isRunning = true;

            try
            {
                // 1. Read task list
                string json = File.ReadAllText(TaskFilePath);
                _taskList = JsonUtility.FromJson<UploadTaskList>(json);
                _resultList = new UploadResultList();

                if (_taskList?.tasks == null || _taskList.tasks.Length == 0)
                {
                    Log("No tasks found in task file. Exiting.");
                    Finish();
                    return;
                }

                Log($"Loaded {_taskList.tasks.Length} upload task(s)");

                // 2. Open SDK Control Panel — this is REQUIRED for the builder API
                Log("Opening VRChat SDK Control Panel...");
                EditorApplication.ExecuteMenuItem("VRChat SDK/Show Control Panel");

                // 3. Wait for SDK to be ready, then start processing
                // Hook into the SDK panel enable event
                VRCSdkControlPanel.OnSdkPanelEnable += OnSdkPanelReady;

                // Also poll periodically in case the event was already fired
                EditorApplication.update += PollForSdkReady;
            }
            catch (Exception ex)
            {
                LogError($"Failed to initialize: {ex.Message}\n{ex.StackTrace}");
                Finish();
            }
        }

        private static void OnSdkPanelReady(object sender, EventArgs e)
        {
            Log("SDK Control Panel is ready (event received)");
            _sdkReady = true;
            VRCSdkControlPanel.OnSdkPanelEnable -= OnSdkPanelReady;
        }

        private static int _pollCount = 0;
        private static void PollForSdkReady()
        {
            _pollCount++;

            // Try every 2 seconds (update runs ~60fps, so every 120 frames)
            if (_pollCount % 120 != 0) return;

            // Check if we can get the builder
            if (VRCSdkControlPanel.TryGetBuilder<IVRCSdkAvatarBuilderApi>(out var builder))
            {
                _builder = builder;
                _sdkReady = true;
            }

            if (_sdkReady && _builder != null)
            {
                EditorApplication.update -= PollForSdkReady;
                Log("SDK Builder API acquired — starting upload pipeline");
                StartNextTask();
            }

            // Timeout after 10 minutes
            if (_pollCount > 120 * 60 * 10)
            {
                EditorApplication.update -= PollForSdkReady;
                LogError("Timed out waiting for SDK Control Panel. " +
                         "Please ensure you are logged in to VRChat in the SDK panel.");
                Finish();
            }
        }

        // ─── Task Processing ────────────────────────────────────────────────

        private static async void StartNextTask()
        {
            _currentTaskIndex++;

            if (_currentTaskIndex >= _taskList.tasks.Length)
            {
                Log($"All tasks complete! ({_resultList.results.Count} processed)");
                Finish();
                return;
            }

            var task = _taskList.tasks[_currentTaskIndex];
            int num = _currentTaskIndex + 1;
            int total = _taskList.tasks.Length;
            Log($"═══ Task [{num}/{total}]: {task.name} ═══");

            var result = new UploadResult { name = task.name };

            try
            {
                // Validate package exists
                if (!File.Exists(task.packagePath))
                {
                    result.status = "failed";
                    result.error = $"Package file not found: {task.packagePath}";
                    LogError(result.error);
                    _resultList.results.Add(result);
                    StartNextTask();
                    return;
                }

                // Step 1: Create a clean scene
                Log("Creating clean scene...");
                var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

                // Step 2: Import the .unitypackage
                Log($"Importing package: {Path.GetFileName(task.packagePath)}");
                AssetDatabase.ImportPackage(task.packagePath, false);

                // Give Unity time to process the import
                await Task.Delay(3000);
                AssetDatabase.Refresh();
                await Task.Delay(2000);

                // Step 3: Find avatar prefab
                Log("Searching for avatar prefab...");
                GameObject avatarInstance = FindAndInstantiateAvatar();

                if (avatarInstance == null)
                {
                    // Try loading from scene files
                    avatarInstance = FindAvatarInScenes();
                }

                if (avatarInstance == null)
                {
                    result.status = "failed";
                    result.error = "Could not find VRCAvatarDescriptor in imported assets";
                    LogError(result.error);
                    _resultList.results.Add(result);
                    CleanupImportedAssets();
                    StartNextTask();
                    return;
                }

                Log($"Found avatar: {avatarInstance.name}");

                // Step 4: Clear Blueprint ID (critical for new uploads)
                var pipelineManager = avatarInstance.GetComponent<PipelineManager>();
                if (pipelineManager != null)
                {
                    if (!string.IsNullOrEmpty(pipelineManager.blueprintId))
                    {
                        Log($"Clearing old Blueprint ID: {pipelineManager.blueprintId}");
                        pipelineManager.blueprintId = "";
                    }
                }
                else
                {
                    // Add PipelineManager if missing
                    pipelineManager = avatarInstance.AddComponent<PipelineManager>();
                    pipelineManager.blueprintId = "";
                }

                // Step 5: Set avatar name
                if (!string.IsNullOrEmpty(task.avatarName))
                {
                    avatarInstance.name = task.avatarName;
                }

                // Step 6: Ensure builder is available
                if (_builder == null)
                {
                    if (!VRCSdkControlPanel.TryGetBuilder<IVRCSdkAvatarBuilderApi>(out _builder))
                    {
                        result.status = "failed";
                        result.error = "SDK Builder API not available. Is the SDK Control Panel open?";
                        LogError(result.error);
                        _resultList.results.Add(result);
                        StartNextTask();
                        return;
                    }
                }

                // Step 7: Build and Upload
                Log("Starting Build & Upload...");
                CancellationTokenSource cts = new CancellationTokenSource();

                // Subscribe to progress events
                _builder.OnSdkBuildProgress += (sender, msg) => Log($"  Build: {msg}");
                _builder.OnSdkBuildFinish += (sender, msg) => Log($"  Build finished, uploading...");

                try
                {
                    // For new avatars (no blueprint ID), use BuildAndUpload without existing avatar data
                    await _builder.BuildAndUpload(avatarInstance, null, cancellationToken: cts.Token);

                    // Get the new blueprint ID
                    var pm = avatarInstance.GetComponent<PipelineManager>();
                    string newId = pm != null ? pm.blueprintId : "unknown";

                    result.status = "success";
                    result.blueprintId = newId;
                    Log($"UPLOAD_SUCCESS — {task.name} (Blueprint: {newId})");
                }
                catch (BuilderException ex)
                {
                    result.status = "failed";
                    result.error = $"Build failed: {ex.Message}";
                    LogError(result.error);
                }
                catch (ValidationException ex)
                {
                    result.status = "failed";
                    result.error = $"Validation failed: {ex.Message} — {string.Join("; ", ex.Errors)}";
                    LogError(result.error);
                }
                catch (OwnershipException ex)
                {
                    result.status = "failed";
                    result.error = $"Ownership error: {ex.Message}";
                    LogError(result.error);
                }
                catch (UploadException ex)
                {
                    result.status = "failed";
                    result.error = $"Upload error: {ex.Message}";
                    LogError(result.error);
                }
                finally
                {
                    cts.Dispose();
                }
            }
            catch (Exception ex)
            {
                result.status = "failed";
                result.error = $"Unexpected error: {ex.Message}";
                LogError($"{result.error}\n{ex.StackTrace}");
            }

            _resultList.results.Add(result);

            // Save intermediate results (in case Unity crashes mid-batch)
            SaveResults();

            // Cleanup imported assets before next task
            CleanupImportedAssets();

            // Small delay between tasks
            await Task.Delay(2000);

            // Continue to next
            StartNextTask();
        }

        // ─── Avatar Discovery ───────────────────────────────────────────────

        private static GameObject FindAndInstantiateAvatar()
        {
            // Search all prefabs for VRCAvatarDescriptor
            var guids = AssetDatabase.FindAssets("t:Prefab");
            List<(string path, GameObject prefab)> candidates = new List<(string, GameObject)>();

            foreach (var guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);

                // Skip Unity built-in and Package assets
                if (!path.StartsWith("Assets/")) continue;
                // Skip our own Editor scripts
                if (path.Contains("Editor/VRCAutoUploader")) continue;

                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab == null) continue;

                if (prefab.GetComponent<VRCAvatarDescriptor>() != null)
                {
                    candidates.Add((path, prefab));
                }
            }

            if (candidates.Count == 0) return null;

            // Pick the "best" prefab — prefer ones at the root of import folders
            var best = candidates
                .OrderBy(c => c.path.Count(ch => ch == '/'))  // Prefer shallower paths
                .First();

            Log($"Instantiating prefab: {best.path}");
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(best.prefab);
            instance.transform.position = Vector3.zero;
            return instance;
        }

        private static GameObject FindAvatarInScenes()
        {
            // Some models come as .unity scene files instead of prefabs
            var sceneGuids = AssetDatabase.FindAssets("t:Scene");

            foreach (var guid in sceneGuids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                if (!path.StartsWith("Assets/")) continue;

                try
                {
                    var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Additive);

                    foreach (var rootObj in scene.GetRootGameObjects())
                    {
                        var descriptor = rootObj.GetComponentInChildren<VRCAvatarDescriptor>();
                        if (descriptor != null)
                        {
                            Log($"Found avatar in scene: {path} → {descriptor.gameObject.name}");
                            // Move to our main scene
                            UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(
                                rootObj, 
                                EditorSceneManager.GetActiveScene()
                            );
                            EditorSceneManager.CloseScene(scene, true);
                            return rootObj;
                        }
                    }

                    EditorSceneManager.CloseScene(scene, true);
                }
                catch (Exception ex)
                {
                    LogError($"Error opening scene {path}: {ex.Message}");
                }
            }

            return null;
        }

        // ─── Utility ────────────────────────────────────────────────────────

        private static void CleanupImportedAssets()
        {
            // Remove imported assets to start clean for next package
            // We keep the Editor/VRCAutoUploader folder
            var assetDirs = Directory.GetDirectories(Path.Combine(ProjectRoot, "Assets"));
            foreach (var dir in assetDirs)
            {
                string dirName = Path.GetFileName(dir);
                if (dirName == "Editor") continue; // Keep our scripts

                try
                {
                    FileUtil.DeleteFileOrDirectory(dir);
                    FileUtil.DeleteFileOrDirectory(dir + ".meta");
                }
                catch { }
            }

            // Also remove loose files in Assets/ (but not .meta for Editor)
            var assetFiles = Directory.GetFiles(Path.Combine(ProjectRoot, "Assets"));
            foreach (var file in assetFiles)
            {
                if (!file.EndsWith(".meta") || !file.Contains("Editor"))
                {
                    try { FileUtil.DeleteFileOrDirectory(file); } catch { }
                }
            }

            AssetDatabase.Refresh();
        }

        private static void SaveResults()
        {
            try
            {
                string json = JsonUtility.ToJson(_resultList, true);
                File.WriteAllText(ResultFilePath, json);
            }
            catch (Exception ex)
            {
                LogError($"Failed to save results: {ex.Message}");
            }
        }

        private static void Finish()
        {
            SaveResults();

            // Cleanup
            try
            {
                if (File.Exists(LockFilePath))
                    File.Delete(LockFilePath);
            }
            catch { }

            Log("=== VRC Auto Uploader Finished ===");

            // Exit Unity after a short delay
            EditorApplication.delayCall += () =>
            {
                EditorApplication.Exit(0);
            };
        }

        // ─── Logging ────────────────────────────────────────────────────────

        private static void Log(string message)
        {
            Debug.Log($"[AutoUploader] {message}");
            AppendToLocalLog($"[INFO] {message}");
        }

        private static void LogError(string message)
        {
            Debug.LogError($"[AutoUploader] {message}");
            AppendToLocalLog($"[ERROR] {message}");
        }

        private static void AppendToLocalLog(string message)
        {
            try
            {
                string logFile = Path.Combine(ProjectRoot, "autouploader.log");
                File.AppendAllText(logFile,
                    $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}\n");
            }
            catch { }
        }
    }
}
