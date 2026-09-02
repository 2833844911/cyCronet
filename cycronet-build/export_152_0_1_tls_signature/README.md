# cyCronet 152.0.1 Chrome 152 TLS 指纹修改导出

导出时间：2026-09-02

在 `export_150_1_0_tls_signature` 的基础上继续修改，参考 `cycronet-async` 分支的
`7c7d666 152版本tls更新`，补齐 macOS 的 Chrome 152 支持。

## 目录内容

- `patches/01-cycronet-source-152.0.1-default-chrome152.patch`
  - cyCronet Python 封装层修改。
  - 版本号改为 `152.0.1`。
  - 默认 `chrometls` 改为 `chrome_152`。
  - 新增 `chrome_152` TLS profile：`tls_extensions` 增加 `trust_anchors`，
    `signature_algorithms` 最前面增加 GREASE 值 `0x0a0a`。
  - `_native_loader.py` 增加 `GSETTINGS_BACKEND=memory`（仅影响 Linux）。

- `patches/02-chromium-cronet-trust-anchors-extension.patch`
  - Chromium/Cronet 侧修改。
  - `net::SSLContextConfig` 新增 `send_empty_trust_anchors`。
  - `SSLClientSocketImpl::Init()` 在没有配置 Trust Anchor IDs 时，
    按需调用 `SSL_set1_requested_trust_anchors(ssl, ptr, 0)` 发送空的
    `trust_anchors` 扩展（BoringSSL 允许空列表，扩展仍然会出现在 ClientHello）。
  - `CronetSSLConfigService` 增加 `send_empty_trust_anchors` 构造参数。
  - `cronet_context.cc` 识别 experimental option `tls_extensions` 中的
    `"trust_anchors"`。注意这里**不**关闭 `permute_extensions`，因为
    Chrome 152 依然会打乱扩展顺序，这一点和 `application_settings*` 分支不同。

- `patches/03-boringssl-allow-grease-verify-sigalgs.patch`
  - BoringSSL 侧修改，两部分。
  - 一、放行：在 150 版本已有的 `is_extra_advertised_sigalg()` 基础上，额外放行
    RFC 8701 的 GREASE 值（`(sigalg & 0x0f0f) == 0x0a0a`）。
    只有 verify signature algorithms 放行，signing algorithm prefs 仍然拒绝。
    如果不打这一部分，`SSL_set_verify_algorithm_prefs` 会因为 `0x0a0a`
    直接返回 0，`SSLClientSocketImpl::Init()` 返回 `ERR_UNEXPECTED`，
    `chrome_152` 下**所有** TLS 连接都会失败，不是降级而是硬失败。
  - 二、随机化：`ssl_grease_index_t` 新增 `ssl_grease_sigalg`，
    `tls12_add_verify_sigalgs()` 把 profile 里的 GREASE 值当作**占位符**，
    每次连接替换成 `ssl_get_grease_value(hs, ssl_grease_sigalg)` 生成的随机
    GREASE 值。只有客户端替换，服务端那条路径（CertificateRequest）不动，
    因为真实 Chrome 也不会在那里发 GREASE。
    没有这一部分的话，每次连接发的都是固定的 `0x0a0a`，
    而真实 Chrome 每次都随机 —— JA4 / PeetPrint 会忽略 GREASE 所以对得上，
    但看原始字节的检测器会发现这是个常量。

- `artifacts/cycronet-152.0.1-cp38-abi3-macosx_11_0_arm64.whl`
  - 已编译好的 macOS arm64 pip wheel。

- `artifacts/libcronet.144.0.7506.0.dylib`
  - 同步给 cyCronet 使用的新 Cronet dylib。

- `artifacts/libcronet.144.0.7506.0.chromium-out.dylib`
  - 从 Chromium `out/Cronet_Mac` 直接复制出的 dylib（与上面同一文件）。

- `artifacts/SHA256SUMS.txt`
  - 产物校验值。

## 应用补丁

补丁 02 / 03 是在 `export_150_1_0_tls_signature` 的补丁**之上**的增量，
干净基线上需要先应用 150 的补丁，再应用这里的补丁。

cyCronet 仓库根目录：

```bash
cd /Volumes/D/myxm/cyCronet
git apply /Volumes/D/myxm/cyCronet/cycronet-build/export_152_0_1_tls_signature/patches/01-cycronet-source-152.0.1-default-chrome152.patch
```

Chromium 仓库根目录：

```bash
cd /Volumes/D/chromeyuanm/chromium/src
git apply /Volumes/D/myxm/cyCronet/cycronet-build/export_152_0_1_tls_signature/patches/02-chromium-cronet-trust-anchors-extension.patch
```

BoringSSL 仓库根目录：

```bash
cd /Volumes/D/chromeyuanm/chromium/src/third_party/boringssl/src
git apply /Volumes/D/myxm/cyCronet/cycronet-build/export_152_0_1_tls_signature/patches/03-boringssl-allow-grease-verify-sigalgs.patch
```

注意：当前工作树已经应用了这些修改，所以在当前机器上直接 `git apply --check` 会因为
补丁已存在而失败。补丁用于干净基线或移植到其它工作树。想在当前机器上验证补丁是否精确，
可以用反向应用：

```bash
git apply --reverse --check <patch>
```

三个补丁都已经用这种方式验证过，可以干净地反向应用。

## 编译命令

重新生成 Chromium/Cronet 构建文件：

```bash
cd /Volumes/D/chromeyuanm/chromium/src
/Volumes/D/chromeyuanm/chromium/src/buildtools/mac/gn gen out/Cronet_Mac
```

编译 Cronet dylib：

```bash
cd /Volumes/D/chromeyuanm/chromium/src
PATH="/Volumes/D/chromeyuanm/chromium/src/third_party/depot_tools:$PATH" \
  autoninja -C out/Cronet_Mac cronet
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
chrometls = "chrome_152"
```

`chrome_152` 相对 `chrome_150` 的差异：

```text
tls_extensions:        [] -> ["trust_anchors"]
signature_algorithms:  最前面增加 "0x0a0a"
```

`chrome_152` 的 `signature_algorithms`：

```text
0x0a0a
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

`trust_anchors` 扩展号是 `0xca34`（十进制 51764），发送的是空列表。

`signature_algorithms` 里的 `0x0a0a` 是**占位符**，不是字面量。实际发出去的是
每次连接随机生成的 GREASE 值（`0x2a2a` / `0x7a7a` / `0xdada` …），和真实 Chrome 行为一致。
profile 里写任何一个 GREASE 值（`0xNaNa`）效果都一样。

## 测试结果

wheel 安装测试：

```text
version 152.0.1
CronetClient default chrome_152
AsyncCronetClient default chrome_152
get() default chrome_152
profiles ['chrome_152', 'chrome_150', 'chrome_144', 'chrome_145', 'chrome_146', 'chrome_147', 'chrome_133', 'chrome_126', 'chrome_test']
```

### 和本机真实 Chrome 152 对比

本机安装的 Chrome 版本：`152.0.7977.76`。用 headless Chrome 走同一个代理访问
`https://tls.peet.ws/api/all`，和 cycronet `chrome_152` 逐项对比：

```text
完全一致：
  ja4                      t13d1517h2_8daaf6152771_cb7bf5808d99
  ja4_r                    一致
  peetprint / hash         fc97c1cdfb1409c9a9326c1b726d1dee
  http2 akamai fp / hash   一致
  cipher suites            16 个，顺序一致
  tls_curves               4588-29-23-24
  supported_versions       一致
  扩展集合（17 个非 GREASE）一致，含 51764 (trust_anchors) 和 17613 (ALPS new)

只差随机值（双方都随机，属于正常）：
  ja3 / ja3_hash    扩展顺序每次连接都不同，真实 Chrome 自己两次也对不上
  cipher GREASE     chrome 0x1A1A / cycronet 0x9A9A
  ext GREASE        chrome 0x3a3a,0x9a9a / cycronet 0x5a5a,0xcaca
  sigalg GREASE     chrome 0x6a6a / cycronet 0xbaba
```

真实 Chrome 连续 3 次的 sigalg GREASE：`0x6a6a`、`0x9a9a`、`0x5a5a`。
cycronet 连续 6 次：`0x2a2a`、`0x7a7a`、`0x3a3a`、`0xdada`、`0xdada`、`0xaaaa`
（6 次里 5 个不同值，全部符合 `0xNaNa` 形式）。

JA4 的 `t13d1517h2` 表示 17 个扩展，`chrome_150` 是 `t13d1516h2`（16 个），
差的正好是 `trust_anchors`。

扩展顺序仍然每次都不一样（连续 3 次请求得到 3 种不同顺序），说明
`permute_extensions` 没有被误关掉。

老 profile 无回归（GREASE 随机化只对 profile 里写了 GREASE 占位符的生效）：

```text
chrome_150  ja4 t13d1516h2_8daaf6152771_806a8c22fdea  sigalg[0]=0x904  无 51764
chrome_144  ja4 t13d1516h2_8daaf6152771_d8a2da3f94cd  sigalg[0]=ecdsa_secp256r1_sha256
chrome_133  ja4 t13d1516h2_8daaf6152771_02713d6af862  17513 (application_settings_old) 存在
```

WSS 测试（`wss://ws.postman-echo.com/raw` 回显）：

```text
chrome_152: echo='hello-chrome_152'
chrome_150: echo='hello-chrome_150'
```

`test_websocket_header_order.py` 2 个用例全部通过。

`https://tls.tsvmp.com:38080/cbbiyhh` 这次没有测到，该地址在本机（含直连和代理）
都连不上，不是 cycronet 的问题。上面的 peet 结果已经覆盖了
`signature_algorithms` 和扩展列表两项验证。

## 未包含的已有改动

Chromium 工作树里存在以下 websocket 相关修改，它们不是本次 Chrome 152 修改的一部分，
因此没有导出到补丁：

```text
components/cronet/native/cronet_websocket.cc
components/cronet/native/cronet_websocket.h
components/cronet/native/include/cronet_websocket_c.h
components/cronet/BUILD.gn
net/websockets/websocket_stream.cc
```

cyCronet 工作树里同样存在未提交的 WSS / `user_agent` / `accept_language` 改动
（`_session.py`、`_websocket.py`、`src/*.rs`、`build.rs` 等），也不属于本次导出，
补丁 01 只包含 Chrome 152 相关的那部分改动。
