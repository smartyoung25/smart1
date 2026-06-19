# Stop hook: NEXT.md 마지막 커밋 해시 자동 갱신
$repoDir = 'C:/smart_farm'
$nextFile = "$repoDir/NEXT.md"

$hash = & git -C $repoDir log --oneline -1 2>$null
if (-not $hash) { exit 0 }

$content = [System.IO.File]::ReadAllText($nextFile, [System.Text.Encoding]::UTF8)
$updated = $content -replace '(> 생성: [^\r\n/]+/ )마지막 커밋: [^\r\n]+', "`${1}마지막 커밋: $hash"

if ($updated -ne $content) {
    [System.IO.File]::WriteAllText($nextFile, $updated, [System.Text.UTF8Encoding]::new($false))
}
