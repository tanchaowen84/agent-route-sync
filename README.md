# AgentRoute · 分流规则库

<a id="about"></a>

**给现有代理客户端用的自动更新分流规则。**

AgentRoute 发布可供各平台代理客户端使用的分流规则和索引。你的 Agent 根据实际客户端、内核和现有配置选择格式与接法。

[![自动构建](https://github.com/ryuu-restart/agent-route/actions/workflows/run.yml/badge.svg)](https://github.com/ryuu-restart/agent-route/actions/workflows/run.yml) [![规则库发布时间](https://img.shields.io/github/last-commit/ryuu-restart/agent-route/release?label=%E8%A7%84%E5%88%99%E5%BA%93%E5%8F%91%E5%B8%83%E6%97%B6%E9%97%B4&color=2d8e76)](https://github.com/ryuu-restart/agent-route/commits/release)

**[规则与订阅](#rule-subscriptions)** · [交给 Agent](#agent-prompt) · [按需检测](#browser-checks)

![AgentRoute 规则动作示意。国内与内网规则对应直连，海外规则对应代理，广告规则对应拦截。](assets/routing-map.svg)

<a id="rule-subscriptions"></a>
<a id="按客户端拿规则"></a>

## 规则与订阅

**规则索引**汇总五类规则的地址、格式、条目数和建议刷新间隔，供 Agent 选择资源。[公开索引](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json)

**给 Agent 的格式入口**适合已经知道客户端或内核的用户。每个入口指向同一份规则索引及对应格式。

[Clash 系列（Mihomo 内核）](https://raw.githubusercontent.com/ryuu-restart/agent-route/master/subscriptions/mihomo.json) · [小火箭（Shadowrocket）](https://raw.githubusercontent.com/ryuu-restart/agent-route/master/subscriptions/shadowrocket.json) · [Surge](https://raw.githubusercontent.com/ryuu-restart/agent-route/master/subscriptions/surge.json) · [sing-box](https://raw.githubusercontent.com/ryuu-restart/agent-route/master/subscriptions/sing-box.json)

**客户端规则集**是实际供客户端加载和刷新的远程文件。按实际内核选格式。

| 规则 | Mihomo | 小火箭 / Surge | sing-box |
| --- | --- | --- | --- |
| 内网直连 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/private.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/private.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/private.json) |
| 广告拦截 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/reject.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/reject.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/reject.json) |
| 海外代理 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/proxy.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/proxy.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/proxy.json) |
| 国内直连 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/direct.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/direct.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/direct.json) |
| 中国 IP 兜底 | [YAML](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/mihomo/cn-ip.yaml) | [RULE-SET](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/surge/cn-ip.list) | [JSON](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/sing-box/cn-ip.json) |

<a id="记得经常更新"></a>

规则校验通过后自动发布到 `release`。客户端按自己支持的方式刷新，索引中的建议间隔为 24 小时。

<a id="agent-prompt"></a>

## 让我的 Agent 接入

把下面这段交给负责接入的 Agent。

```text
请读取 AgentRoute 的规则索引和接入说明。
https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json
按我的目标和现用客户端版本选择接入方案。
使用对应格式的远程规则，保留我的节点和订阅。
按我的授权操作，说明改动和恢复方法。
```

**禁止使用 Claude（包括 Claude Code 及其他基于 Claude 模型的 Agent）执行本项目的接入、复查或维护任务。**

<a id="browser-checks"></a>

## 浏览器检测

用平时上网的浏览器打开 [IP 检测](https://browserleaks.com/ip)、[DNS 检测](https://browserleaks.com/dns)、[WebRTC 检测](https://browserleaks.com/webrtc)。结果只覆盖当前浏览器的本次探测。

<a id="反馈问题"></a>

## 参考资料

[规则索引](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json) · [可选模板与历史验证](examples/README.md) · [高级 DNS / WebRTC 验收](docs/DNS-WEBRTC.md) · [同步与回退](docs/SYNC.md) · [维护说明](docs/MAINTAINING.md) · [反馈问题](AGENTS.md#issue-feedback)

规则来源、处理方式和许可见 [NOTICE](NOTICE.md)、[sources.json](sources.json) 与 [licenses](licenses/)。[本仓库许可](LICENSE)与上游声明分别适用。
