# 编译所有平台的 wheel
param(
    [ValidateSet("windows", "linux", "macos", "all")]
    [string]$Platform = "all"
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot  # 使用脚本所在目录

function Build-Windows {
    Write-Host "`n=== 编译 Windows x86_64 Wheel ===" -ForegroundColor Cyan
    cd $ProjectDir

    Write-Host "清理其他平台的库文件..." -ForegroundColor Yellow
    Remove-Item python\cycronet\*.so -ErrorAction SilentlyContinue
    Remove-Item python\cycronet\*.dylib -ErrorAction SilentlyContinue

    Write-Host "复制 Windows DLL..." -ForegroundColor Yellow
    Copy-Item cronet-libs\windows\cronet.144.0.7506.0.dll python\cycronet\ -Force

    Write-Host "开始构建..." -ForegroundColor Green
    maturin build --release

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Windows wheel 构建成功" -ForegroundColor Green
    } else {
        Write-Host "✗ Windows wheel 构建失败" -ForegroundColor Red
        exit 1
    }
}

function Build-Linux {
    Write-Host "`n=== 编译 Linux x86_64 Wheel (manylinux_2_24) ===" -ForegroundColor Cyan
    cd $ProjectDir

    Write-Host "清理其他平台的库文件..." -ForegroundColor Yellow
    Remove-Item python\cycronet\*.dll -ErrorAction SilentlyContinue
    Remove-Item python\cycronet\*.dylib -ErrorAction SilentlyContinue

    Write-Host "复制 Linux SO 和 NSS 依赖..." -ForegroundColor Yellow
    Copy-Item cronet-libs\linux\libcronet.144.0.7506.0.so python\cycronet\ -Force
    Copy-Item linux_deps\*.so python\cycronet\ -Force

    Write-Host "检查 Docker..." -ForegroundColor Yellow
    try {
        docker version | Out-Null
    } catch {
        Write-Host "✗ Docker 未运行，请启动 Docker Desktop" -ForegroundColor Red
        exit 1
    }

    Write-Host "开始构建（使用 Docker）..." -ForegroundColor Green
    $mountPath = $ProjectDir -replace '\\', '/'
    docker run --rm `
        -v "${mountPath}:/io" `
        -e LD_LIBRARY_PATH=/io/python/cycronet `
        ghcr.io/pyo3/maturin:latest `
        build --release --target x86_64-unknown-linux-gnu --compatibility manylinux_2_24

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Linux wheel 构建成功" -ForegroundColor Green
    } else {
        Write-Host "✗ Linux wheel 构建失败" -ForegroundColor Red
        exit 1
    }
}

function Build-MacOS {
    Write-Host "`n=== 编译 macOS ARM64 Wheel ===" -ForegroundColor Cyan
    cd $ProjectDir

    Write-Host "清理其他平台的库文件..." -ForegroundColor Yellow
    Remove-Item python\cycronet\*.dll -ErrorAction SilentlyContinue
    Remove-Item python\cycronet\*.so -ErrorAction SilentlyContinue

    Write-Host "复制 macOS dylib..." -ForegroundColor Yellow
    Copy-Item cronet-libs\macos\libcronet.144.0.7506.0.dylib python\cycronet\ -Force

    Write-Host "检查 Rust 目标..." -ForegroundColor Yellow
    $targets = rustup target list --installed
    if ($targets -notcontains "aarch64-apple-darwin") {
        Write-Host "安装 aarch64-apple-darwin 目标..." -ForegroundColor Yellow
        rustup target add aarch64-apple-darwin
    }

    Write-Host "开始构建（使用 zig 交叉编译）..." -ForegroundColor Green
    maturin build --release --target aarch64-apple-darwin --zig

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ macOS wheel 构建成功" -ForegroundColor Green
    } else {
        Write-Host "✗ macOS wheel 构建失败" -ForegroundColor Red
        exit 1
    }
}

# 主逻辑
Write-Host "=== Cycronet 多平台 Wheel 构建工具 ===" -ForegroundColor Cyan
Write-Host "项目目录: $ProjectDir" -ForegroundColor White

switch ($Platform) {
    "windows" { Build-Windows }
    "linux" { Build-Linux }
    "macos" { Build-MacOS }
    "all" {
        Build-Windows
        Build-Linux
        Build-MacOS
    }
}

# 显示构建结果
Write-Host "`n=== 构建完成 ===" -ForegroundColor Green
Write-Host "`n最近构建的 Wheel 文件:" -ForegroundColor Cyan

Get-ChildItem "$ProjectDir\target\wheels\*.whl" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 |
    ForEach-Object {
        $sizeMB = [math]::Round($_.Length / 1MB, 2)
        $time = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        Write-Host "  $($_.Name)" -ForegroundColor White
        Write-Host "    大小: $sizeMB MB | 时间: $time" -ForegroundColor Gray
    }

Write-Host "`n下一步:" -ForegroundColor Cyan
Write-Host "  1. 测试 wheel: pip install target\wheels\cycronet-*.whl" -ForegroundColor White
Write-Host "  2. 上传到 PyPI: python -m twine upload target\wheels\cycronet-*.whl" -ForegroundColor White
