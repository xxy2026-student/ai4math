# AI4Research 本地部署指南

本仓库仍名为 `ai4math`，但当前定位是带人类决策门的 AI4Research 工作流。本文面向希望在自己电脑上完整运行项目的用户。

## 1. 环境要求

- Windows 10/11、macOS 或常见 Linux 发行版
- Python 3.11 或更高版本
- Git（推荐；也可以下载 ZIP）
- 可访问 Python 包索引的网络
- 至少一种运行入口：
  - 内置 runner：需要一个兼容 OpenAI `chat.completions` 和 function calling 的模型 API；
  - Claude Code：需要 Claude Code 已安装并完成登录；
  - OpenCode：可选，需要 OpenCode 已安装并配置模型。

首次安装依赖大约需要下载 150 MB。密钥只应放在环境变量或密钥管理器中，不要写进仓库文件。

## 2. 获取代码

推荐克隆默认分支：

```bash
git clone https://github.com/xxy2026-student/ai4math.git
cd ai4math
```

如果 AI4Research 版 PR 尚未合并到 `main`，可临时检出功能分支：

```bash
git clone --branch codex/ai4research-human-gates --single-branch https://github.com/xxy2026-student/ai4math.git
cd ai4math
```

从 ZIP 解压也可以运行，但将不能使用本文中的 `git pull`、`git status` 和 `git restore` 命令。

## 3. Windows 一键安装

在 PowerShell 中进入仓库目录，推荐先只安装项目自身，不修改全局 OpenCode：

```powershell
Set-Location <你的路径>\ai4math
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Yes -SkipOpenCode
```

也可以双击 `setup.bat`，按提示选择是否安装 OpenCode。

安装脚本会：

1. 检查 Python 3.11+；
2. 创建 `.venv`；
3. 安装 `requirements.txt`；
4. 运行示例验证器、全树 gate 和 63 项框架测试；
5. 从 `runner/config.example.yaml` 生成未被 Git 跟踪的 `runner/config.yaml`；
6. 检查 API Key 环境变量。

如果 PowerShell 禁止执行脚本，只对当前命令使用上面的 `-ExecutionPolicy Bypass` 即可，不需要永久降低系统策略。

## 4. macOS / Linux 一键安装

```bash
cd /path/to/ai4math
chmod +x setup.sh
./setup.sh --yes --skip-opencode
```

如果系统缺少创建虚拟环境的组件，Debian/Ubuntu 通常需要先安装：

```bash
sudo apt install python3 python3-venv
```

## 5. 手动安装

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item runner\config.example.yaml runner\config.yaml
```

### macOS / Linux

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp runner/config.example.yaml runner/config.yaml
```

如果下载较慢，可以先为该虚拟环境配置可信的镜像，再重试安装。不要从不明来源下载预编译依赖。

## 6. 配置模型

内置 runner 默认使用 DeepSeek。先设置当前终端的环境变量。

Windows PowerShell：

```powershell
$env:DEEPSEEK_API_KEY = "<你的 API Key>"
```

macOS / Linux：

```bash
export DEEPSEEK_API_KEY="<你的 API Key>"
```

上述设置只在当前终端有效。长期使用时，请通过操作系统密钥管理器或受保护的 shell 配置管理密钥，不要把真实值写入 `runner/config.yaml`、`.env`、命令截图、Issue 或提交记录。

要换用 OpenAI、Qwen、Gemini、Moonshot、Ollama、vLLM 或 LiteLLM，请编辑 `runner/config.yaml` 中的：

- `base_url`
- `api_key_env`
- `model`
- 可选的角色级 `roles` 覆盖

配置示例和支持边界见 `runner/config.example.yaml`。接口必须兼容 OpenAI 风格的 `chat.completions` 与 function calling。

## 7. 启动项目

### 方式 A：内置 runner（推荐用于完整暂停/恢复）

Windows：

```powershell
.\.venv\Scripts\python.exe -m runner.main "/ground 你的研究问题或初步想法"
```

macOS / Linux：

```bash
./.venv/bin/python -m runner.main "/ground 你的研究问题或初步想法"
```

工作流到达人类决策门时会保存请求和检查点，然后主动退出。查看待处理决策：

```powershell
.\.venv\Scripts\python.exe -m runner.main --list-decisions pending
```

选择系统给出的选项并恢复：

```powershell
.\.venv\Scripts\python.exe -m runner.main --decide <decision-id> --choice <option-id> --rationale "你的理由"
.\.venv\Scripts\python.exe -m runner.main --resume <decision-id>
```

不想接受现有选项时，可以提交开放方案：

```powershell
.\.venv\Scripts\python.exe -m runner.main --decide <decision-id> --choice custom --custom "你的修正或组合方案"
.\.venv\Scripts\python.exe -m runner.main --resume <decision-id>
```

macOS/Linux 把 `.\.venv\Scripts\python.exe` 替换为 `./.venv/bin/python`。

### 方式 B：Claude Code

先按 Claude Code 官方方式完成安装和登录，然后在仓库根目录运行：

```bash
claude
```

进入会话后输入：

```text
/ground 你的研究问题或初步想法
```

### 方式 C：OpenCode

先确认全局命令确实可运行：

```bash
opencode --version
```

再在仓库根目录运行：

```bash
opencode
```

如果 `opencode --version` 已失败，说明是本机 OpenCode/Node 安装问题，不是本仓库的 Python 环境问题。内置 runner 和 Claude Code 不依赖 OpenCode，可以继续使用。

## 8. 验证部署

先运行不会执行仓库验证器代码的结构检查。

Windows：

```powershell
.\.venv\Scripts\python.exe verifiers\gate.py --all --structure-only
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

macOS / Linux：

```bash
./.venv/bin/python verifiers/gate.py --all --structure-only
./.venv/bin/python -B -m unittest discover -s tests -q
```

成功时，测试结尾应显示 `OK`。当前版本共有 63 项测试。

要执行注册过的真实验证器，可运行：

```powershell
.\.venv\Scripts\python.exe verifiers\gate.py --all
```

完整 gate 会执行仓库代码，并可能刷新模板 evidence 的时间戳。对不可信 fork 应先审查代码；如果你只是在验证干净克隆且不想保留模板时间戳变化，可在确认差异只有该时间戳后运行：

```powershell
git diff -- problems/_template/results/c000_evidence.json
git restore -- problems/_template/results/c000_evidence.json
```

不要用 `git restore` 覆盖你自己的研究 evidence。

## 9. 更新现有安装

先确认没有需要保留的本地修改：

```bash
git status
```

然后只做快进更新，并重新运行幂等安装脚本：

Windows：

```powershell
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Yes -SkipOpenCode
```

macOS / Linux：

```bash
git pull --ff-only
./setup.sh --yes --skip-opencode
```

不要在未备份研究产物时删除整个仓库。`ideas/`、`problems/`、`literature/` 和 `decisions/` 可能包含未被 Git 跟踪的私人研究内容。

## 10. 常见问题

### `ModuleNotFoundError`

通常是用了系统 Python，而不是项目虚拟环境。请使用 `.venv` 中的解释器重新运行。

### `401`、`403` 或提示缺少 API Key

确认 `runner/config.yaml` 的 `api_key_env` 与实际环境变量名一致。只检查变量是否存在，不要在公开日志中打印它的值。

### `--list-decisions pending` 显示“没有匹配的决策”

这是正常状态，表示当前还没有运行中的研究流程停在人类决策门。先执行一次 `/ground`。

### OpenCode 无法启动

先运行 `opencode --version`。如果这里就失败，请修复本机 OpenCode/Node 安装，或者改用内置 runner/Claude Code。

### GitHub CI 是否通过

PR 页面中 `framework-checks / test` 为绿色 `pass` 才表示 CI 通过。Draft 只表示 PR 尚未进入合并状态，不等于 CI 失败。

## 11. 隐私和安全边界

- `runner/config.yaml`、个人决策记录和默认私人研究目录已被 `.gitignore` 排除，但提交前仍应运行 `git status` 检查。
- 不要提交 API Key、私有数据、未获授权的论文全文或个人反馈。
- 项目的人类决策门提供本地流程约束和可追溯记录，但目前不是带数字签名的人类身份安全边界。
- `evidence-supported` 和 `reviewed` 不等同于数学证明；Lean 是按研究问题需要启用的可选形式证据通道。

部署完成后，建议从一个范围较小、成功标准明确的问题开始：

```text
/ground 我想研究……；目标指标是……；暂时不考虑……
```
