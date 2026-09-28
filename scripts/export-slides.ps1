<#
.SYNOPSIS
    Export every slide of the proposal deck to PNG, so the layout can be checked
    visually (overflow / overlap) instead of inferred from character counts.

.DESCRIPTION
    Handles the traps the quick 5-line version fell into:
      * works no matter which directory you run it from (paths are derived from
        this script's own location);
      * creates the output directory first — PowerPoint's Export() fails
        silently-ish if the folder does not exist;
      * checks the deck exists and reports clearly instead of leaving a null
        object that produces a confusing second error;
      * tries the plain path, a UNC-style path and an ASCII working copy, because
        COM Open() rejects some paths — notably ones containing CJK characters
        or spaces (error 0x80070003 "path not found");
      * if COM still refuses, says what to try next instead of pretending the
        deck is broken.

.EXAMPLE
    pwsh -File scripts\export-slides.ps1
    powershell -ExecutionPolicy Bypass -File scripts\export-slides.ps1
    # 或者在资源管理器里：右键 -> 使用 PowerShell 运行
#>
[CmdletBinding()]
param(
    [string]$Deck,
    [string]$OutDir = (Join-Path $env:TEMP 'pco-slides'),
    [int]$Width = 1600,
    [int]$Height = 900
)

$ErrorActionPreference = 'Stop'

function Fail([string]$msg) {
    Write-Host "[x] $msg" -ForegroundColor Red
    exit 1
}

# --- locate the deck: explicit -Deck, else relative to this script, else CWD ---
$here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$repo = Split-Path -Parent $here
if (-not $Deck) {
    $candidates = @(
        (Join-Path $repo 'proposal\PharmaColdOps-Proposal-Presentation-Final.pptx'),
        (Join-Path $here 'PharmaColdOps-Proposal-Presentation-Final.pptx'),
        (Join-Path (Get-Location).Path 'proposal\PharmaColdOps-Proposal-Presentation-Final.pptx')
    )
    $Deck = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Deck -or -not (Test-Path -LiteralPath $Deck)) {
    Fail "找不到 PPTX。请用 -Deck 指定，例如:`n    .\export-slides.ps1 -Deck `"D:\...\PharmaColdOps-Proposal-Presentation-Final.pptx`""
}
$Deck = (Resolve-Path -LiteralPath $Deck).Path
Write-Host "[i] 演示文稿: $Deck"
Write-Host "[i] 大小: $([math]::Round((Get-Item -LiteralPath $Deck).Length / 1MB, 2)) MB"

# --- output directory must exist BEFORE Export() ---
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    Write-Host "[i] 已创建输出目录: $OutDir"
}
Get-ChildItem -LiteralPath $OutDir -Filter *.png -ErrorAction SilentlyContinue | Remove-Item -Force

# --- PowerPoint COM ---
try {
    $ppt = New-Object -ComObject PowerPoint.Application
} catch {
    Fail "无法启动 PowerPoint COM（$($_.Exception.Message)）。请确认已安装桌面版 PowerPoint。"
}

$opened = $null
$usedPath = $null
try {
    # 1) the real path; 2) a UNC form; 3) an ASCII copy in TEMP
    $attempts = @($Deck, "\\localhost\$($Deck -replace ':', '$')")
    $ascii = Join-Path $OutDir 'deck-ascii.pptx'
    Copy-Item -LiteralPath $Deck -Destination $ascii -Force
    $attempts += $ascii

    foreach ($path in $attempts) {
        try {
            $opened = $ppt.Presentations.Open($path, $true, $false, $false)   # ReadOnly, Untitled, no window
            $usedPath = $path
            break
        } catch {
            Write-Host "[!] 打不开: $path" -ForegroundColor Yellow
        }
    }
    if (-not $opened) {
        Fail @"
PowerPoint 打开了，但拒绝打开这个文件（三种路径都试过）。
常见原因与对策：
  1) 文件被"来自网络"标记锁定 -> 右键文件属性 -> 勾选"解除锁定"；
  2) 受保护的视图/信任中心限制 -> PowerPoint 文件 > 选项 > 信任中心 > 受保护的视图，取消勾选；
  3) 路径含中文或空格（本机已复现）-> 确认上面的 ASCII 副本尝试未被跳过；
  4) 需要可见的桌面会话（远程/服务方式运行会失败）。
"@
    }

    Write-Host "[i] 打开成功（使用路径: $usedPath），共 $($opened.Slides.Count) 页"
    foreach ($s in $opened.Slides) {
        $file = Join-Path $OutDir ('slide-{0:d2}.png' -f $s.SlideIndex)
        # Export 目标目录必须已存在（上面已创建）；宽高按 16:9 给
        $s.Export($file, 'PNG', $Width, $Height)
    }
    $opened.Close()
} finally {
    try { $ppt.Quit() } catch { }
    Start-Sleep -Milliseconds 400
}

$made = Get-ChildItem -LiteralPath $OutDir -Filter 'slide-*.png' | Sort-Object Name
if (-not $made) { Fail "导出结束但没有生成任何 PNG（PowerPoint 可能闪退了）。" }

Write-Host ""
Write-Host "[ok] 导出 $($made.Count) 张到 $OutDir" -ForegroundColor Green
$made | ForEach-Object { "     {0}  {1,7:N0} KB" -f $_.Name, ($_.Length / 1KB) }
Write-Host ""
Write-Host "打开目录: $OutDir"
