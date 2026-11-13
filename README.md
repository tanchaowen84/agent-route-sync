# AgentRoute

<a id="about"></a>

**想用 Claude，但不想自己研究 YAML、DNS 和分流？把下面的提示词交给 Codex，让它替换旧规则、配置浏览器并验证结果。**

AgentRoute 持续更新分流规则。沿用你的代理客户端和节点，由 AgentRoute 接管业务分流和默认兜底。Agent 会核对实际流量去向，并告诉你怎么恢复。

**[快速开始 · 复制提示词](#agent-prompt)** · [加入官方微信群](#wechat-group) · [浏览器检测](#browser-checks) · [规则与订阅](#rule-subscriptions)

<a id="让我的-agent-接入"></a>
<a id="agent-prompt"></a>

## 快速开始

准备好现用的代理客户端和可用节点，把下面的提示词复制给 **Codex** 等能操作本机文件和浏览器的 Agent。

**禁止使用 Claude（包括 Claude Code 及其他基于 Claude 模型的 Agent）执行本项目的接入、复查或维护任务。**

```text
请把 AgentRoute 规则装到我现用的代理客户端，直接替换旧业务分流规则和默认兜底。请检查本机已安装的所有浏览器，补装并配好 WebRTC 防护。我授权你执行下面的操作、所需的客户端重载和一次现有节点订阅刷新。核对环境后直接执行。

请先读取 AgentRoute 的接入说明和规则索引。
https://raw.githubusercontent.com/ryuu-restart/agent-route/master/AGENTS.md
https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json

先检查现用客户端、内核版本和生效配置。客户端只能追加规则时，暂停代理规则改动，说明覆盖未完成的原因。

先备份配置，保留节点订阅、可用代理策略组和联网所需的技术规则。在订阅刷新后仍生效的配置入口停用旧业务规则、规则集引用和旧兜底，包括节点订阅、覆写或模块带入的规则。让 AgentRoute 接管业务分流，未匹配的流量走默认代理。

接入后回读生效配置，核对实际流量去向、默认代理出站和 Claude 相关域名的命中。刷新节点订阅后，再回读确认旧规则没有恢复。按接入说明核对实际生效的 DNS 策略。

逐个检查浏览器版本和我实际使用的配置档，记录原设置。支持 WebRTC Network Limiter 的浏览器，缺扩展就从官方商店安装，已有扩展就核对并修正设置。启用扩展并选择 Use my proxy server (if present)，对应 disable_non_proxied_udp。
https://chromewebstore.google.com/detail/webrtc-network-limiter/npeicpdbkakmehahjeeohfdhnlpdklia
无法安装这款扩展时，按浏览器版本应用官方支持的等效防护。系统或浏览器要求我本人确认时，把该步骤准备好，等我确认后继续配置和检测。缺少权限或没有可核实方案时，标为待配置并说明原因。继续处理其余项目。
https://github.com/ryuu-restart/agent-route/blob/master/docs/DNS-WEBRTC.md#webrtc-methods

在每个浏览器实际使用的配置档里回读设置，并用以下三个页面完成 IP、DNS 和 WebRTC 检测。交付三个链接、规则覆盖和刷新复查结果、每个浏览器的配置和检测结果、备份位置及恢复方法。未核实的项目注明未验证。
https://ippure.com/
https://ippure.com/DNS-Leak-Detect.html
https://ippure.com/Browser-WebRTC-Leak-Detect.html
```

### 接下来会发生什么

1. **替换旧规则。** Agent 备份现用配置，保留节点订阅，用 AgentRoute 接管业务分流和默认兜底。
2. **配好浏览器。** Agent 检查本机所有已安装的浏览器，在支持的浏览器里补装或配置扩展。遇到必须本人确认的提示时，Agent 会指出具体操作。
3. **给出结果。** Agent 核对分流、刷新后的规则和每个浏览器的检测结果，告诉你备份在哪、怎么恢复。

<details>
<summary>查看接入结果示例</summary>

**Agent** 汇报「已备份并替换规则，节点订阅刷新后依然由 AgentRoute 分流。Chrome 已安装并配置 WebRTC 扩展，Edge 已核对原有扩展并调整设置。两款浏览器的检测结果、备份位置和恢复步骤见本次报告。」

</details>

<a id="browser-checks"></a>

## 浏览器检测

Agent 按浏览器版本安装并配置适用的 WebRTC 防护，再在实际使用的配置档内逐项检测。检测结果覆盖该配置档的本次探测。[各浏览器官方资料](docs/DNS-WEBRTC.md#webrtc-methods) · [IP 检测](https://ippure.com/) · [DNS 检测](https://ippure.com/DNS-Leak-Detect.html) · [WebRTC 检测](https://ippure.com/Browser-WebRTC-Leak-Detect.html)

<a id="rule-subscriptions"></a>
<a id="按客户端拿规则"></a>

## 规则与订阅

[![自动构建](https://github.com/ryuu-restart/agent-route/actions/workflows/run.yml/badge.svg)](https://github.com/ryuu-restart/agent-route/actions/workflows/run.yml) [![规则库发布时间](https://img.shields.io/github/last-commit/ryuu-restart/agent-route/release?label=%E8%A7%84%E5%88%99%E5%BA%93%E5%8F%91%E5%B8%83%E6%97%B6%E9%97%B4&color=2d8e76)](https://github.com/ryuu-restart/agent-route/commits/release)

AgentRoute 的发布校验会检查 `claude.ai`、`claude.com`、`anthropic.com` 和 `api.anthropic.com` 是否被误归为广告、内网或国内直连。实际规则命中与出站以设备验证结果为准。[构建校验源码](scripts/build_rules.py)

**规则索引**汇总五类规则的地址、格式、条目数和建议刷新间隔，供 Agent 选择资源。[公开索引](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json)

**给 Agent 的格式入口**适合已经知道客户端或内核的用户。每个入口指向同一份规则索引及对应格式，具体接法以实际内核和版本为准。[客户端参考](docs/CLIENTS.md)

[Clash 系列（Mihomo 内核）](https://raw.githubusercontent.com/ryuu-restart/agent-route/master/subscriptions/mihomo.json) · [小火箭（Shadowrocket）](https://raw.githubusercontent.com/ryuu-restart/agent-route/master/subscriptions/shadowrocket.json) · [Surge](https://raw.githubusercontent.com/ryuu-restart/agent-route/master/subscriptions/surge.json) · [sing-box](https://raw.githubusercontent.com/ryuu-restart/agent-route/master/subscriptions/sing-box.json)

**客户端规则集**是实际供客户端加载和刷新的远程文件。按实际内核选格式。

![AgentRoute 规则动作示意。国内与内网规则对应直连，海外规则对应代理，广告规则对应拦截。](assets/routing-map.svg)

| 规则 | Mihomo | 小火箭 / Surge | sing-box |
| --- | --- | --- | --- |
| 内网直连 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/private.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/private.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/private.json) |
| 广告拦截 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/reject.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/reject.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/reject.json) |
| 海外代理 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/proxy.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/proxy.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/proxy.json) |
| 国内直连 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/direct.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/direct.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/direct.json) |
| 中国 IP 兜底 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/cn-ip.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/cn-ip.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/cn-ip.json) |

<a id="记得经常更新"></a>

规则校验通过后自动发布到 `release`。客户端按自己支持的方式刷新，索引中的建议间隔为 24 小时。

<a id="反馈问题"></a>
<a id="wechat-group"></a>

## 接入求助与问题反馈

接入卡住、规则没生效，或者看不懂检测结果？微信扫码加入 **AgentRoute 官方交流群**，带上你的操作系统、客户端版本和脱敏后的问题描述，一起排查。

<img src="assets/wechat-group-qr.png" width="280" height="392" alt="微信扫码加入 AgentRoute 官方交流群">

当前二维码在 **2026 年 11 月 20 日前有效**。[查看二维码原图](assets/wechat-group-qr.png)

二维码过期或发现可复现的规则、文档问题，可以通过 GitHub Issue 反馈。提问前请隐去订阅链接、节点地址、凭据和真实 IP。[GitHub Issue 入口](https://github.com/ryuu-restart/agent-route/issues/new/choose) · [脱敏说明](AGENTS.md#issue-feedback)

## 参考资料

[Agent 接入说明](AGENTS.md) · [可选模板与历史验证](examples/README.md) · [高级 DNS / WebRTC 验收](docs/DNS-WEBRTC.md) · [同步与回退](docs/SYNC.md) · [维护说明](docs/MAINTAINING.md)

规则来源、处理方式和许可见 [NOTICE](NOTICE.md)、[sources.json](sources.json) 与 [licenses](licenses/)。[本仓库许可](LICENSE)与上游声明分别适用。
