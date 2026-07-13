# cyCronet 150.1.0 TLS Signature Algorithms 修改导出

导出时间：2026-07-10

## 目录内容

- `patches/01-cycronet-source-150.1.0-default-chrome150.patch`
  - cyCronet Python/Rust 封装层修改。
  - 版本号改为 `150.1.0`。
  - 默认 `chrometls` 改为 `chrome_150`。
  - 新增 `chrome_150` TLS profile。
  - 把 `signature_algorithms` 从 `tls_profiles.json` 传到 Cronet experimental options 的 `tls_signature_algorithms`。

- `patches/02-chromium-cronet-tls-signature-algorithms.patch`
  - Chromium/Cronet 侧修改。
  - 新增 `TLSSignatureAlgorithmMapper`。
  - 解析 Cronet experimental option `tls_signature_algorithms`。
  - 写入 `net::SSLContextConfig::custom_signature_algorithm_prefs`。
  - `SSLClientSocketImpl` 优先使用自定义 signature_algorithms。

- `patches/03-boringssl-allow-extra-verify-sigalgs.patch`
  - BoringSSL 侧修改。
  - 只在 verify signature algorithms 里额外允许 `0x0904/0x0905/0x0906`。
  - signing algorithm prefs 仍拒绝这些未知值。

- `artifacts/cycronet-150.1.0-cp38-abi3-macosx_11_0_arm64.whl`
  - 已编译好的 macOS arm64 pip wheel。

- `artifacts/libcronet.144.0.7506.0.dylib`
  - 同步给 cyCronet 使用的新 Cronet dylib。

- `artifacts/libcronet.144.0.7506.0.chromium-out.dylib`
  - 从 Chromium `out/Cronet_Mac` 直接复制出的 dylib。

- `artifacts/SHA256SUMS.txt`
  - 产物校验值。

## 应用补丁

cyCronet 仓库根目录：

```bash
cd /Volumes/D/myxm/cyCronet
git apply /Volumes/D/myxm/cyCronet/cycronet-build/export_150_1_0_tls_signature/patches/01-cycronet-source-150.1.0-default-chrome150.patch
```

Chromium 仓库根目录：

```bash
cd /Volumes/D/chromeyuanm/chromium/src
git apply /Volumes/D/myxm/cyCronet/cycronet-build/export_150_1_0_tls_signature/patches/02-chromium-cronet-tls-signature-algorithms.patch
```

BoringSSL 仓库根目录：

```bash
cd /Volumes/D/chromeyuanm/chromium/src/third_party/boringssl/src
git apply /Volumes/D/myxm/cyCronet/cycronet-build/export_150_1_0_tls_signature/patches/03-boringssl-allow-extra-verify-sigalgs.patch
```

注意：当前工作树已经应用了这些修改，所以在当前机器上直接 `git apply --check` 会因为补丁已存在而失败。补丁用于干净基线或移植到其它工作树。

## 编译命令

重新生成 Chromium/Cronet 构建文件：

```bash
cd /Volumes/D/chromeyuanm/chromium/src
/Volumes/D/chromeyuanm/chromium/src/buildtools/mac/gn gen out/Cronet_Mac
```

编译 Cronet dylib：

```bash
/Volumes/D/chromeyuanm/chromium/src/third_party/depot_tools/autoninja -C out/Cronet_Mac cronet
```

同步 dylib 到 cyCronet：

```bash
cd /Volumes/D/myxm/cyCronet/cycronet-build
cp -f /Volumes/D/chromeyuanm/chromium/src/out/Cronet_Mac/libcronet.144.0.7506.0.dylib cronet-bin/mac/libcronet.dylib
cp -f /Volumes/D/chromeyuanm/chromium/src/out/Cronet_Mac/libcronet.144.0.7506.0.dylib cronet-libs/macos/libcronet.144.0.7506.0.dylib
cp -f /Volumes/D/chromeyuanm/chromium/src/out/Cronet_Mac/libcronet.144.0.7506.0.dylib python/cycronet/libcronet.144.0.7506.0.dylib
```

构建 pip wheel：

```bash
cd /Volumes/D/myxm/cyCronet/cycronet-build
tmpfile=$(mktemp /tmp/libcronet-so-pkg.XXXXXX)
mv python/cycronet/libcronet.144.0.7506.0.so.pkg "$tmpfile"
CONDA_PREFIX=/Volumes/D/app/anaconda3 PATH="$HOME/.cargo/bin:/Volumes/D/app/anaconda3/bin:$PATH" \
  /Volumes/D/app/anaconda3/bin/python -m maturin build --release
mv "$tmpfile" python/cycronet/libcronet.144.0.7506.0.so.pkg
```

临时移走 `.so.pkg` 是为了避免 Linux 包产物混入 macOS wheel。

## 关键行为

默认 profile：

```text
chrometls = "chrome_150"
```

`chrome_150` 的 `signature_algorithms`：

```text
0x0904
0x0905
0x0906
ecdsa_secp256r1_sha256
rsa_pss_rsae_sha256
rsa_pkcs1_sha256
0x0503
rsa_pss_rsae_sha384
rsa_pkcs1_sha384
rsa_pss_rsae_sha512
0x0601
```

## 测试结果

wheel 安装测试：

```text
version 150.1.0
client_default chrome_150
get_default chrome_150
```

`https://tls.tsvmp.com:38080/cbbiyhh`：

```text
status 200
signature_algorithms:
Unknown(0x0904)
Unknown(0x0905)
Unknown(0x0906)
ecdsa_secp256r1_sha256
rsa_pss_rsae_sha256
rsa_pkcs1_sha256
Unknown(0x0503)
rsa_pss_rsae_sha384
rsa_pkcs1_sha384
rsa_pss_rsae_sha512
Unknown(0x0601)
match True
```

`https://tls.peet.ws/api/all`，使用 `chrome_150`：

```text
http_version h2
akamai_fingerprint:
1:65536;2:0;4:6291456;6:262144|15663105|0|m,a,s,p

akamai_fingerprint_hash:
52d84b11737d980aef856699f885ca86
```

同一 wheel 中对比测试时，`chrome_144` 访问 peet 出现过 `net::ERR_CONNECTION_RESET`，`chrome_150` 正常返回 200。

## 未包含的已有改动

Chromium 工作树里存在以下 websocket 相关修改，它们不是本次 TLS signature_algorithms 修改的一部分，因此没有导出到补丁：

```text
components/cronet/native/cronet_websocket.cc
components/cronet/native/cronet_websocket.h
components/cronet/native/include/cronet_websocket_c.h
```
