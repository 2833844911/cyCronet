#!/usr/bin/env bash
# 在 Linux x86_64 上用当前检出的代码直接打 wheel，不需要手动拷任何文件。
#
#   ./build_wheel_linux.sh            # 用 Docker 打 manylinux_2_24 wheel（发布用）
#   ./build_wheel_linux.sh local      # 用本机的 maturin 打，仅供本机测试（不是 manylinux）
#   ./build_wheel_linux.sh prepare    # 只把依赖库放进 python/cycronet，不编译
#
# 产物在 target/wheels/。
#
# 环境变量：
#   MATURIN_IMAGE                         Docker 镜像，默认 ghcr.io/pyo3/maturin:v1.12.6
#                                         （152.0.1、157.0.1 用的就是这个版本）
#   HTTP_PROXY / HTTPS_PROXY / NO_PROXY   设置了就传给容器，用来下载 crates
#
# 放进 wheel 的 Linux 库都在仓库里：
#   cronet-libs/linux/libcronet.144.0.7506.0.so   Cronet 原生库
#   linux_deps/*                                  NSS 依赖库，以及 libglib / libgobject / libffi / libpcre
set -euo pipefail

cd "$(dirname "$0")"

MODE="${1:-docker}"
IMAGE="${MATURIN_IMAGE:-ghcr.io/pyo3/maturin:v1.12.6}"
VERSIONED_SO="libcronet.144.0.7506.0.so"
PKG_DIR="python/cycronet"

case "$MODE" in
    docker | local | prepare) ;;
    *)
        echo "用法: $0 [docker|local|prepare]" >&2
        exit 2
        ;;
esac

sha8() { (sha256sum "$1" 2>/dev/null || shasum -a 256 "$1") | cut -c1-8; }

# --- 1. 检查 ---
for f in "cronet-bin/linux/libcronet.so" "cronet-libs/linux/$VERSIONED_SO"; do
    [ -f "$f" ] || { echo "缺少 $f" >&2; exit 1; }
done
# build.rs 链接和生成 .so.pkg 用 cronet-bin 里的，wheel 里放的是 cronet-libs 里的，两份必须一致
if ! cmp -s "cronet-bin/linux/libcronet.so" "cronet-libs/linux/$VERSIONED_SO"; then
    echo "cronet-bin/linux/libcronet.so 和 cronet-libs/linux/$VERSIONED_SO 内容不同" >&2
    exit 1
fi
[ -d linux_deps ] || { echo "缺少 linux_deps/" >&2; exit 1; }
if [ "$MODE" != prepare ] && [ "$(uname -m)" != x86_64 ]; then
    echo "libcronet 是 x86_64 的，当前机器是 $(uname -m)，不能打 wheel" >&2
    exit 1
fi

# --- 2. 准备 python/cycronet：先清掉旧版本和其他平台留下的库，再放入这次要打进 wheel 的库 ---
rm -f "$PKG_DIR"/lib*.so "$PKG_DIR"/lib*.so.* "$PKG_DIR"/*.dll "$PKG_DIR"/*.dylib
cp -f "cronet-libs/linux/$VERSIONED_SO" "$PKG_DIR/"
cp -f linux_deps/* "$PKG_DIR/"

echo "python/cycronet 里的 .so："
ls -1 "$PKG_DIR" | grep -F '.so' | sed 's/^/  /'
echo "libcronet sha256 前 8 位: $(sha8 "cronet-libs/linux/$VERSIONED_SO")"

if [ "$MODE" = prepare ]; then
    exit 0
fi

# --- 3. 打包 ---
VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)"
MARKER="$(mktemp)"
trap 'rm -f "$MARKER"' EXIT

if [ "$MODE" = local ]; then
    command -v maturin >/dev/null || { echo "没找到 maturin，先 pip install maturin" >&2; exit 1; }
    maturin build --release --compatibility linux
    PATTERN="cycronet-${VERSION}-cp38-abi3-linux_x86_64.whl"
else
    command -v docker >/dev/null || { echo "没找到 docker" >&2; exit 1; }
    proxy_args=()
    for v in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
        if [ -n "${!v:-}" ]; then
            proxy_args+=(-e "$v=${!v}")
        fi
    done

    status=0
    docker run --rm \
        -v "$PWD:/io" \
        -e LD_LIBRARY_PATH=/io/python/cycronet \
        ${proxy_args[@]+"${proxy_args[@]}"} \
        "$IMAGE" \
        build --release --target x86_64-unknown-linux-gnu --compatibility manylinux_2_24 \
        || status=$?

    # 容器以 root 运行，把它写过的文件改回当前用户，免得之后清理要 sudo
    docker run --rm -v "$PWD:/io" --entrypoint chown "$IMAGE" \
        -R "$(id -u):$(id -g)" /io/target /io/python 2>/dev/null || true

    PATTERN="cycronet-${VERSION}-cp38-abi3-manylinux*_x86_64.whl"
    if [ "$status" -ne 0 ]; then
        echo "注意：docker 退出码 $status。如果下面能看到 abi3 wheel，通常是 abi3 之后尝试打 PyPy wheel 失败，可以忽略。" >&2
    fi
fi

WHEEL="$(find target/wheels -name "$PATTERN" -newer "$MARKER" 2>/dev/null | head -1)"
if [ -z "$WHEEL" ]; then
    echo "没有生成 target/wheels/$PATTERN" >&2
    exit 1
fi
echo
echo "已生成："
ls -l "$WHEEL"
