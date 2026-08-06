<#
AI4Research 一键部署（Windows；仓库名兼容保留为 ai4math）。

用法：双击 setup.bat，或在 PowerShell 中：
    .\setup.ps1                 # 交互式，问一步装一步
    .\setup.ps1 -Yes            # 全部默认继续，不询问
    .\setup.ps1 -SkipOpenCode   # 只装 Python 环境（用 runner / Claude Code 的人）

脚本做的事：找/装 Python 3.12 → 建 .venv 装依赖 → 跑冒烟测试 →
生成 runner 配置 → （可选）装 Node + OpenCode → 检查 API key 配置。
全程幂等，重复运行安全。
#>
param(
    [switch]$SkipOpenCode,
    [switch]$Yes
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Confirm-Step($msg) {
    if ($Yes) { return $true }
    $r = Read-Host "$msg [Y/n]"
    return ($r -eq "" -or $r -match "^[Yy]")
}

Write-Host ""
Write-Host "=== AI4Research 一键部署 ===" -ForegroundColor Cyan

# ---- 1. Python ----
$py = $null
foreach ($v in @("Python313", "Python312", "Python311")) {
    $c = "$env:LOCALAPPDATA\Programs\Python\$v\python.exe"
    if (Test-Path $c) { $py = $c; break }
}
if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") { $py = $cmd.Source }
}
if (-not $py) {
    if (-not (Confirm-Step "未找到 Python。用 winget 安装 Python 3.12（python.org 官方包，用户级）？")) {
        throw "需要 Python 3.11+。请自行安装后重新运行本脚本。"
    }
    winget install --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $py)) { throw "Python 安装未成功，请手动安装后重跑。" }
}
Write-Host "[1/6] Python: $py"

# ---- 2. venv + 依赖 ----
if (-not (Test-Path ".venv")) {
    Write-Host "[2/6] 创建虚拟环境..."
    & $py -m venv .venv
}
Write-Host "[2/6] 安装依赖（首次需下载约 150 MB：numpy/scipy/sympy/nashpy，请耐心）"
Write-Host "      若下载太慢，可 Ctrl+C 中止，运行下面一行配置国内镜像后重新双击 setup.bat："
Write-Host "      .venv\Scripts\python.exe -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple"
& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败（多为网络问题）——配置上面的镜像后重跑。" }

# ---- 3. 冒烟测试 ----
& .\.venv\Scripts\python.exe verifiers\search\counterexample_search.py --spec problems/_template/specs/c000_demo.json
if ($LASTEXITCODE -ne 0) { throw "冒烟测试失败——请把上面的输出发给维护者。" }
& .\.venv\Scripts\python.exe verifiers\gate.py --all
if ($LASTEXITCODE -ne 0) { throw "全树证据门禁失败——请检查上面的 claim/evidence 绑定。" }
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) { throw "框架单元测试失败——请把上面的输出发给维护者。" }
Write-Host "[3/6] 验证器、全树门禁与框架测试通过"

# ---- 4. runner 配置 ----
if (-not (Test-Path "runner\config.yaml")) {
    Copy-Item runner\config.example.yaml runner\config.yaml
    Write-Host "[4/6] 已生成 runner\config.yaml（默认 DeepSeek，可编辑换厂商）"
} else {
    Write-Host "[4/6] runner\config.yaml 已存在，跳过"
}

# ---- 5. OpenCode（可选） ----
if (-not $SkipOpenCode) {
    $oc = Get-Command opencode -ErrorAction SilentlyContinue
    $ocHealthy = $false
    if ($oc) {
        try {
            & $oc.Source --version *> $null
            $ocHealthy = ($LASTEXITCODE -eq 0)
        } catch {
            $ocHealthy = $false
        }
    }
    if ($ocHealthy) {
        Write-Host "[5/6] OpenCode 已安装且可运行：$($oc.Source)"
    } elseif (Confirm-Step "未找到可运行的 OpenCode。经 npm 安装/修复？没有 Node 会先装 Node LTS") {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
        if (-not $npm) {
            winget install --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw "Node.js 安装失败。" }
        }
        $npmExe = "$env:ProgramFiles\nodejs\npm.cmd"
        if (Get-Command npm -ErrorAction SilentlyContinue) { $npmExe = (Get-Command npm).Source }
        & $npmExe install -g opencode-ai
        if ($LASTEXITCODE -ne 0) { throw "OpenCode npm 安装失败。" }
        Write-Host "[5/6] OpenCode 安装完成；请新开终端运行 opencode --version 确认"
    } else {
        Write-Host "[5/6] 跳过 OpenCode"
    }
} else {
    Write-Host "[5/6] 跳过 OpenCode（-SkipOpenCode）"
}

# ---- 6. API key（不在安装脚本中读取或回显秘密） ----
if ($env:DEEPSEEK_API_KEY) {
    Write-Host "[6/6] DEEPSEEK_API_KEY 已设置（未读取其内容）"
} else {
    Write-Host "[6/6] 未设置 DEEPSEEK_API_KEY；请稍后通过系统环境变量或密钥管理器配置"
}

Write-Host ""
Write-Host "=== 部署完成 ===" -ForegroundColor Green
Write-Host "接下来（新开一个终端，进入本目录）："
Write-Host "  用 OpenCode：   opencode        （接入你的模型后，直接用 /explore /ground 等命令）"
Write-Host "  用内置 runner： .venv\Scripts\python.exe -m runner.main `"/lit 你的主题`""
Write-Host "  用 Claude Code：claude          （有 Claude 订阅或 API 的话）"
Write-Host "使用说明见 README.md，研究纪律见 CLAUDE.md。"
