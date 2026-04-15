# VRChat Avatar Auto Uploader

全自动批量上传 VRChat Avatar 的 CLI 工具。从 `.unitypackage` 到 VRChat 服务器，一条命令搞定。

## ⚡ 工作原理

```
Python Orchestrator                    Unity Editor (GUI mode)
┌───────────────────┐                  ┌─────────────────────────┐
│ 1. 解压压缩包      │                  │ [InitializeOnLoad]      │
│ 2. 创建纯净工程    │  ──启动Unity──▶  │ 打开 SDK Control Panel  │
│ 3. 安装 SDK/lilToon│                  │ 导入 .unitypackage      │
│ 4. 注入 C# 脚本    │                  │ 查找 Avatar Prefab      │
│ 5. 实时读取日志    │  ◀──JSON结果──   │ 清除 Blueprint ID       │
│ 6. 反馈上传结果    │                  │ BuildAndUpload() 🚀     │
└───────────────────┘                  └─────────────────────────┘
```

> **为什么不用 `-batchmode`（无头模式）？**
>
> VRChat SDK 的 `VRCSdkControlPanel.TryGetBuilder()` **依赖 Unity Editor GUI 初始化**。
> 在 `-batchmode -nographics` 下 Builder 实例不会注册，上传必定失败。
> 本工具使用正确的 GUI 模式启动 Unity，但全程自动化无需人工操作。

## 🛠️ 环境要求

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 主控脚本 |
| Unity | 2022.3.22f1 | VRChat 官方指定版本 |
| vrc-get | latest | VRChat 包管理器 (自动下载) |

## 🚀 快速开始

### 1. 首次设置

```bash
cd VRC-Auto-Uploader
python main.py setup
```

这会自动检测你电脑上的 Unity 安装和 vrc-get。如果 vrc-get 不存在会自动下载。

### 2. 首次登录 VRChat (仅需一次)

第一次上传时，Unity 会打开 VRChat SDK Control Panel。**你需要手动登录一次**。
登录后 session 会持久化，后续所有上传都不需要再输入密码。

### 3. 上传单个模型

```bash
python main.py upload --package "D:\Model\Azuki\Azuki_v1.2.1.unitypackage"
```

### 4. 批量上传整个目录

```bash
# 先预览要上传的模型（仅解压，不上传）
python main.py extract --dir "D:\Model"

# 确认无误后，批量上传
python main.py batch --dir "D:\Model"

# 跳过确认直接上传
python main.py batch --dir "D:\Model" -y
```

## 📂 项目结构

```
VRC-Auto-Uploader/
├── main.py              # Python 主控脚本
├── config.py            # 环境检测 & 配置管理
├── extractor.py         # 智能解压 (.zip/.rar/.7z)
├── config.json          # 持久化配置 (自动生成)
├── UnityScripts/
│   ├── AutoUploader.cs  # Unity C# 上传核心
│   └── PopupSuppressor.cs  # 自动关闭弹窗
└── tools/
    └── vrc-get.exe      # 自动下载的包管理器
```

## ✨ 特性

- **🧹 零污染**: 每次上传都在独立的临时 Unity 工程中进行，绝不相互影响
- **💊 自动装依赖**: 自动安装 VRChat SDK、lilToon（防粉红材质）、Modular Avatar
- **🔑 Blueprint ID 清理**: 自动清除原作者的蓝图 ID，避免"无法覆盖他人 Avatar"错误
- **🔍 智能搜索**: 同时搜索 Prefab 和 Scene 文件中的 Avatar
- **📦 智能解压**: 自动从 .zip/.rar/.7z 中提取 .unitypackage，过滤 Shader 插件包
- **🛡️ 完善错误处理**: 覆盖 SDK 所有异常类型 (Validation/Ownership/Upload/Builder)
- **📊 JSON 结果输出**: 上传结果写入 JSON 文件，方便二次开发

## ⚠️ 注意事项

1. **首次使用必须手动登录** — VRChat SDK 不支持在代码中直接传账号密码
2. **上传过程中 Unity 会打开 GUI** — 这不是 bug，是 SDK 的要求
3. **确保有上传权限** — VRChat 账号需要 New User (蓝名) 及以上信任等级

## 📜 技术参考

- [VRCMultiUploader](https://github.com/I5UCC/VRCMultiUploader) — 社区批量上传工具 (本项目参考实现)
- [VRChat Creator Docs](https://creators.vrchat.com/) — 官方文档
- [vrc-get](https://github.com/vrc-get/vrc-get) — VRChat 包管理器

---

*Disclaimer: This is an educational tool. Ensure you have the rights to upload the avatars you process.*