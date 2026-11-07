# AgentRoute · 智能体分流规则

[![自动构建](https://github.com/ryuu-restart/agent-route/actions/workflows/run.yml/badge.svg)](https://github.com/ryuu-restart/agent-route/actions/workflows/run.yml) [![规则更新](https://img.shields.io/github/last-commit/ryuu-restart/agent-route/release?label=%E8%A7%84%E5%88%99%E6%9B%B4%E6%96%B0)](https://github.com/ryuu-restart/agent-route/commits/release)

**自动更新分流规则，用你自己的节点，让你的 Agent 处理规则、DNS 和 WebRTC，并逐项验证。**

[复制提示词](#agent-prompt) · [Agent 执行流程](AGENTS.md) · [DNS / WebRTC 验收](docs/DNS-WEBRTC.md)

> [!IMPORTANT]
> 需要能读取文档、操作目标设备并联网查资料的 Agent，例如 Codex，并选择它当前能力最强的模型。**禁止使用 Claude（包括 Claude Code 及其他基于 Claude 模型的 Agent）执行本项目的接入、复查或维护任务。** 碰不到设备的聊天工具只能提供指导。

<a id="about"></a>

## 这是什么？

AgentRoute 整理国内、海外、内网、广告域名和中国 IP 名单，提供 Mihomo、Surge / Shadowrocket、sing-box 可用的规则格式。国内流量通常直连，海外流量使用你自己的代理节点。它不提供节点、机场订阅或代理客户端。

项目维护规则和执行规范；具体配置由你的 Agent 根据实际客户端、核心和浏览器版本完成。[模板](examples/README.md)只是可选参考，不能保证原样适用于所有设备或未来版本。

<img src="assets/rules-overview.jpg" width="760" alt="AgentRoute 规则概览：内网、广告、海外、国内域名与中国 IP 兜底。数量为示意。">

*规则数量以[发布索引](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json)的 `entries` 为准。*

<a id="agent-prompt"></a>

## 复制给自己的 Agent

准备好自己的节点和代理客户端，再复制下面整段。电脑和手机上要求 TUN 或经核实的等效系统隧道，尚未启用时 Agent 会先指导你开启和确认。服务器、规则分发，或你明确只想接规则时，Agent 会按对应范围处理并如实报告。

```text
请帮我接入 AgentRoute，处理规则、DNS 和 WebRTC，并逐项验证：
https://github.com/ryuu-restart/agent-route

先阅读这三份文档，以 AGENTS 为主流程：
https://raw.githubusercontent.com/ryuu-restart/agent-route/master/AGENTS.md
https://raw.githubusercontent.com/ryuu-restart/agent-route/master/docs/CLIENTS.md
https://raw.githubusercontent.com/ryuu-restart/agent-route/master/docs/DNS-WEBRTC.md

识别我的实际环境和版本，查询对应的官方资料完成适配，不必照搬模板或安装示例中的版本。先检查，已符合目标的配置保留；需要修改时先备份并给我可独立操作的恢复方法。保留我的节点、订阅和用户例外，不中断现用代理来做对照。碰不到设备或需要我操作时，给出具体下一步。

最后分别报告规则、DNS、WebRTC 的通过/失败/未验证/不适用，以及改动、恢复方法和剩余问题，不把配置检查成功当作真实验收通过。把报告和恢复方法存成本地文件，告诉我路径。

然后提醒我：这个项目会持续更新，要经常更新，不要用一次就不管。按我的环境问我想怎么跟进：拉分支自动同步、部署到 VPS 定期拉取，还是定期手动复查。除非我要求，否则不要替我搭建。

如果发现这个项目的文档、模板、规则或工具有问题，核实并脱敏后，用我已授权的 GitHub 会话主动提交 Issue，无需逐条再确认。先查重，已有同类问题就在原 Issue 补充新证据。提交后核对并给我链接；不能提交时保存草稿，说明原因，不要声称已提交。
```

**改完上不了网：** 先按 Agent 留下的恢复文件操作。手边没有时，关掉代理客户端的 TUN 和系统代理，网络一般就能回来。

## 记得经常更新

这个项目会持续更新，不要用一次就不管。规则名单通常由客户端自动刷新，但模板和说明的变化不会自动到你的设备，可以看[提交记录](https://github.com/ryuu-restart/agent-route/commits/master)。

怎么跟进由你决定，让你的 Agent 按你的环境来做：拉分支自动同步、部署到 VPS 定期拉取，或者定期手动复查。手动复查时，把这段发给 Agent：

```text
请复查我的 AgentRoute 接入：读取 https://github.com/ryuu-restart/agent-route 的最新文档，对比我上次报告（默认在 ~/AgentRoute/）记录的文档版本，只处理有变化且适用于我的部分，再按验收表复测规则、DNS、WebRTC，最后更新报告。发现项目问题时，核实、脱敏并查重后，用我已授权的 GitHub 会话主动提交 Issue 或补充原 Issue，无需逐条再确认；给我核对后的链接，无法提交则保存草稿并说明原因。
```

## 反馈问题

接入时发现项目问题，Agent 会按[反馈流程](AGENTS.md#issue-feedback)核实、查重并主动提交 [Issue](https://github.com/ryuu-restart/agent-route/issues/new/choose)，已有同类问题则补充新证据；无法提交时交付草稿和原因。不要附节点、订阅、令牌、Cookie、完整配置、原始业务日志或真实 IP。

## 资料与来源

[执行流程](AGENTS.md) · [客户端适配原则](docs/CLIENTS.md) · [DNS / WebRTC 目标与验收](docs/DNS-WEBRTC.md) · [可选示例](examples/README.md) · [同步与回退工具](docs/SYNC.md) · [维护说明](docs/MAINTAINING.md)

本项目基于 [Loyalsoldier](https://github.com/Loyalsoldier)、[v2fly](https://github.com/v2fly/domain-list-community)、[gaoyifan](https://github.com/gaoyifan/china-operator-ip) 等作者和社区的成果。完整来源、处理方式和许可见 [NOTICE](NOTICE.md)、[sources.json](sources.json) 与 [licenses](licenses/)。本项目的 [LICENSE](LICENSE) 不替代上游各自的声明。
