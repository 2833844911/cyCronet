# Cycronet Build Directory - File Checklist

## ✅ 核心文件清单

### 📋 配置文件
- [x] Cargo.toml - Rust 项目配置
- [x] Cargo.lock - Rust 依赖锁定
- [x] pyproject.toml - Python 项目配置
- [x] build.rs - Rust 构建脚本

### 📁 源代码
- [x] src/ - Rust 源代码目录
  - [x] lib.rs - 库入口
  - [x] python.rs - Python 绑定
  - [x] cronet.rs - Cronet FFI 封装
  - [x] service.rs - 服务层
  - [x] cronet_bindings_linux.rs - Linux 预生成绑定
  - [x] cronet_bindings_mac.rs - macOS 预生成绑定
  - [x] cronet_proto_linux.rs - Linux Proto 绑定
  - [x] cronet_proto_mac.rs - macOS Proto 绑定

- [x] python/ - Python 包源代码
  - [x] cycronet/__init__.py - Python 包入口
  - [x] cycronet/__init__.pyi - 类型提示
  - [x] cycronet/tls_profiles.json - TLS 配置

- [x] proto/ - Protocol Buffers 定义
  - [x] cronet_engine.proto

### 📚 原生库文件
- [x] cronet-libs/windows/cronet.144.0.7506.0.dll (17MB)
- [x] cronet-libs/linux/libcronet.144.0.7506.0.so (23MB)
- [x] cronet-libs/macos/libcronet.144.0.7506.0.dylib (19MB)

### 📂 构建依赖文件
- [x] cronet-bin/ - Cronet 头文件和版本信息
  - [x] include/ - Windows 头文件
  - [x] cronet.lib - Windows 导入库 (85KB)
  - [x] linux/include/ - Linux 头文件
  - [x] linux/libcronet.so - Linux 链接库 (23MB)
  - [x] linux/VERSION
  - [x] mac/include/ - macOS 头文件
  - [x] mac/libcronet.dylib - macOS 链接库 (19MB)
  - [x] mac/VERSION
  - [x] VERSION - 版本信息文件

### 🔐 Linux NSS 依赖库
- [x] linux_deps/libnspr4.so
- [x] linux_deps/libplc4.so
- [x] linux_deps/libplds4.so
- [x] linux_deps/libnssutil3.so
- [x] linux_deps/libfreebl3.so
- [x] linux_deps/libfreeblpriv3.so
- [x] linux_deps/libsoftokn3.so
- [x] linux_deps/libnss3.so
- [x] linux_deps/libnssdbm3.so

### 📖 文档
- [x] README.md - 项目说明
- [x] BUILD_INSTRUCTIONS.md - 构建说明
- [x] build_ALL.md - 详细构建文档
- [x] LICENSE - MIT 许可证

### 🛠️ 构建脚本
- [x] build_all.ps1 - PowerShell 自动化构建脚本

## 📊 文件统计

```
总文件数: ~40 个
总大小: ~60 MB (包含所有原生库)

按类型分类:
- Rust 源文件: 8 个
- Python 源文件: 3 个
- 配置文件: 4 个
- 原生库: 12 个 (3 个 Cronet + 9 个 NSS)
- 文档: 4 个
- 脚本: 1 个
```

## 🎯 构建目标

运行 `.\build_all.ps1 -Platform all` 将生成:

1. **Windows x86_64**
   - cycronet-144.0.27-cp38-abi3-win_amd64.whl (~8.3MB)

2. **Linux x86_64 (manylinux_2_24)**
   - cycronet-144.0.27-cp38-abi3-manylinux_2_24_x86_64.whl (~22MB)
   - 包含所有 NSS 依赖,支持 GLIBC 2.24+

3. **macOS ARM64**
   - cycronet-144.0.27-cp38-abi3-macosx_11_0_arm64.whl (~8.7MB)

所有 wheel 支持 Python 3.8-3.13 (abi3)。

## ⚠️ 注意事项

1. **不要修改 cronet-libs/ 目录** - 这些是预编译的 Cronet 库
2. **不要修改 linux_deps/ 目录** - 这些是 Linux 必需的 NSS 依赖
3. **构建前确保 Docker Desktop 运行** - Linux 编译需要
4. **保持目录结构** - 构建脚本依赖相对路径

## 🔄 更新库文件

如果需要更新 Cronet 库到新版本:

1. 替换 `cronet-libs/` 中的对应文件
2. 更新 `pyproject.toml` 中的版本号
3. 重新运行构建脚本

## 📝 版本信息

- Cronet 版本: 144.0.7506.0
- Python 包版本: 144.0.27
- 支持的 Python 版本: 3.8-3.13
- 支持的平台: Windows x64, Linux x64, macOS ARM64
