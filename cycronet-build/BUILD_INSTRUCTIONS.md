# Cycronet Build Directory

这是一个干净的构建目录,包含编译所有平台 wheel 所需的全部文件。

## 📁 目录结构

```
cycronet-build/
├── src/                    # Rust 源代码
├── python/                 # Python 包源代码
│   └── cycronet/
│       ├── __init__.py              # 81 行 - 主入口，导出公共 API
│       ├── _native_loader.py        # 原生库加载逻辑
│       ├── _utils.py                # 工具函数（header 排序、domain 匹配等）
│       ├── _types.py                # 类型定义
│       ├── _cookies.py              # Cookie 和 CookieJar 类
│       ├── _response.py             # Response 和异常类
│       ├── _session.py              # 同步 Session 类
│       ├── _async_session.py        # 异步 AsyncSession 类
│       ├── _client.py               # CronetClient 和 AsyncCronetClient 工厂函数（含 TLS 配置缓存优化）
│       ├── _api_sync.py             # 同步模块级函数
│       └── _api_async.py            # 异步模块级函数
├── proto/                  # Protocol Buffers 定义
├── linux_deps/             # Linux NSS 依赖库
├── cronet-libs/            # Cronet 原生库文件
│   ├── windows/
│   │   └── cronet.144.0.7506.0.dll
│   ├── linux/
│   │   └── libcronet.144.0.7506.0.so
│   └── macos/
│       └── libcronet.144.0.7506.0.dylib
├── cronet-bin/             # Cronet 头文件和版本信息
│   ├── include/            # Windows 头文件
│   ├── cronet.lib          # Windows 导入库
│   ├── linux/
│   │   ├── include/        # Linux 头文件
│   │   ├── libcronet.so    # Linux 链接库
│   │   └── VERSION
│   ├── mac/
│   │   ├── include/        # macOS 头文件
│   │   ├── libcronet.dylib # macOS 链接库
│   │   └── VERSION
│   └── VERSION
├── Cargo.toml              # Rust 项目配置
├── Cargo.lock              # Rust 依赖锁定
├── build.rs                # Rust 构建脚本
├── pyproject.toml          # Python 项目配置
├── LICENSE                 # 许可证
├── README.md               # 项目说明
├── build_ALL.md            # 详细构建文档
└── build_all.ps1           # 自动化构建脚本

生成的文件:
├── target/                 # Rust 编译输出
│   └── wheels/             # 生成的 wheel 文件
└── Cargo.lock              # 依赖锁定文件
```

## 🚀 快速开始

### 前置要求

1. **Rust 工具链**
   ```powershell
   # 安装 Rust
   winget install Rustlang.Rustup

   # 添加目标平台
   rustup target add x86_64-pc-windows-msvc
   rustup target add x86_64-unknown-linux-gnu
   rustup target add aarch64-apple-darwin
   ```

2. **Python 3.8+**
   ```powershell
   python --version  # 确认版本
   ```

3. **Maturin**
   ```powershell
   pip install maturin
   ```

4. **cargo-zigbuild** (用于 macOS 交叉编译)
   ```powershell
   pip install cargo-zigbuild
   ```

5. **Docker Desktop** (用于 Linux 编译)
   - 下载并安装 Docker Desktop for Windows
   - 启动 Docker Desktop

### 编译所有平台

使用自动化脚本:

```powershell
# 编译所有平台
.\build_all.ps1 -Platform all

# 或单独编译
.\build_all.ps1 -Platform windows
.\build_all.ps1 -Platform linux
.\build_all.ps1 -Platform macos
```

### 手动编译

#### Windows x86_64

```powershell
# 清理其他平台文件
Remove-Item python\cycronet\*.so -ErrorAction SilentlyContinue
Remove-Item python\cycronet\*.dylib -ErrorAction SilentlyContinue

# 复制 Windows DLL
Copy-Item cronet-libs\windows\cronet.144.0.7506.0.dll python\cycronet\ -Force

# 编译
maturin build --release
```

#### Linux x86_64 (manylinux_2_24)

```powershell
# 清理其他平台文件
Remove-Item python\cycronet\*.dll -ErrorAction SilentlyContinue
Remove-Item python\cycronet\*.dylib -ErrorAction SilentlyContinue

# 复制 Linux SO 和 NSS 依赖
Copy-Item cronet-libs\linux\libcronet.144.0.7506.0.so python\cycronet\ -Force
Copy-Item linux_deps\*.so python\cycronet\ -Force

# 使用 Docker 编译
docker run --rm `
  -v "${PWD}:/io" `
  -e LD_LIBRARY_PATH=/io/python/cycronet `
  ghcr.io/pyo3/maturin:latest `
  build --release --target x86_64-unknown-linux-gnu --compatibility manylinux_2_24
```

#### macOS ARM64

```powershell
# 清理其他平台文件
Remove-Item python\cycronet\*.dll -ErrorAction SilentlyContinue
Remove-Item python\cycronet\*.so -ErrorAction SilentlyContinue

# 复制 macOS dylib
Copy-Item cronet-libs\macos\libcronet.144.0.7506.0.dylib python\cycronet\ -Force

# 使用 cargo-zigbuild 交叉编译
maturin build --release --target aarch64-apple-darwin --zig
```

## 📦 生成的 Wheel 文件

编译完成后,wheel 文件位于 `target/wheels/`:

- `cycronet-144.0.27-cp38-abi3-win_amd64.whl` (~8.3MB)
- `cycronet-144.0.27-cp38-abi3-manylinux_2_24_x86_64.whl` (~22MB)
- `cycronet-144.0.27-cp38-abi3-macosx_11_0_arm64.whl` (~8.7MB)

所有 wheel 支持 Python 3.8-3.13 (abi3)。

## 🔍 验证 Wheel

```powershell
# 查看 wheel 内容
python -m zipfile -l target\wheels\cycronet-*.whl

# 测试安装
pip install target\wheels\cycronet-*.whl

# 测试导入
python -c "import cycronet; print(cycronet.__version__)"
```

## 📝 注意事项

1. **Linux wheel 较大** - manylinux_2_24 wheel 包含所有 NSS/NSPR 依赖库,确保在任何 GLIBC 2.24+ 系统上都能运行
2. **macOS 交叉编译** - 在 Windows 上使用 Zig 工具链交叉编译 macOS ARM64 版本
3. **Docker 要求** - Linux 编译需要 Docker Desktop 运行
4. **代理设置** - 如果网络需要代理,在 Docker 命令中添加代理环境变量

## 🐛 故障排除

### Docker 连接失败
```powershell
# 确保 Docker Desktop 正在运行
docker ps
```

### Rust 编译错误
```powershell
# 清理并重新编译
cargo clean
maturin build --release
```

### 依赖下载慢
```powershell
# 配置 Rust 国内镜像
# 编辑 ~/.cargo/config.toml
[source.crates-io]
replace-with = 'ustc'

[source.ustc]
registry = "https://mirrors.ustc.edu.cn/crates.io-index"
```

## 📚 更多信息

详细构建说明请参考 `build_ALL.md`。
