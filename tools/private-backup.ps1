# private-backup.ps1 —— 备份/恢复**插件目录里的私人文件**（A35，2026-09-27）
#
# 为什么要它：A35 起私人文件就在插件目录里（<包>/local、<包>/agent/{output,docs/knowledge,
#   docs/archive}、<包>/state）。好处是"插件目录拷到哪都能跑"，代价是
#   **`dsh plugin add dsh-chat-digest@<新版本>` 会重建整个包目录 ⇒ 私人文件一起没**。
#   所以：**每次重装前后各跑一次**（先 -Backup，重装完 -Restore）。
#
# 用法：
#   pwsh tools/private-backup.ps1 -Backup  -To D:\backup\chat-digest     # 装之前
#   pwsh tools/private-backup.ps1 -Restore -From D:\backup\chat-digest   # 装完之后
# 只做复制（robocopy /E），**从不删除**源。
param(
  [switch]$Backup,
  [switch]$Restore,
  [string]$To,
  [string]$From,
  [string]$Pkg = "$env:USERPROFILE\.dsh\profiles\web\node_modules\dsh-chat-digest"
)
$items = @('local', 'state', 'agent\output', 'agent\docs\knowledge', 'agent\docs\archive', 'agent\docs\信息列表.md')
if ($Backup) {
  if (-not $To) { Write-Error '需要 -To <目录>'; exit 2 }
  foreach ($it in $items) { robocopy "$Pkg\$it" "$To\$it" /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null }
  Write-Output "已备份到 $To（rc=$LASTEXITCODE，0-7 都算成功）"
} elseif ($Restore) {
  if (-not $From) { Write-Error '需要 -From <目录>'; exit 2 }
  New-Item -ItemType Directory -Force -Path "$Pkg\local", "$Pkg\state" | Out-Null
  foreach ($it in $items) { robocopy "$From\$it" "$Pkg\$it" /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null }
  Write-Output "已从 $From 恢复（rc=$LASTEXITCODE，0-7 都算成功）"
} else { Write-Error '用 -Backup -To <目录> 或 -Restore -From <目录>'; exit 2 }
