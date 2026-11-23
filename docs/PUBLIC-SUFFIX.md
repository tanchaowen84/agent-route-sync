# reject 与 private 的公共后缀检查

一条后缀规则会影响域名本身和全部子域。例如 `DOMAIN-SUFFIX,co.nz` 会覆盖新西兰 `co.nz` 下不同注册人的网站。`reject` 会拦截这些连接，`private` 会将它们纳入本地直连。发布验证读取当代 `surge/reject.list` 与 `surge/private.list`，区分精确规则与后缀规则，并使用公共后缀表（PSL）核对覆盖范围。[PSL 官方格式](https://github.com/publicsuffix/list/wiki/Format)

| 规则覆盖范围 | 发布处理 |
| --- | --- |
| 后缀规则覆盖 ICANN 部分的一条公共后缀或其上级域 | 阻止发布。通配规则也计入，例如 `*.kawasaki.jp` 使对整个 `kawasaki.jp` 的后缀匹配过宽。PSL 的 `!city.kawasaki.jp` 例外照常生效。 |
| 精确规则只匹配公共后缀本身 | 在 `review` 列出。匹配不会扩展到各注册人。 |
| 规则直接命中 PRIVATE 部分的托管边界，或后缀规则覆盖该边界的上级域 | 在 `review` 列出，供维护者对照上游用途。例如 `github.io` 影响所有租户，单一租户 `tenant.github.io` 可正常列入规则。 |
| `private` 中明示的本地域 | 在 `local_exceptions` 单列。范围为生成器已有的八个单标签和家庭网络专用的 `home.arpa`。[RFC 8375](https://www.rfc-editor.org/rfc/rfc8375) |

构建器的标准库预检保留原有单标签约束，以及对六个已知过宽域的精确、后缀拒绝。完整 PSL 检查在 CI 的只读验证任务中执行。维护时可在安装开发依赖后复查本地候选。

```sh
python3 -B scripts/check_contracts.py --generated generated
python3 -B scripts/check_public_suffixes.py --generated generated
```

第一项核对产物完整性。第二项输出各类规则的条数、判定明细与 PSL 摘要。出现 `blocked`、无法读取输入或快照摘要不符时返回非零状态。规则生成和使用者的同步工具仍使用标准库。

## 固定快照与更新

仓库收录官方每日分发的原始 UTF-8 文件，版本为 `2026-11-21_04-33-45_UTC`，内标上游提交为 `87a2c1b8de5886a133ff4da21b2aa6fec88d8739`。分发文件的 SHA-256 为 `017501d3fa7911c60ac7e0f68df4122b07216c585c15dc30e0f0c74b8d13a2b9`。PSL 使用 MPL 2.0，原许可证随快照保存在源码仓库，规则发布目录无需携带这份验证数据。[官方分发说明](https://publicsuffix.org/list/) · [对应上游源码](https://github.com/publicsuffix/list/tree/87a2c1b8de5886a133ff4da21b2aa6fec88d8739) · [本地快照](../validation/psl/public_suffix_list.dat) · [许可原文](../validation/psl/LICENSE)

维护者更新快照时从官方分发地址下载原件，核对文件头的版本、提交与许可证并重新计算下载字节的 SHA-256。本次固定提交中的源文件 SHA-256 为 `00a0af2ed2379634523b9ca80de3469d1466893915c252a91264e248c92d69d8`，与分发副本仅差服务插入的版本、提交和分隔空行。更新脚本里的摘要和本页记录，在同一代产品数据上运行新旧两份表并核对变化，再复查 `test_public_suffixes.py` 的通配、例外和 PRIVATE 样本。日常检查只从仓库文件加载，关闭网络适配器、缓存和包内备用表。[官方分发文件](https://publicsuffix.org/list/public_suffix_list.dat) · [tldextract 使用说明](https://github.com/john-kurkowski/tldextract)

## 首次实盘评估

2026-11-21 的固定代中，`reject` 有 0 条精确和 201,160 条后缀规则，`private` 有 14 条精确和 118 条后缀规则。ICANN 阻断数为 0。`reject` 中 `servebbs.net` 匹配 PRIVATE 边界，`0emm.com` 覆盖 PRIVATE 通配 `*.0emm.com`。`private` 中 `ts.net` 匹配 PRIVATE 边界。`private` 的九个本地范围均单列。这些结果描述规则可覆盖的域名范围，所用输入分别来自固定的广告名单和内网名单。[广告输入](https://github.com/Loyalsoldier/v2ray-rules-dat/blob/9c3ed9c8dde9ba3bf128defe8e8971c9a30a539d/reject-list.txt) · [内网输入](https://github.com/Loyalsoldier/domain-list-custom/blob/faf4043bdad9e771920e0761aece70ee536f15eb/private.txt)
