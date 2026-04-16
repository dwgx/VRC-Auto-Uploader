# VRChat Avatar Auto Uploader

**一条命令批量上传所有 VRChat Avatar | Batch-upload all your VRChat avatars with a single command.**

[![GitHub Pages](https://img.shields.io/badge/docs-GitHub%20Pages-7c6cff?style=flat-square)](https://dwgx.github.io/VRC-Auto-Uploader/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python)](https://python.org)
[![Unity](https://img.shields.io/badge/Unity-2022.3.22f1-black?style=flat-square&logo=unity)](https://unity.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

> 📖 **[查看完整文档 / View Full Docs →](https://dwgx.github.io/VRC-Auto-Uploader/)**

---

## ⚡ 工作原理

```
Python Orchestrator                    Unity Editor (GUI mode)
┌───────────────────┐                  ┌─────────────────────────┐
│ 1. 扫描模型目录    │                  │ [InitializeOnLoad]      │
│ 2. 解压压缩包      │                  │ 打开 SDK Control Panel  │
│ 3. 创建纯净工程    │  ──启动Unity──▶  │ 导入 .unitypackage      │
│ 4. 安装 SDK/lilToon│                  │ 查找 Avatar Prefab      │
│ 5. 注入 C# 脚本    │                  │ 清除 Blueprint ID       │
│ 6. 实时读取日志    │  ◀──JSON结果──   │ BuildAndUpload() 🚀     │
│ 7. 反馈上传结果    │                  │ 自动关闭弹窗            │
└───────────────────┘                  └─────────────────────────┘
```

> **为什么不用 `-batchmode`（无头模式）？**
>
> VRChat SDK 的 `VRCSdkControlPanel.TryGetBuilder()` **依赖 Unity Editor GUI 初始化**。
> 在 `-batchmode -nographics` 下 Builder 实例不会注册，上传必定失败。
> 本工具使用正确的 GUI 模式启动 Unity，但全程自动化无需人工操作。

---

## 🛠️ 环境要求

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 主控脚本 |
| Unity | 2022.3.22f1 | VRChat 官方指定版本，通过 Unity Hub 安装 |
| vrc-get | 自动下载 | VRChat 包管理器，首次运行 `setup` 时自动获取 |
| 7-Zip | 可选 | 如需解压 `.rar` / `.7z` 格式，需安装 7-Zip |

---

## 🚀 快速开始

### 第一步：克隆并配置

```bash
git clone https://github.com/dwgx/VRC-Auto-Uploader.git
cd VRC-Auto-Uploader
python main.py setup
```

这会自动检测你电脑上的 Unity 安装位置，并下载 `vrc-get`。

### 第二步：首次登录 VRChat（仅需一次）

```bash
python main.py upload --package "D:\Model\Azuki\Azuki.unitypackage"
```

Unity 会弹出 VRChat SDK 控制面板，**手动登录你的 VRChat 账号**。
登录后 session 会持久化，后续所有上传都不需要再次输入密码。

### 第三步：批量上传整个目录

```bash
# 预览将要上传的模型（只解压，不上传）
python main.py extract --dir "D:\Model"

# 确认无误后，批量上传
python main.py batch --dir "D:\Model" -y
```

---

## 📋 完整命令列表

```bash
# 首次配置 / 修复环境
python main.py setup

# 上传单个 .unitypackage
python main.py upload --package "PATH\TO\model.unitypackage"
python main.py upload --package "PATH\TO\model.unitypackage" --keep-project

# 批量上传整个目录下的所有模型
python main.py batch --dir "D:\Model"          # 交互式确认
python main.py batch --dir "D:\Model" -y       # 跳过确认，直接开始
python main.py batch --dir "D:\Model" --extract-only  # 只解压不上传

# 只扫描解压（不上传）
python main.py extract --dir "D:\Model"
python main.py extract --dir "D:\Model" -o results.json
```

---

## 📂 项目结构

```
VRC-Auto-Uploader/
├── main.py                    # Python 主控脚本（CLI 入口）
├── config.py                  # 环境检测 & 配置管理（自动修复）
├── extractor.py               # 智能解压（.zip/.rar/.7z）
├── requirements.txt           # 无外部依赖（纯标准库）
├── config.json                # 持久化配置（自动生成）
├── UnityScripts/
│   ├── AutoUploader.cs        # Unity C# 上传核心脚本
│   └── PopupSuppressor.cs     # 自动处理 SDK 弹窗
├── docs/
│   └── index.html             # GitHub Pages 文档页面
└── .github/
    └── workflows/
        └── pages.yml          # 自动部署 GitHub Pages
```

---

## ✨ 特性详解

| 特性 | 说明 |
|------|------|
| 🧹 零污染 | 每次上传都在独立临时工程中进行，绝不相互影响 |
| 💊 自动装依赖 | 自动安装 VRChat SDK、lilToon（防粉红）、Modular Avatar |
| 🔑 Blueprint ID 清理 | 自动清除原作者蓝图 ID，避免"无法覆盖他人 Avatar"错误 |
| 🤖 弹窗自动处理 | 自动接受版权声明、关闭更新提示，全程无需人工点击 |
| 🔍 智能搜索 | 同时搜索 Prefab 和 Scene 文件中的 Avatar |
| 📦 智能解压 | 自动从 .zip/.rar/.7z 提取 .unitypackage，过滤 Shader 包 |
| 🔧 自动修复环境 | 工具路径失效时自动重新检测并修复，无需手动 `setup` |
| 🛡️ 完善错误处理 | 覆盖所有 SDK 异常类型，失败自动跳过继续下一个 |
| 📊 JSON 结果输出 | 上传结果含 blueprintId，写入 JSON 文件方便二次使用 |

---

## 📊 上传结果

上传完成后，结果保存在 `TempVRCProject/upload_results.json`：

```json
{
  "results": [
    {
      "name": "Airi爱莉",
      "status": "success",
      "error": "",
      "blueprintId": "avtr_582e9038-6ccd-4e37-a096-cc83dcc969b5"
    },
    {
      "name": "BrokenModel",
      "status": "failed",
      "error": "Could not find VRCAvatarDescriptor",
      "blueprintId": ""
    }
  ]
}
```

---

## ⚠️ 注意事项

1. **首次使用必须手动登录** — VRChat SDK 不支持在代码中直接传账号密码
2. **上传过程中 Unity 会打开 GUI** — 这不是 bug，是 SDK 的设计要求
3. **确保有上传权限** — VRChat 账号需要 New User (蓝名) 及以上信任等级
4. **请确保拥有模型版权** — 本工具不对版权问题负责，仅供合法使用

---

## 📜 技术参考

- [VRCMultiUploader](https://github.com/I5UCC/VRCMultiUploader) — 社区批量上传工具（参考实现）
- [VRChat Creator Docs](https://creators.vrchat.com/) — VRChat 官方开发者文档
- [vrc-get](https://github.com/vrc-get/vrc-get) — VRChat VPM 包管理器

---

## 🌐 GitHub Pages 部署

本仓库的 `docs/` 目录包含完整的项目文档页面，可直接启用 GitHub Pages：

1. 进入仓库 → **Settings** → **Pages**
2. Source 选择 **GitHub Actions**
3. 推送代码后，Actions 会自动部署 `docs/` 到 Pages

---

*Disclaimer: This is an educational tool. Ensure you have the rights to upload the avatars you process.*