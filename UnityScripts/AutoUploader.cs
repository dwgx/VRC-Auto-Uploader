using UnityEngine;
using UnityEditor;
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Threading.Tasks;
using VRC.Core;
using VRC.SDK3.Avatars.Components;
using VRC.SDKBase.Editor;
using VRC.SDKBase.Editor.Api;

namespace VRCAutoUploader
{
    public static class AutoUploader
    {
        private static string packagePath;
        private static string username;
        private static string password;

        public static void Execute()
        {
            try
            {
                Debug.Log("[AutoUploader] Initialization started...");
                string[] args = Environment.GetCommandLineArgs();
                for (int i = 0; i < args.Length; i++)
                {
                    if (args[i] == "-vrcPackage" && i + 1 < args.Length) packagePath = args[i + 1];
                    if (args[i] == "-vrcUser" && i + 1 < args.Length) username = args[i + 1];
                    if (args[i] == "-vrcPass" && i + 1 < args.Length) password = args[i + 1];
                }

                if (string.IsNullOrEmpty(packagePath) || string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
                {
                    Debug.LogError("[AutoUploader] Missing required arguments (-vrcPackage, -vrcUser, -vrcPass)");
                    EditorApplication.Exit(1);
                    return;
                }

                Debug.Log($"[AutoUploader] Package Path: {packagePath}");
                Debug.Log($"[AutoUploader] Username: {username}");

                EditorApplication.update += OnUpdate;
                State = UploadState.Importing;
                AssetDatabase.importPackageCompleted += OnImportPackageCompleted;
                AssetDatabase.importPackageFailed += OnImportPackageFailed;
                AssetDatabase.importPackageCancelled += OnImportPackageCancelled;
                
                Debug.Log("[AutoUploader] Triggering AssetDatabase.ImportPackage...");
                AssetDatabase.ImportPackage(packagePath, false);
            }
            catch (Exception e)
            {
                Debug.LogError($"[AutoUploader] Error in Execute: {e.Message}");
                EditorApplication.Exit(1);
            }
        }

        private enum UploadState { Idle, Importing, Authenticating, WaitFor2FA, ProcessingAvatar, Building }
        private static UploadState State = UploadState.Idle;

        private static void OnImportPackageCompleted(string packageName)
        {
            Debug.Log($"[AutoUploader] Import completed: {packageName}");
            State = UploadState.Authenticating;
            LoginToVRChat();
        }

        private static void OnImportPackageFailed(string packageName, string err)
        {
            Debug.LogError($"[AutoUploader] Import failed: {err}");
            EditorApplication.Exit(1);
        }

        private static void OnImportPackageCancelled(string packageName)
        {
            Debug.LogError($"[AutoUploader] Import cancelled.");
            EditorApplication.Exit(1);
        }

        private static void LoginToVRChat()
        {
            Debug.Log("[AutoUploader] Attempting VRChat Login...");
            APIUser.Login(username, password,
                (user) =>
                {
                    Debug.Log($"[AutoUploader] Login successful as: {user.displayName}");
                    State = UploadState.ProcessingAvatar;
                },
                (error) =>
                {
                    Debug.LogWarning($"[AutoUploader] Login failed or requires 2FA: {error}");
                    if (error.Contains("RequireTwoFactorAuth"))
                    {
                        Debug.Log("[AutoUploader] Awaiting 2FA...");
                        State = UploadState.WaitFor2FA;
                    }
                    else
                    {
                        Debug.LogError("[AutoUploader] Fatal Login Error.");
                        EditorApplication.Exit(1);
                    }
                }
            );
        }

        private static async void ProcessAvatar()
        {
            Debug.Log("[AutoUploader] Finding VRCAvatarDescriptor in project...");
            var guids = AssetDatabase.FindAssets("t:Prefab");
            GameObject targetPrefab = null;

            foreach (var guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab != null && prefab.GetComponent<VRCAvatarDescriptor>() != null)
                {
                    targetPrefab = prefab;
                    Debug.Log($"[AutoUploader] Found Avatar Prefab: {path}");
                    
                    // Clear Blueprint ID
                    var pipelineManager = targetPrefab.GetComponent<PipelineManager>();
                    if (pipelineManager != null && !string.IsNullOrEmpty(pipelineManager.blueprintId))
                    {
                        Debug.Log($"[AutoUploader] Clearing Blueprint ID: {pipelineManager.blueprintId}");
                        pipelineManager.blueprintId = "";
                        EditorUtility.SetDirty(targetPrefab);
                        AssetDatabase.SaveAssets();
                    }
                    break;
                }
            }

            if (targetPrefab == null)
            {
                Debug.LogError("[AutoUploader] Could not find any VRCAvatarDescriptor in imported prefabs.");
                EditorApplication.Exit(1);
                return;
            }

            if (!VRCSdkControlPanel.TryGetBuilder<IVRCSdkAvatarBuilderApi>(out var builder))
            {
                Debug.LogError("[AutoUploader] VRChat SDK Builder API not found. Is SDK 3.7+ installed?");
                EditorApplication.Exit(1);
                return;
            }

            try
            {
                Debug.Log("[AutoUploader] Starting BuildAndUpload process via SDK Builder API...");
                await builder.BuildAndUpload(targetPrefab);
                Debug.Log("[AutoUploader] UPLOAD_SUCCESS");
                EditorApplication.Exit(0);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[AutoUploader] BuildAndUpload failed: {ex.Message}");
                EditorApplication.Exit(1);
            }
        }

        private static void OnUpdate()
        {
            if (State == UploadState.WaitFor2FA)
            {
                string twoFaFile = Path.Combine(Directory.GetCurrentDirectory(), "2fa.txt");
                if (File.Exists(twoFaFile))
                {
                    string code = File.ReadAllText(twoFaFile).Trim();
                    File.Delete(twoFaFile);
                    Debug.Log($"[AutoUploader] Read 2FA Code, verifying...");
                    State = UploadState.Authenticating;
                    
                    APIUser.VerifyTwoFactorAuthCode(code, API2FA.EmailOtp,
                        (u) => {
                            Debug.Log($"[AutoUploader] 2FA Login successful as: {u.displayName}");
                            State = UploadState.ProcessingAvatar;
                        },
                        (e) => {
                            Debug.LogError($"[AutoUploader] 2FA Login failed: {e}");
                            EditorApplication.Exit(1);
                        }
                    );
                }
            }

            if (State == UploadState.ProcessingAvatar)
            {
                State = UploadState.Building;
                ProcessAvatar();
            }
        }
    }
}
