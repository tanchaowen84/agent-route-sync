# WebRTC 常见探测防护

`webrtc-guard` 是独立于五类业务规则的防护资源。Agent 首次把它接入客户端的持久配置，并核对加载、顺序和实际流量；此后与其他远程规则集一样刷新。仅更新已有五类名单，不会自动安装这条新引用。

## 覆盖条件

满足下面任一条件的已接管连接，默认执行 **REJECT**：

| 条件 | 范围 |
| --- | --- |
| 目标端口 | `3478`、`5349`、`19302` 至 `19309`，共 10 个端口；TCP、UDP 均适用 |
| 已知域名含关键字 | `stun`；不要求同时命中上述端口 |

端口条件也能匹配 IP 字面量，在核心实际收到 IPv6 连接时同样适用。域名条件依赖核心拿到域名，不能假定 STUN 流量总能嗅探出主机名。自定义端口、其他域名、TURN 中继和点对点连接可能不命中；这套资源不能等同于完全停用 WebRTC。

这会影响命中条件的通话、会议、P2P 和其他业务，域名关键字也可能误伤名称中含 `stun` 的无关服务。首页提示词包含这一取舍；已有明确授权时直接接入。用户需要保留通话时，按具体应用做限定例外并复查，说明例外缩小了防护范围。不要预置整款应用或所有国内服务直连的宽泛豁免。

## 格式与动作

资源和 SHA-256 位于 [index.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json) 的 `protections[]`，查找 `id: webrtc-guard`。五类业务规则仍在 `datasets[]`，保持原地址和格式。v1 索引增加的是可选字段；旧发布没有它时，报告该代没有防护资源，不能假装已经安装。

| 客户端 | 文件 | 引用要求 |
| --- | --- | --- |
| Mihomo | [webrtc-guard.yaml](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/webrtc-guard.yaml) | `behavior: classical`、`format: yaml`，引用动作 `REJECT` |
| Surge / Shadowrocket | [webrtc-guard.list](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/webrtc-guard.list) | 无策略列的 RULE-SET，客户端引用动作 `REJECT`；小火箭须实机核对端口条件支持情况 |
| sing-box | [webrtc-guard.json](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/webrtc-guard.json) | source version 3；路由引用使用 `action: reject` |

这份资源包含端口条件，不可混进 Mihomo 的 domain 规则集，也不用于 DNS 域名策略。sing-box 将端口和域名分别放在两条 headless rule 中，保持“任一命中”语义。使用明确拒绝动作，不依赖节点的 UDP 能力，不设置失败后 DIRECT 的回退。

## Agent 接入顺序

1. 备份持久配置及运行配置，识别实际核心、规则模式和支持的格式。先核实索引与所需文件已发布、可下载、校验正常，配置检查通过后再应用。资源缺失或格式不支持时，保留可用配置并说明防护未完成。
2. 保留防止代理回环所需的精确节点例外、DNS 接管和核心自有地址保护、真实 LAN 技术规则。在这些必要规则之后、普通公网 DNS 地址例外及五类业务规则之前引用 `webrtc-guard`。节点恰用上述端口时，例外应限定实际节点目的地址和端口，不能因此放行全部同端口或整个浏览器。
3. 检查更高优先级的进程、域名、IP 及模块规则。业务直连例外若放在防护前面，会绕过拦截；用户明确保留的例外需要单独记录防护缺口。sing-box 等有中途嗅探的配置，域名在嗅探后才出现时，须在后续业务判断前再检查防护条件。可参考[四套模板](../examples/README.md)。
4. 在订阅刷新后仍生效的配置入口安装引用，回读实际规则与资源条目。设置客户端支持的独立刷新方式，建议 24 小时；获准刷新节点订阅后再次确认引用、拒绝动作和优先级仍在。
5. 在实际浏览器配置档运行探测，用核心连接记录或获准的抓包确认匹配项确实被拒绝，分别检查 IPv4、IPv6。未进入核心的 UDP 无法由规则阻断；仅开启系统代理不构成接管证明。需要调整 TUN、VPN 或系统设置时按已有授权范围执行，权限或能力不足则单列未完成。

Chrome 和 Edge 继续安装、启用 WebRTC Network Limiter，并设为 `Use my proxy server (if present)`（`disable_non_proxied_udp`）。网络规则与扩展分别复查。Safari 优先验证真实网络路径，其他浏览器按[版本对应方案](DNS-WEBRTC.md#webrtc-methods)处理。

## 验收与恢复

在同一配置档依次执行 [IP 检测](https://ippure.com/)、[DNS 检测](https://ippure.com/DNS-Leak-Detect.html)、[WebRTC 检测](https://ippure.com/Browser-WebRTC-Leak-Detect.html)。没有返回候选地址可能是规则阻断、浏览器策略、探针不可用或错误，不能仅凭空白结果判通过。至少同时核对资源加载、实际设置、命中或阻断证据，并明确哪些端点、地址族与浏览器被测过。

复查普通网页、Claude 相关域名及用户需要的通话功能。交付时区分“常见探测已阻断”“未接管”“未命中”和“未验证”，不要把有限探测扩大为任意环境无泄露。恢复时从备份撤销本次引用及相关覆写；浏览器设置按其独立前像恢复。恢复后重新检测。

## 来源与验证层次

端口和关键字参考 [Niklaus88/Clash-Config 的固定版本](https://github.com/Niklaus88/Clash-Config/blob/afcae376a52824864970a68c5aa0e24a38444563/clash-script.js)，按 MIT 保留[许可](../licenses/Niklaus88-Clash-Config-LICENSE.txt)。本项目自行生成和维护三种格式，不执行该项目脚本，不采用其 DNS、策略组或应用例外。

格式依据：[Mihomo classical 内容](https://wiki.metacubex.one/config/rule-providers/content/)、[Surge RULE-SET](https://manual.nssurge.com/rules/ruleset.html)、[sing-box headless rule](https://sing-box.sagernet.org/configuration/rule-set/headless-rule/)。离线匹配测试和内核配置检查只证明对应格式与条件；目标设备的接管、浏览器表现、订阅持久化和功能影响仍按上面的步骤验收。
