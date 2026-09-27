# dev-check.ps1 — 一条命令诊断前端为什么打不开 localhost:5173
#
#   用法（在仓库根目录）：
#     pwsh -File scripts\dev-check.ps1
#   Windows PowerShell 5.1 亦可：
#     powershell -ExecutionPolicy Bypass -File scripts\dev-check.ps1
#
# 只读诊断：不改文件、不装东西、不起服务。

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$fe = Join-Path $root 'frontend-vue'

function Head($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [注意] $t" -ForegroundColor Yellow }
function Bad($t)  { Write-Host "  [问题] $t" -ForegroundColor Red }

Head "1. 运行环境"
foreach ($c in 'node', 'npm', 'pnpm') {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if (-not $cmd) {
        if ($c -eq 'pnpm') { Warn "pnpm 不在 PATH —— 用下面第 5 步的 npx 方案，或先运行 corepack enable pnpm" }
        else { Bad "$c 未安装" }
        continue
    }
    $v = (& $c --version 2>&1 | Select-Object -First 1)
    if ("$v" -match 'child_process|EPERM|Error') { Warn "$c 存在但调用失败：$v" }
    else { Ok "$c $v  ($($cmd.Source))" }
}

Head "2. 依赖是否装好"
foreach ($p in 'node_modules\vite\bin\vite.js', 'node_modules\vue\package.json', 'node_modules\leaflet\package.json', 'node_modules\pinia\package.json') {
    if (Test-Path (Join-Path $fe $p)) { Ok $p } else { Bad "$p 缺失 —— 需要在 frontend-vue 目录跑一次 pnpm install（或 npm install）" }
}
if (Test-Path (Join-Path $fe 'node_modules\.pnpm')) {
    Ok ("pnpm 布局存在（$((Get-ChildItem (Join-Path $fe 'node_modules\.pnpm') -Directory).Count) 个包）")
} elseif (Test-Path (Join-Path $fe 'node_modules')) {
    Warn "node_modules 存在但不是 pnpm 布局（可能是 npm 装的）—— 混用包管理器容易出现奇怪问题，建议统一用一种"
}

Head "3. 5173 端口现在是谁的"
$conns = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Warn "5173 已被占用：PID $($c.OwningProcess) $($proc.ProcessName)"
    }
    Write-Host "  → 若是残留的 node，先结束它：Stop-Process -Id <PID> -Force"
    Write-Host "  → 或直接换端口：pnpm dev --port 5174 --strictPort"
} else {
    Ok "5173 空闲（说明 dev server 没在跑；打不开是正常的，因为没人监听）"
}

Head "4. dist 构建产物新鲜度"
$dist = Join-Path $fe 'dist\index.html'
if (Test-Path $dist) {
    $distTime = (Get-Item $dist).LastWriteTime
    $srcTime = (Get-ChildItem (Join-Path $fe 'src') -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    Write-Host "  dist : $distTime"
    Write-Host "  src  : $srcTime"
    if ($srcTime -gt $distTime) { Warn "dist 比源码旧 —— 页面会用旧样式；要新界面必须重新 build（见第 5 步 B 方案）" }
    else { Ok "dist 不旧于源码" }
} else {
    Warn "还没有 dist（没 build 过）"
}

Head "5. 可用的启动方式（二选一，任选其一即可）"
Write-Host @"
  A) dev server（改代码即时生效，演示常用）
     cd "$fe"
     pnpm dev                                  # 终端停在 "Local: http://localhost:5173/" 才算起来
     # pnpm 不可用时改用：
     npx --yes vite@8 --port 5173 --strictPort
     # 地址栏用：http://127.0.0.1:5173/?api=http://127.0.0.1:8000

  B) 先构建再预览（最稳，dev server 起不来时用这个）
     cd "$fe"
     pnpm build      # 或 npx --yes vite@8 build
     pnpm preview    # 等价于 npx --yes vite@8 preview
     # 若预览端口不是 5173，按终端打印的地址打开，并加上 ?api=http://127.0.0.1:8000
"@

Head "6. 两个容易踩的点"
Write-Host "  · dev server 必须一直在前台跑：关掉那个终端窗口，页面就 404/打不开。"
Write-Host "  · 同一个终端里跑不了第二条命令；要开第二个终端（PowerShell 新窗口）再跑后端 uvicorn。"
Write-Host ""
