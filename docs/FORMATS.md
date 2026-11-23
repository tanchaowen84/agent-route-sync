# 试用同一份规则的其他格式

每一版规则的 `index.json` 都列出当版可用的资源。先找 `format_variants`，再按规则名 `id` 和格式 `format` 取记录里的 `url`。早期版本没有这个字段，可以继续使用原有文本入口。五类业务规则的顺序和动作见[首页规则表](../README.md#rule-subscriptions)。

| 客户端 | 可选资源 | 使用方法 |
| --- | --- | --- |
| Mihomo | 5 份 MRS，涵盖四组域名和中国 IP | 在现有 provider 中选对应 MRS 地址，设 `format: mrs`。域名沿用 `behavior: domain`，中国 IP 用 `ipcidr`。显式配置了缓存文件时，为 MRS 使用独立路径。WebRTC 防护继续用 `classical` YAML。[官方格式说明](https://wiki.metacubex.one/en/config/rule-providers/) |
| sing-box | 7 份 SRS，涵盖五类业务、防护和 DNS 辅助 | 在原有 `route.rule_set` 条目中保留 `tag`，将 `format` 设为 `binary` 并选择相应 SRS 地址。DNS 辅助 `non-cn-ip` 用在原有 DNS 条件中。项目使用 1.14.4 生成并检查 SRS v2。[官方规则集说明](https://sing-box.sagernet.org/configuration/rule-set/) |
| Surge | 4 份 DOMAIN-SET，分别为 `private.domains`、`reject.domains`、`proxy.domains`、`direct.domains` | 在 `[Rule]` 中将对应的普通域名规则改为 `DOMAIN-SET` 并使用索引中的地址，沿用原策略和顺序。中国 IP、端口及关键字防护继续用原来的 `RULE-SET`。参考模板中的 DNS 映射和扩展匹配继续引用各自的 LIST。[官方域名语法](https://manual.nssurge.com/rules/domain.html#domain-set) · [规则集说明](https://manual.nssurge.com/rules/ruleset.html) |
| 小火箭（Shadowrocket） | 继续使用 Surge LIST 入口 | 上述 DOMAIN-SET 试用范围为 Surge。小火箭的远程加载与实际命中仍需在对应版本的真机上验证。[客户端证据](CLIENT-EVIDENCE.md) |

例如，想试用 Mihomo 的海外代理名单，可以在本地完整快照里查找 `id=proxy`、`format=mrs`，只替换这份 provider 的文件地址和格式。使用独立同步缓存时可以直接选择整套资源。

```sh
python scripts/sync_rules.py sync --output ./rules-pilot --format mrs
python scripts/sync_rules.py verify --output ./rules-pilot
```

`srs` 与 `domain-set` 可在同一参数位置使用。优先保留原来的文本缓存，方便比较及恢复。同步工具检查所选资源是否由该代索引登记，并核对清单摘要；命令返回的目录可供客户端读取。客户端的实际加载需要单独验证。[同步与回退](SYNC.md)

## 怎样选择

2026-11-22，在一台 Apple Silicon Mac 上，用同一批规则分别启动全新的客户端核心进程。每种格式交错测六轮，使用本地文件，系统文件缓存未清空。计时从启动进程到六组本地请求全部走到预期接收端。内存为就绪后约两秒内测得的核心进程常驻内存中位数。

| 客户端 | 原有文本就绪 | 可选格式就绪 | 文本内存 | 可选格式内存 |
| --- | ---: | ---: | ---: | ---: |
| Mihomo 1.19.32，YAML 与 MRS | 591 毫秒 | 36 毫秒 | 118 MiB | 59 MiB |
| sing-box 1.14.4，JSON 与 SRS | 612 毫秒 | 66 毫秒 | 352 MiB | 57 MiB |

在上述版本上，需要缩短启动时间或减少启动后的内存占用，可以优先试 MRS 或 SRS。用于比较传输量的本地 HTTP 服务对每份文件分别启用 gzip。在这个条件下，五份 MRS 比五份 YAML 多传约 17%，七份 SRS 比七份 JSON 多传约 4%，四份 Surge 纯域名列表比四份对应 LIST 少传约 4%。实际下载量取决于服务器和客户端协商的编码。Surge 的启动和内存、小火箭真机、本地以外的二进制下载量仍待测量。
