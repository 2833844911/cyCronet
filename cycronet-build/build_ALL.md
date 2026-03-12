
---

## 🔨 从源码编译 Wheel

如果你需要从源码编译 Cycronet 的 wheel 包，以下是在 Windows 机器上为不同平台编译的完整指南。

### 前置要求

1. **Rust 工具链**
   ```powershell
   # 安装 Rust
   # 访问 https://rustup.rs/ 下载安装

   # 验证安装
   rustc --version
   cargo --version
   ```

2. **Python 和 Maturin**
   ```powershell
   pip install maturin
   ```

3. **交叉编译工具**
   ```powershell
   # 安装 cargo-zigbuild（用于 macOS 交叉编译）
   cargo install cargo-zigbuild

   # 安装 Docker Desktop（用于 Linux 交叉编译）
   # 下载：https://www.docker.com/products/docker-desktop/
   ```

### 📦 编译 Windows x86_64 Wheel

```powershell
# 1. 进入项目目录
cd cycronet-build

# 2. 清理其他平台的库文件
Remove-Item python\cycronet\*.so -ErrorAction SilentlyContinue
Remove-Item python\cycronet\*.dylib -ErrorAction SilentlyContinue

# 3. 复制 Windows DLL
Copy-Item cronet-libs\windows\cronet.144.0.7506.0.dll python\cycronet\ -Force

# 4. 构建 wheel
maturin build --release

# 5. 生成的 wheel 位于
# target\wheels\cycronet-144.0.x-cp38-abi3-win_amd64.whl
```

**验证**：
```powershell
# 查看 wheel 内容
python -m zipfile -l target\wheels\cycronet-*-win_amd64.whl | Select-String "cycronet/"

# 应该包含：
# - cycronet/__init__.py
# - cycronet/cronet_cloak.pyd
# - cycronet/cronet.144.0.7506.0.dll
# - cycronet/tls_profiles.json
```

### 🐧 编译 Linux x86_64 Wheel

```powershell
# 1. 进入项目目录
cd cycronet-build

# 2. 清理其他平台的库文件
Remove-Item python\cycronet\*.dll -ErrorAction SilentlyContinue
Remove-Item python\cycronet\*.dylib -ErrorAction SilentlyContinue

# 3. 复制 Linux SO 和 NSS 依赖库
Copy-Item cronet-libs\linux\libcronet.144.0.7506.0.so python\cycronet\ -Force
Copy-Item linux_deps\*.so python\cycronet\ -Force

# 4. 使用 Docker 构建 manylinux_2_24 wheel（支持 GLIBC 2.24+）
# 推荐：自动打包所有依赖，最大兼容性
docker run --rm `
  -v "${PWD}:/io" `
  -e LD_LIBRARY_PATH=/io/python/cycronet `
  ghcr.io/pyo3/maturin:latest `
  build --release --target x86_64-unknown-linux-gnu --compatibility manylinux_2_24

# 如果使用代理（可选）
docker run --rm `
  -v "${PWD}:/io" `
  -e LD_LIBRARY_PATH=/io/python/cycronet `
  -e HTTPS_PROXY=http://host.docker.internal:21882 `
  -e HTTP_PROXY=http://host.docker.internal:21882 `
  --add-host=host.docker.internal:host-gateway `
  ghcr.io/pyo3/maturin:latest `
  build --release --target x86_64-unknown-linux-gnu --compatibility manylinux_2_24

# 5. 生成的 wheel 位于
# target\wheels\cycronet-144.0.x-cp38-abi3-manylinux_2_24_x86_64.whl
```

**支持的 Linux 发行版**：
- Ubuntu 16.04+ (GLIBC 2.23+)
- Debian 9+ (GLIBC 2.24+)
- CentOS 8+ (GLIBC 2.28+)
- RHEL 8+
- 其他使用 GLIBC 2.24+ 的发行版

**验证**：
```powershell
# 查看 wheel 内容
python -m zipfile -l target\wheels\cycronet-*-manylinux*.whl | Select-String "cycronet"

# 应该包含：
# - cycronet/__init__.py
# - cycronet/cronet_cloak.abi3.so
# - cycronet/libcronet.144.0.7506.0.so
# - cycronet/lib*.so (NSS 依赖库)
# - cycronet/tls_profiles.json
# - cycronet.libs/ (maturin 自动打包的系统依赖)
```

**注意事项**：
- manylinux_2_24 wheel 会自动包含所有 NSS/NSPR 依赖库
- 生成的 wheel 较大（约 22MB），但无需用户手动安装依赖
- 包含完整的 SSL/TLS 证书校验支持

### 🍎 编译 macOS ARM64 Wheel

```powershell
# 1. 进入项目目录
cd cycronet-build

# 2. 清理其他平台的库文件
Remove-Item python\cycronet\*.dll -ErrorAction SilentlyContinue
Remove-Item python\cycronet\*.so -ErrorAction SilentlyContinue

# 3. 复制 macOS dylib
Copy-Item cronet-libs\macos\libcronet.144.0.7506.0.dylib python\cycronet\ -Force

# 4. 添加 macOS 交叉编译目标
rustup target add aarch64-apple-darwin

# 5. 构建 wheel（使用 zig 交叉编译）
maturin build --release --target aarch64-apple-darwin --zig

# 6. 生成的 wheel 位于
# target\wheels\cycronet-144.0.x-cp38-abi3-macosx_11_0_arm64.whl
```

**验证**：
```powershell
# 查看 wheel 内容
python -m zipfile -l target\wheels\cycronet-*-macosx*.whl | Select-String "cycronet/"

# 应该包含：
# - cycronet/__init__.py
# - cycronet/cronet_cloak.abi3.so (实际是 Mach-O ARM64 格式)
# - cycronet/libcronet.144.0.7506.0.dylib
# - cycronet/tls_profiles.json
```

### 📋 编译脚本总结

使用 `build_all.ps1` 自动化脚本：

```powershell
# 编译所有平台的 wheel
param(
    [ValidateSet("windows", "linux", "macos", "all")]
    [string]$Platform = "all"
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot  # 使用脚本所在目录

function Build-Windows {
    Write-Host "=== 编译 Windows x86_64 Wheel ===" -ForegroundColor Cyan
    cd $ProjectDir
    Remove-Item python\cycronet\*.so -ErrorAction SilentlyContinue
    Remove-Item python\cycronet\*.dylib -ErrorAction SilentlyContinue
    Copy-Item cronet-libs\windows\cronet.144.0.7506.0.dll python\cycronet\ -Force
    maturin build --release
}

function Build-Linux {
    Write-Host "=== 编译 Linux x86_64 Wheel (manylinux_2_24) ===" -ForegroundColor Cyan
    cd $ProjectDir
    Remove-Item python\cycronet\*.dll -ErrorAction SilentlyContinue
    Remove-Item python\cycronet\*.dylib -ErrorAction SilentlyContinue

    # 复制 libcronet.so 和 NSS 依赖库
    Copy-Item cronet-libs\linux\libcronet.144.0.7506.0.so python\cycronet\ -Force
    Copy-Item linux_deps\*.so python\cycronet\ -Force

    $mountPath = $ProjectDir -replace '\\', '/'
    docker run --rm `
        -v "${mountPath}:/io" `
        -e LD_LIBRARY_PATH=/io/python/cycronet `
        ghcr.io/pyo3/maturin:latest `
        build --release --target x86_64-unknown-linux-gnu --compatibility manylinux_2_24
}

function Build-MacOS {
    Write-Host "=== 编译 macOS ARM64 Wheel ===" -ForegroundColor Cyan
    cd $ProjectDir
    Remove-Item python\cycronet\*.dll -ErrorAction SilentlyContinue
    Remove-Item python\cycronet\*.so -ErrorAction SilentlyContinue
    Copy-Item cronet-libs\macos\libcronet.144.0.7506.0.dylib python\cycronet\ -Force

    maturin build --release --target aarch64-apple-darwin --zig
}

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

Write-Host "`n=== 编译完成 ===" -ForegroundColor Green
Get-ChildItem "$ProjectDir\target\wheels\*.whl" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 5 |
    ForEach-Object {
        $sizeMB = [math]::Round($_.Length / 1MB, 2)
        Write-Host "$($_.Name) ($sizeMB MB)" -ForegroundColor White
    }
```

**使用方法**：
```powershell
# 编译所有平台
.\build_all.ps1 -Platform all

# 只编译 Windows
.\build_all.ps1 -Platform windows

# 只编译 Linux
.\build_all.ps1 -Platform linux

# 只编译 macOS
.\build_all.ps1 -Platform macos
```

### 🧪 测试编译的 Wheel

**Windows**:
```powershell
pip install target\wheels\cycronet-*-win_amd64.whl
python -c "import cycronet; print(cycronet.get('https://httpbin.org/get').status_code)"
```

**Linux** (在 Linux 机器上):
```bash
pip install cycronet-*-linux_x86_64.whl
python3 -c "import cycronet; print(cycronet.get('https://httpbin.org/get').status_code)"
```

**macOS** (在 macOS ARM64 机器上):
```bash
pip install cycronet-*-macosx_11_0_arm64.whl
python3 -c "import cycronet; print(cycronet.get('https://httpbin.org/get').status_code)"
```

### 📝 注意事项

1. **版本号管理**: 版本号在 `pyproject.toml` 中定义
2. **库文件准备**: 确保对应平台的 Cronet 库文件在 `cronet-libs/` 目录中
3. **清理工作**: 每次切换平台编译前，务必清理 `python/cycronet/` 中其他平台的库文件
4. **Docker 要求**: Linux 编译需要 Docker Desktop 运行
5. **交叉编译限制**: macOS 交叉编译使用 zig，可能会有警告，但不影响使用

### 🔗 相关文档

- **BUILD_INSTRUCTIONS.md** - 完整构建说明
- **CHECKLIST.md** - 文件清单
- **START_HERE.txt** - 快速入门指南

---
