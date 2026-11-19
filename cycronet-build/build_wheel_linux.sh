#!/usr/bin/env bash
# 在 Linux x86_64 上用当前检出的代码直接打 wheel，不需要手动拷任何文件。
#
#   ./build_wheel_linux.sh                  # 用 Docker 打 manylinux_2_24 wheel（发布用）
#   ./build_wheel_linux.sh local            # 用本机的 maturin 打，仅供本机测试（不是 manylinux）
#   ./build_wheel_linux.sh prepare          # 只把依赖库放进 python/cycronet，不编译
#   ./build_wheel_linux.sh check [wheel]    # 检查 wheel 是否完整；不带参数时检查 target/wheels 里本版本的
#
# 产物在 target/wheels/。打完会自动检查；检查不过的文件会被删掉，脚本以非 0 退出，
# 所以只要脚本最后打印了"已生成并通过检查"，那个文件就是完整的。
#
# 环境变量：
#   MATURIN_IMAGE                         Docker 镜像，默认 ghcr.io/pyo3/maturin:v1.12.6
#                                         （152.0.1、157.0.1 用的就是这个版本）
#   HTTP_PROXY / HTTPS_PROXY / NO_PROXY   设置了就传给容器，用来下载 crates
#                                         （用 sudo 运行时要加 -E，否则这些变量会被 sudo 清掉）
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
    docker | local | prepare | check) ;;
    *)
        echo "用法: $0 [docker|local|prepare|check [wheel]]" >&2
        exit 2
        ;;
esac

VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)"
[ -n "$VERSION" ] || { echo "读不到 pyproject.toml 里的 version" >&2; exit 1; }

sha8() { (sha256sum "$1" 2>/dev/null || shasum -a 256 "$1") | cut -c1-8; }

# 检查一个 wheel 是否完整、内容是否和当前检出的代码一致。通过返回 0，否则返回 1。
# maturin 在修复步骤失败时会留下一个 22 字节的空 zip（文件名和正常的 wheel 一样），
# 光看文件在不在会把它当成成功的产物，所以这里要真的打开检查。
check_wheel() {
    command -v python3 >/dev/null || { echo "检查 wheel 需要 python3" >&2; return 1; }
    python3 - "$1" "$VERSION" "cronet-libs/linux/$VERSIONED_SO" "$PKG_DIR/tls_profiles.json" <<'PY'
import base64, csv, hashlib, os, sys, zipfile

wheel, version, libcronet_ref, json_ref = sys.argv[1:5]
sha = lambda data: hashlib.sha256(data).hexdigest()
size = os.path.getsize(wheel)
name = os.path.basename(wheel)

try:
    z = zipfile.ZipFile(wheel)
except zipfile.BadZipFile as e:
    print(f"  不合格 {name}: 不是有效的 zip（{e}）")
    sys.exit(1)
names = z.namelist()
if not names:
    print(f"  不合格 {name}: 只有 {size} 字节，是空的 zip。这是构建中途失败后留下的文件，不是 wheel，不能上传。")
    sys.exit(1)

problems, notes = [], []
bad_member = z.testzip()
if bad_member is not None:
    problems.append(f"压缩包里的 {bad_member} 已损坏")

# 元数据里的版本号要和 pyproject.toml 一致
meta = [n for n in names if n.endswith(".dist-info/METADATA")]
if not meta:
    problems.append("缺少 METADATA")
else:
    wheel_version = next((l.split(":", 1)[1].strip() for l in z.read(meta[0]).decode("utf-8", "replace").splitlines()
                          if l.startswith("Version:")), "?")
    if wheel_version != version:
        problems.append(f"wheel 里的版本是 {wheel_version}，pyproject.toml 里是 {version}")
    else:
        notes.append(f"版本 {wheel_version}")

# RECORD 里登记的每个文件的哈希都要对得上
record = [n for n in names if n.endswith(".dist-info/RECORD")]
if not record:
    problems.append("缺少 RECORD")
else:
    checked = bad = 0
    for path, digest, _size in csv.reader(z.read(record[0]).decode("utf-8").splitlines()):
        if not digest:
            continue
        algo, b64 = digest.split("=", 1)
        try:
            got = base64.urlsafe_b64encode(hashlib.new(algo, z.read(path)).digest()).rstrip(b"=").decode()
        except KeyError:
            bad += 1
            continue
        checked += 1
        bad += got != b64
    if bad:
        problems.append(f"RECORD 里有 {bad} 个文件的哈希对不上")
    else:
        notes.append(f"RECORD {checked} 项校验通过")

# 扩展、原生库、profile 文件要在，且和仓库里的一致
if "cycronet/cronet_cloak.abi3.so" not in names:
    problems.append("缺少 cycronet/cronet_cloak.abi3.so（Rust 扩展）")
for member, ref, label in (
    (f"cycronet/{os.path.basename(libcronet_ref)}", libcronet_ref, "libcronet"),
    ("cycronet/tls_profiles.json", json_ref, "tls_profiles.json"),
):
    if member not in names:
        problems.append(f"缺少 {member}")
    elif sha(z.read(member)) != sha(open(ref, "rb").read()):
        problems.append(f"{label} 和仓库里的（{ref}）不一致")
    else:
        notes.append(f"{label} 与仓库一致（{sha(z.read(member))[:8]}）")

# manylinux 包里，auditwheel 修复会把 libcronet 嫁接进 cycronet.libs/，扩展靠它找到 libcronet
if "manylinux" in name:
    grafted = [n for n in names if n.startswith("cycronet.libs/")]
    if not any(os.path.basename(n).startswith("libcronet-") for n in grafted):
        problems.append("cycronet.libs/ 里没有 libcronet-<hash>.so，auditwheel 修复没有完成")
    else:
        notes.append(f"cycronet.libs/ 里有 {len(grafted)} 个嫁接的库")

with open(wheel, "rb") as f:
    wheel_sha = hashlib.sha256(f.read()).hexdigest()
print(f"  {name}  {size / 1048576:.1f} MB  sha256 {wheel_sha[:16]}")
for n in notes:
    print(f"    ok  {n}")
for p in problems:
    print(f"    不合格  {p}")
sys.exit(1 if problems else 0)
PY
}

# --- 检查模式：不改动任何文件 ---
if [ "$MODE" = check ]; then
    if [ -n "${2:-}" ]; then
        check_wheel "$2"
        exit $?
    fi
    found=0
    rc=0
    for f in target/wheels/cycronet-"$VERSION"-*.whl; do
        [ -e "$f" ] || continue
        found=1
        check_wheel "$f" || rc=1
    done
    if [ "$found" -eq 0 ]; then
        echo "target/wheels 里没有 cycronet-$VERSION-*.whl" >&2
        exit 1
    fi
    exit "$rc"
fi

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

# --- 3. 清掉上一次的构建残留 ---
# maturin 的 auditwheel 修复会用 patchelf 原地改写编好的扩展：把 DT_NEEDED 里的
# libcronet.144.0.7506.0.so 改成 libcronet-<哈希>.144.0.7506.0.so。改过的文件留在 target/ 里，
# 下一次构建 cargo 判定"已经是最新的"（只花零点几秒），maturin 拿到的就是这个被改过的扩展，
# 修复时找不到那个带哈希的库，报 "required library libcronet-<哈希>...so could not be located"。
# 所以 Docker 构建每次都从空的 target/ 开始（和以前每次用全新目录打包的效果一致）。
rm -f target/wheels/cycronet-"$VERSION"-*.whl 2>/dev/null || true
if [ "$MODE" = docker ] && [ -e target ]; then
    echo "清理上一次的 target/ ..."
    rm -rf target 2>/dev/null || true
    if [ -e target ]; then
        # 上一次是 root（sudo 或容器）建的，当前用户删不掉，交给容器来删
        docker run --rm -v "$PWD:/io" --entrypoint rm "$IMAGE" -rf /io/target || true
    fi
    [ ! -e target ] || { echo "无法删除 target/，请先执行: sudo rm -rf target" >&2; exit 1; }
fi

# --- 4. 打包 ---
status=0
if [ "$MODE" = local ]; then
    command -v maturin >/dev/null || { echo "没找到 maturin，先 pip install maturin" >&2; exit 1; }
    maturin build --release --compatibility linux || status=$?
    PATTERN="cycronet-${VERSION}-cp38-abi3-linux_x86_64.whl"
else
    command -v docker >/dev/null || { echo "没找到 docker" >&2; exit 1; }
    proxy_args=()
    for v in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
        if [ -n "${!v:-}" ]; then
            proxy_args+=(-e "$v=${!v}")
        fi
    done

    docker run --rm \
        -v "$PWD:/io" \
        -e LD_LIBRARY_PATH=/io/python/cycronet \
        ${proxy_args[@]+"${proxy_args[@]}"} \
        "$IMAGE" \
        build --release --target x86_64-unknown-linux-gnu --compatibility manylinux_2_24 \
        || status=$?

    # 容器以 root 运行，把它写过的文件改回运行脚本的用户（用 sudo 运行时是 SUDO_UID），免得之后清理要 sudo
    docker run --rm -v "$PWD:/io" --entrypoint chown "$IMAGE" \
        -R "${SUDO_UID:-$(id -u)}:${SUDO_GID:-$(id -g)}" /io/target /io/python 2>/dev/null || true

    PATTERN="cycronet-${VERSION}-cp38-abi3-manylinux*_x86_64.whl"
fi

# --- 5. 检查产物：不看退出码，看文件本身 ---
echo
echo "检查产物："
WHEEL=""
for f in $(find target/wheels -maxdepth 1 -name "$PATTERN" 2>/dev/null | sort); do
    if check_wheel "$f"; then
        WHEEL="$f"
    else
        rm -f "$f" && echo "    已删除不合格的 $f" >&2
    fi
done

if [ -z "$WHEEL" ]; then
    echo >&2
    echo "打包失败：没有得到完整的 wheel（构建命令退出码 ${status}）。" >&2
    echo "把上面 maturin 输出的最后 20 行发出来排查。" >&2
    exit 1
fi
if [ "$status" -ne 0 ]; then
    echo "注意：构建命令退出码是 ${status}，但上面这个 abi3 wheel 已经完整生成并通过检查，之后的失败（比如 PyPy）可以忽略。" >&2
fi
echo
echo "已生成并通过检查："
ls -l "$WHEEL"
