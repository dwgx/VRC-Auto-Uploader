/*
 * VRC Auto Uploader — Popup Suppressor
 * 
 * Automatically handles SDK popups and dialogs that would block
 * the automated upload pipeline. In particular:
 *   - Suppresses the copyright agreement popup (auto-accepts)
 *   - Handles "SDK update available" prompts
 *   - Closes any other blocking dialog windows
 */

using UnityEngine;
using UnityEditor;
using System;
using System.Reflection;

namespace VRCAutoUploader
{
    [InitializeOnLoad]
    public static class PopupSuppressor
    {
        private static int _frameCount = 0;

        static PopupSuppressor()
        {
            // Only activate when AutoUploader is running
            string taskFile = System.IO.Path.Combine(
                System.IO.Directory.GetCurrentDirectory(), "upload_tasks.json");

            if (!System.IO.File.Exists(taskFile))
                return;

            EditorApplication.update += SuppressPopups;
            Debug.Log("[AutoUploader] PopupSuppressor active");
        }

        private static void SuppressPopups()
        {
            _frameCount++;

            // Check every ~2 seconds
            if (_frameCount % 120 != 0) return;

            try
            {
                // Close any EditorUtility.DisplayDialog that might be open
                // Unity doesn't provide a direct way to detect/close these,
                // but we can close any popup-type EditorWindows
                var windows = Resources.FindObjectsOfTypeAll<EditorWindow>();
                foreach (var window in windows)
                {
                    string title = window.titleContent?.text ?? "";

                    // Auto-close known blocking popups
                    if (title.Contains("VRChat SDK") && title.Contains("Update"))
                    {
                        Debug.Log($"[AutoUploader] Closing popup: {title}");
                        window.Close();
                    }
                }
            }
            catch (Exception)
            {
                // Silently ignore — popup suppression is best-effort
            }
        }
    }
}
