# 验证构建环境
Write-Host "=== Cycronet 构建环境检查 ===" -ForegroundColor Cyan

$allOk = $true

# 检查 Rust
Write-Host "`n检查 Rust..." -ForegroundColor Yellow
try {
    $rustVersion = rustc --version
    Write-Host "✓ Rust: $rustVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Rust 未安装" -ForegroundColor Red
    Write-Host "  安装: winget install Rustlang.Rustup" -ForegroundColor Gray
    $allOk = $false
}

# 检查 Python
Write-Host "`n检查 Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version
    Write-Host "✓ Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Python 未安装" -ForegroundColor Red
    $allOk = $false
}

# 检查 Maturin
Write-Host "`n检查 Maturin..." -ForegroundColor Yellow
try {
    $maturinVersion = maturin --version
    Write-Host "✓ Maturin: $maturinVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Maturin 未安装" -ForegroundColor Red
    Write-Host "  安装: pip install maturin" -ForegroundColor Gray
    $allOk = $false
}

# 检查 cargo-zigbuild
Write-Host "`n检查 cargo-zigbuild..." -ForegroundColor Yellow
try {
    $zigVersion = cargo zigbuild --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ cargo-zigbuild 已安装" -ForegroundColor Green
    } else {
        throw
    }
} catch {
    Write-Host "✗ cargo-zigbuild 未安装" -ForegroundColor Red
    Write-Host "  安装: pip install cargo-zigbuild" -ForegroundColor Gray
    $allOk = $false
}

# 检查 Docker
Write-Host "`n检查 Docker..." -ForegroundColor Yellow
try {
    docker version | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $dockerVersion = docker --version
        Write-Host "✓ Docker: $dockerVersion" -ForegroundColor Green
    } else {
        throw
    }
} catch {
    Write-Host "✗ Docker 未运行" -ForegroundColor Red
    Write-Host "  请启动 Docker Desktop" -ForegroundColor Gray
    $allOk = $false
}

# 检查 Rust 目标
Write-Host "`n检查 Rust 目标..." -ForegroundColor Yellow
$targets = rustup target list --installed

$requiredTargets = @(
    "x86_64-pc-windows-msvc",
    "x86_64-unknown-linux-gnu",
    "aarch64-apple-darwin"
)

foreach ($target in $requiredTargets) {
    if ($targets -contains $target) {
        Write-Host "✓ $target" -ForegroundColor Green
    } else {
        Write-Host "✗ $target 未安装" -ForegroundColor Red
        Write-Host "  安装: rustup target add $target" -ForegroundColor Gray
        $allOk = $false
    }
}

# 检查库文件
Write-Host "`n检查 Cronet 库文件..." -ForegroundColor Yellow
$libFiles = @(
    "cronet-libs\windows\cronet.144.0.7506.0.dll",
    "cronet-libs\linux\libcronet.144.0.7506.0.so",
    "cronet-libs\macos\libcronet.144.0.7506.0.dylib"
)

foreach ($lib in $libFiles) {
    if (Test-Path $lib) {
        $size = [math]::Round((Get-Item $lib).Length / 1MB, 2)
        Write-Host "✓ $lib ($size MB)" -ForegroundColor Green
    } else {
        Write-Host "✗ $lib 缺失" -ForegroundColor Red
        $allOk = $false
    }
}

# 检查 Linux 依赖
Write-Host "`n检查 Linux NSS 依赖..." -ForegroundColor Yellow
$nssLibs = Get-ChildItem "linux_deps\*.so" -ErrorAction SilentlyContinue
if ($nssLibs.Count -eq 9) {
    Write-Host "✓ 找到 $($nssLibs.Count) 个 NSS 库文件" -ForegroundColor Green
} else {
    Write-Host "✗ NSS 库文件不完整 (应该有 9 个,实际 $($nssLibs.Count) 个)" -ForegroundColor Red
    $allOk = $false
}

# 总结
Write-Host "`n=== 检查结果 ===" -ForegroundColor Cyan
if ($allOk) {
    Write-Host "✓ 所有检查通过,可以开始构建!" -ForegroundColor Green
    Write-Host "`n运行构建:" -ForegroundColor Cyan
    Write-Host "  .\build_all.ps1 -Platform all" -ForegroundColor White
} else {
    Write-Host "✗ 部分检查失败,请先解决上述问题" -ForegroundColor Red
    exit 1
}
