# 在本地解释一个规则快照

在源码仓库内，用 Python 3.11+ 和项目的[开发依赖](../requirements-dev.txt)运行 `scripts/inspect_rules.py`。输入是已解包的完整 v1 发布目录，顶层包含 `manifest.json`、`index.json` 和清单列出的全部文件。请在文件不再变化时运行。只下载了部分格式的同步缓存需要另行准备完整快照。[同步缓存契约](SYNC.md)

下例的 `snapshots/old` 和 `snapshots/new` 代表你保存两版规则的目录名。如果手里只有一版，也能查询样本和客户端验证情况。维护者刚运行完构建时，可以直接用 `generated` 代替 `snapshots/new`。

初次试用可以下载下面示例所用的完整规则包。解压后，把命令里的 `snapshots/new` 换成能看到 `manifest.json` 的那一层目录。这份清单的 SHA-256 为 `33ef0011b3460fa359db7aaf82b742db3c8086079be25c3181a67cf94e414bdb`。[下载示例快照](https://codeload.github.com/ryuu-restart/agent-route/tar.gz/9e2fb2c63df2a15468930e35e8e9df1089ffa43f)

```sh
python -B scripts/inspect_rules.py diff snapshots/old snapshots/new --summary-only
python -B scripts/inspect_rules.py explain snapshots/new --domain www.google.com --port 443
python -B scripts/inspect_rules.py explain snapshots/new --ip 2001:db8::1 --port 3478
python -B scripts/inspect_rules.py evidence snapshots/new --client shadowrocket
```

三个命令只读取本地文件，输出 JSON。每份快照先通过 v1 Schema、完整文件清单、摘要、资源身份和同代时间校验。输出的 `manifest_sha256` 标识实际读取的清单字节，相同目录名或发布时间可以对应不同摘要。发布来源和 Git 提交由快照提供者另行记录；可与可信来源提供的清单摘要核对身份。工具不联网、不写同步缓存、不加载客户端配置。查询完成或明确得出 `unknown` 时退出码为 0，输入或快照校验失败时为 1，命令行用法错误为 2。

## 两版名单的增删

`diff OLD NEW` 给出总数、每个托管规则组的增删数及具体记录。记录由条件类型和值组成，精确域名和后缀分别计数。加 `--summary-only` 可省略明细。五类业务名单和快照中实际发布的 WebRTC 防护参与比较，DNS 辅助、旧兼容文件和用户模板不参与名单计数。

三套原生表示中，工具使用发布内的 sing-box v3 源文件来统一读取域名、域名后缀、关键字、端口及 IPv4/IPv6 前缀。每个组的 `changed_resource_formats` 另列出文件字节发生变化的格式。例如 Surge 把旧文件里的 `DST-PORT` 修正为 `DEST-PORT`，若端口名单相同，结果是 Surge 文件有变化、静态端口增删均为零。这个字段帮助追查特定客户端的解析差异。新增一个 CIDR 与删掉其覆盖的两个旧 CIDR 也按三条记录计数，实际覆盖地址可能相同。[sing-box 源格式](https://sing-box.sagernet.org/configuration/rule-set/headless-rule/) · [Surge 端口语法](https://manual.nssurge.com/rules/source-and-port.html)

比较提供可选格式的快照时，`changed_resource_formats` 也列出业务规则和防护新登记、移除或摘要发生变化的 `mrs`、`srs`、`domain-set`。首次登记既有的 `.domains` 文件也会列出。名单增删继续按同一份静态文本计算，避免把新增一种表示重复算成新增规则。[可选格式](FORMATS.md)

## 一个样本先命中哪条

`explain` 按这份索引列出的托管资源顺序查找。只传 `--ip` 表示样本是没有已知主机名的裸 IP，也可同时给出已知域名和目标地址。域名支持 ASCII 或 Punycode，比较时忽略大小写和末尾的根点。精确域名只匹配自身，后缀匹配自身及其子域。防护已发布时，端口和域名关键字满足其一即可。历史快照没有防护时，按那一版的业务顺序匹配。

| 输出 | 含义 |
| --- | --- |
| `matched` | `match` 给出第一个命中的托管组及一条成立条件，`action` 是索引为该组声明的动作。 |
| `no_match` | 输入已足以排除所有托管记录，`action` 为空。 |
| `unknown` | 需要的信息或支持的语义不足，例如缺少排除防护所需的目标端口、域名未命中且没有给出目标 IP、源文件含未支持的组合条件，或请求了真实设备出口。 |

`scope.outside_scope` 列出索引中依赖设备配置的环节，包括用户与节点例外、LAN、DNS 路径和最终兜底。即使托管名单给出动作，例外也可能先命中。DNS 答案、嗅探结果、实际流量接管、浏览器和节点状态均需现场证据。用 `--device` 查询设备出口时返回 `unknown`，名单未命中时也不会代选出口。

例如，对规则代 `9e2fb2c63df2a15468930e35e8e9df1089ffa43f` 查询 `www.google.com`、端口 `443`，结果为 `matched`。其中 `value: google.com` 表示命中这个后缀，`group: proxy` 和 `action: PROXY` 表示该名单要求走代理。换一版规则，可以用同一个样本再查一次。

## 各客户端验证到哪一层

`evidence SNAPSHOT` 一次显示四个客户端的结果，`--client` 可选择 `mihomo`、`sing-box`、`surge` 或 `shadowrocket`。`snapshot_declared_scope` 保留这份索引原有的声明，缺字段时为 `unknown`。`current_project_scope` 是当前项目的验证范围。`separate_observation` 给出单独记录的版本和覆盖面。三者都不能替代对输入快照运行原生客户端并取得回执。

2026-11-21 的版本记录包括 Mihomo 1.19.32 的规则及配置解析、sing-box 1.14.4 的合成 DNS 和回环连接，以及 Surge Mac 6.12.0 官方服务对内联防护正文的解析。小火箭 2.2.62 的发布记录提到端口解析；它与 Surge 共用 LIST，小火箭远程加载及实际命中仍待真机验证。CLI 本次验证的是发布文件，各客户端对该快照的运行及目标设备加载状态均标为 `unverified`。[客户端证据](CLIENT-EVIDENCE.md) · [项目维护检查](MAINTAINING.md) · [Surge 官方校验范围](https://manual.nssurge.com/tools/profile-validation.html)
