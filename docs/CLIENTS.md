# 客户端接入

本文回答三个问题：用哪个模板、改动放哪里才不会丢、每个客户端有哪些坑。整体流程见 [AGENTS](../AGENTS.md)。

## 选模板

| 客户端 | 模板 | 规则格式 |
| --- | --- | --- |
| Mihomo / Clash Meta / FlClash / Clash Verge Rev | [full/mihomo.yaml](../examples/full/mihomo.yaml) | YAML `payload`，域名 `behavior: domain`，IP `ipcidr` |
| Surge | [full/surge.conf](../examples/full/surge.conf) | 无策略列的 `RULE-SET` 文本 |
| Shadowrocket | [full/shadowrocket.conf](../examples/full/shadowrocket.conf) | 同 Surge；刷新周期在 App 内设置 |
| sing-box | [full/sing-box.json](../examples/full/sing-box.json) | JSON source rule-set version 3 |

模板包含 DNS、嗅探、DNS 服务器路由和完整规则顺序。用户的 DNS 已按 [DNS-WEBRTC](DNS-WEBRTC.md) 配好时，只取 `AgentRoute managed` 标记之间的规则即可。

<a id="baseline"></a>

### 验证基线

| 客户端 | 版本 | 验证到什么程度 |
| --- | --- | --- |
| Mihomo | 1.19.32 | 配置检查；隔离实例中规则加载、DNS 与分流命中 |
| sing-box | 1.14.4（模板需要 1.14.0+） | 配置检查；隔离实例中 DNS 答案筛选与分流命中 |
| Surge | Mac 5.10.0+（`[Host]` 引用规则集需要） | 只做配置检查 |
| Shadowrocket | 未限定 | **只做文本结构检查，实体 iOS 未验证** |

以上都未覆盖真实 TUN、实体手机、持续负载和真实泄露测试。低于基线时不要照搬模板：按实际版本的文档适配，或问用户是否升级。旧版 Clash 分支不支持全部字段。

<a id="where-changes-survive"></a>

## 改动放哪里

**这一节决定接入能否长期有效。** 配置由订阅生成时，直接改文件，下次刷新就被冲掉。先判断配置来源，再选位置。

| 客户端 | 配置来源 | 改动放哪里 | 依据 |
| --- | --- | --- | --- |
| Mihomo 核心 | 本地文件 | 直接改文件。节点来自订阅的，用 `proxy-providers`，规则不受订阅影响 | 官方文档 |
| Clash Verge Rev | 订阅 | 规则用“编辑规则”的前置规则；DNS 和嗅探用“扩展配置”或“扩展脚本” | [规则](https://www.clashverge.dev/guide/rules.html)、[扩展](https://www.clashverge.dev/guide/extend.html) |
| FlClash | 订阅 | 完整订阅负责 DNS，要关闭“DNS 覆写”和“追加系统 DNS”。规则覆盖方式按当前版本确认，确认不了就问用户 | 2026-10 实测 DNS 开关；覆盖方式未核实 |
| Surge | 自己的配置 | 直接改，或用 Detached Profile | [手册](https://manual.nssurge.com/) |
| Surge | 托管配置 | 用模块，但有限制，见下方 | [模块](https://manual.nssurge.com/profile/module.html) |
| Shadowrocket | 任意 | 按当前 App 版本确认本地配置和模块的行为 | 未核实 |
| sing-box GUI | 远程配置 | 远程配置更新会覆盖。改用本地配置，或让生成方合并模板 | 未核实，按当前版本确认 |
| 其他 GUI | 订阅 | 找“覆写 / 扩展 / Override”功能。找不到就停下问用户，不要改订阅原文 | — |

### Clash Verge Rev 的合并陷阱

扩展配置写到的列表和 `dns` 字段会**整段替换**，包括 `nameserver-policy`，没写的字段保留。所以：

- 要保留订阅原有的条目，用扩展脚本（`main(config)`）追加，不要用扩展配置覆盖。
- `mixed-port`、`mode`、`ipv6`、`allow-lan`、`tun.enable` 等由应用设置页控制，写在扩展里会被丢弃，要到设置页改。
- 官方文档明确“编辑规则”不会随订阅更新失效；扩展是否每次刷新后重新应用，文档没有逐字说明，接入后刷新一次订阅实测。

### Surge 托管配置的模块限制

托管配置不能直接编辑，模块是官方给的办法，但：

- 模块里的规则**只能用内置策略**（DIRECT、REJECT、REJECT-TINYGIF），`RULE-SET,...proxy.list,PROXY` 放不进去。
- 模块不能改 `[Proxy]` 和 `[Proxy Group]`，模块的启用状态也不跨设备同步。

因此托管配置下只能把 private、reject、direct、cn-ip 和 `[Host]` 放进模块，海外流量依靠托管配置原有的最终规则走代理。代价是少了“proxy 先于 direct”这一层保护。如果用户要完整顺序，就问他们是否改用自己的非托管配置。

### 订阅刷新后复查

配置放好后，手动刷新一次订阅，再确认规则和 DNS 还在。这一步没做，就不能报告“已持久化”。

## 规则顺序及原因

**用户例外 → 节点地址 → 本地与 LAN → DNS 服务器地址 → private → reject → proxy → direct → cn-ip → 默认代理。**

| 顺序 | 为什么 |
| --- | --- |
| 用户例外最先 | 用户明确的选择优先于任何名单 |
| 节点地址早于一切代理规则 | 否则连接节点的流量可能又被送进代理，形成循环 |
| FakeIP 段早于 LAN | `fc00::/7` 这条 LAN 规则包含 FakeIP 的 IPv6 段，顺序反了 FakeIP 流量会被当成内网直连 |
| DNS 服务器地址早于名单 | 决定 DoH 连接走直连还是代理，每个备用解析器都要有规则 |
| private 早于 reject 和 proxy | 精确的 `router.asus.com` 不应被 `.asus.com` 海外后缀覆盖 |
| proxy 早于 direct | 防止海外域名被国内名单误判直连 |
| cn-ip 在所有域名规则之后 | 它是兜底，且需要解析出真实 IP 才能判断 |

几个细节：

- 这里的 `private` 指通用内网域名规则，不是维护者的私密数据。
- 不要把精确域名扩成后缀。Mihomo 的 `+.example.com` 同时覆盖根域名和子域名；sing-box 的 `domain` 和 `domain_suffix` 分开保存。
- `direct` **只含域名**，`cn-ip` **只含公网中国 IP**。cn-ip 已剔除 LAN 和合成地址。
- 个人强制代理域名、业务直连 IP、App 专用例外、广告白名单和节点不在共享数据里，放在用户自己的配置中。

### cn-ip 能兜住未知域名吗

取决于客户端的解析流程。模板有意不给 cn-ip 加 `no-resolve`。

- **Mihomo / Surge**：未知域名会解析后再匹配 IP。解析失败走默认代理。
- **sing-box**：路由规则不会替域名做解析。模板在 DNS 层判断：答案**全部**是中国 IP 才返回真实地址，连接随后命中 cn-ip；混合、海外或解析失败都继续走 FakeIP 和代理。这段逻辑需要 `sing-box/non-cn-ip.json`，它只用于 DNS 判断，不是路由规则集。
- **直接以 SOCKS / HTTP 传入 sing-box 的未知域名**不经过这个 DNS 判断，会走默认代理。这是偏安全的结果，不算故障。

## 稳定资源地址

基础地址为 `https://raw.githubusercontent.com/ryuu-restart/agent-route/release/`，全部公开，无需凭据。

| 规则 | 动作 | Surge / Shadowrocket | Mihomo | sing-box |
| --- | --- | --- | --- | --- |
| 私有 / 内网域名 | DIRECT | [private.list](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/private.list) | [private.yaml](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/private.yaml) | [private.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/private.json) |
| 广告域名 | REJECT | [reject.list](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/reject.list) | [reject.yaml](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/reject.yaml) | [reject.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/reject.json) |
| 海外域名 | 自己的 PROXY | [proxy.list](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/proxy.list) | [proxy.yaml](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/proxy.yaml) | [proxy.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/proxy.json) |
| 国内域名 | DIRECT | [direct.list](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/direct.list) | [direct.yaml](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/direct.yaml) | [direct.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/direct.json) |
| 中国 IPv4 / IPv6 | DIRECT 兜底 | [cn-ip.list](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/cn-ip.list) | [cn-ip.yaml](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/cn-ip.yaml) | [cn-ip.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/cn-ip.json) |

机器入口：[index.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json)；同批时间、来源及 SHA-256：[manifest.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/manifest.json)。`index.json` 是本项目版本化的索引，不是客户端配置或通用标准协议。

规则下载默认经 `PROXY`：`raw.githubusercontent.com` 在部分网络无法直连。代理不可用时，客户端继续使用已缓存的上一份规则。

## 更新与失败保留

规则每天 **UTC+8 06:30** 计划构建，调度可能延迟，以 manifest 时间为准。每次先跑测试，再生成并通过官方 Mihomo / sing-box 原生检查，最后一次性切换 `release` 分支。失败时不发布，旧规则仍然可用。

客户端按远程地址约每 24 小时刷新，各设备刷新时刻不同。

## 兼容旧消费者

根目录原有的 `direct.list` / `direct.json` / `direct.domains` / `direct.ipcidr`、`private.domains`、`proxy-source.txt`、`reject.domains` / `reject.list` / `reject.json` 和 manifest 字段继续保留。旧 `direct.list` / `direct.json` 混合了域名、LAN 和 IP，不能用来替换新目录中的纯域名资源。消费者不要假设 manifest 的 `files` 永远只有固定数量。

## 依据与局限

格式依据：[Mihomo rule-providers](https://wiki.metacubex.one/config/rule-providers/) · [Surge RULE-SET](https://manual.nssurge.com/rules/ruleset.html) · [sing-box rule-set](https://sing-box.sagernet.org/configuration/rule-set/)。DNS 和域名过滤不能可靠消除与正常内容共用域名的视频广告；原生检查不等于每台设备的真实网络验收。
