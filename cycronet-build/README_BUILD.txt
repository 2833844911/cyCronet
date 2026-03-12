================================================================================
  Cycronet 多平台构建目录
================================================================================

这是一个干净的构建目录,包含编译 Windows、Linux、macOS 三个平台 wheel 所需的全部文件。

📁 目录说明
-----------
src/            - Rust 源代码
python/         - Python 包源代码
proto/          - Protocol Buffers 定义
linux_deps/     - Linux NSS 依赖库 (9 个 .so 文件)
cronet-libs/    - Cronet 原生库文件
  ├── windows/  - cronet.144.0.7506.0.dll (17MB)
  ├── linux/    - libcronet.144.0.7506.0.so (23MB)
  └── macos/    - libcronet.144.0.7506.0.dylib (19MB)

🚀 快速开始
-----------
1. 确保已安装: Rust, Python 3.8+, Maturin, cargo-zigbuild, Docker Desktop
2. 运行构建脚本:
   .\build_all.ps1 -Platform all

📦 生成的 Wheel
--------------
target/wheels/
├── cycronet-144.0.27-cp38-abi3-win_amd64.whl (~8.3MB)
├── cycronet-144.0.27-cp38-abi3-manylinux_2_24_x86_64.whl (~22MB)
└── cycronet-144.0.27-cp38-abi3-macosx_11_0_arm64.whl (~8.7MB)

📖 详细文档
-----------
- BUILD_INSTRUCTIONS.md - 完整构建说明
- build_ALL.md - 详细构建文档
- CHECKLIST.md - 文件清单

⚠️ 重要提示
-----------
- Linux wheel 较大是因为包含了所有 NSS/NSPR 依赖库
- manylinux_2_24 支持 GLIBC 2.24+ (Ubuntu 16.04+, Debian 9+, CentOS 8+)
- 所有 wheel 支持 Python 3.8-3.13 (abi3)

================================================================================
