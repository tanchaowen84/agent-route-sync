# 维护与验证

只有仓库所有者授权的工作才可发布；公共读取不授予写权限。消费者操作见 [Agent 入口](../AGENTS.md)。

项目维护规则、公开格式、同步校验工具和执行规范；目标设备的具体配置与验收由使用者的 Agent 负责。接入主流程只规定目标、边界和完成条件，客户端字段、界面与命令由执行者按实际版本核对。[完整示例](../examples/README.md)是可选参考，维护者不承诺逐设备适配。

客户端示例版本用于说明历史证据与功能要求，不是所有使用者必须安装的版本，也不保证未来版本兼容。CI 核心、Action 和开发依赖继续固定以复现测试；规则集格式、Schema 版本和工具最低运行要求仍是接口约束。不要把这些不同用途的版本号一并删除或改成 latest；确需更新测试基线时单独核验。

来源以 sources.json 为登记入口。变更来源时同步核对公开作者、实际输入、许可证原文、处理方式与证据；NOTICE 引用必须对应登记。直接来源许可原文保存在 licenses 并随规则发布；间接贡献者按上游实际生成流程记录，未独立核验的许可明确标注，不能推断再授权。

生成器按每个上游仓库的固定提交下载；跨仓库是一次构建所选的多个快照，不声称它们来自同一时刻。支持普通后缀、domain:、full: 与点前缀；regexp:/keyword: 保持历史跳过行为并在 manifest 统计。其他不合法条目拒绝发布，优化模式不能绕过检查。

开发环境按 requirements-dev.txt 安装固定版本依赖。运行单元测试、优化模式测试、check_contracts.py、原生 validate_native.py；比较同批输入的旧九个数据文件。每日 UTC+8 06:30 计划和手动入口保留。Action 使用完整提交标识，原生工具下载校验 SHA-256。

发布分四个任务：test 在三平台跑测试；build 只用标准库生成数据并上传；validate 下载同一份数据做原生检查，装什么都碰不到待发布的字节；publish 是唯一有写权限的任务，不检出代码也不安装任何东西，核对字节与 build 一致后推到 release。PR 只跑前三个。

release 是只有一个提交的滚动分支：每次发布都新建无历史的提交并强推，用预期旧 SHA 保护并发，所以不能从分支上找回旧版本。任何验证失败保持线上旧代。不修改 master 历史。回退代码用正常 revert，同时保留既有公开文件地址。

GitHub 可能因仓库长期无活动停用定时任务，任务失败也只通知所有者。README 的“规则库发布时间”徽章显示 release 最后一次发布的时间。发布清单超过 48 小时时去看 Actions。同步工具会拒绝过期发布，客户端可以继续用旧名单。

构建还会拦下三类上游异常，失败时线上旧规则不变：

- 任何一类名单比线上版本少 30% 以上。确认上游确实如此后，手动运行工作流并勾选 `allow_shrink`。
- 规则下载、加密 DNS、登录和常用 AI 服务的域名被广告或内网名单命中，或 AI 服务被判成直连。列表在 `scripts/build_rules.py` 开头。
- `www.google.com`、`github.com` 不再出现在海外名单里。

上游超过 14 天没有新提交时，规则照常发布，但 `upstream-freshness` 任务会失败。这是给维护者的信号：GitHub 会发失败邮件，构建徽章变红。去看上游是否停更，并决定是否换来源。提交时间记录在 manifest 的 `source_versions` 里。

收到反馈后先核实受影响的目标，再检查同类入口、后续阶段及示例。对外反馈使用[脱敏入口](../AGENTS.md#issue-feedback)，具体版本观察放入[可选证据](CLIENT-EVIDENCE.md)。项目维护规则、原生格式、索引、校验和发布。客户端接法由使用者的 Agent 决定。文档检查覆盖格式入口、首页规则地址、浏览器检测入口和仓库内链接。

测试结论按层次记录：单元测试证明对应算法/失败保护，模板约束检查证明声明未自相矛盾，原生检查证明格式与配置被固定核心接受；真实查询路径仍需执行 Agent 在获准设备上验证。新增回归应覆盖违反目标的条件及失败保护，不只检查某字段出现。用未发布的文档试跑时，让 Agent 在报告里标注候选稿。

公开文本不能出现维护者的私有内容。词表（一行一个）放在仓库外，运行测试时用环境变量 `AGENTROUTE_PRIVATE_WORDS_FILE` 指向它；未设置时这项检查跳过，CI 也不设置，所以发布前要在本机跑一次。词表不进仓库，哈希也不行。

Mihomo/sing-box 原生验证可在 Linux CI 执行；Surge 是可选本机原生检查，Shadowrocket 仅文本结构检查。不得将这些结果写成实体 iOS、DNS/WebRTC 泄露或真实 VPN/TUN 流量已通过。

保持已发布的规则地址稳定，下游的配置里写的就是这些地址。下游的部署和更新方式由他们自己决定，本项目不提供这部分代码。

维护账号的安全就是所有下游的安全：开启两步验证，不把写权限交给不受信任的自动化。`master` 已禁止强推和删除。

## 构建与原生验证

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
python3 -B scripts/check_contracts.py
python3 -B scripts/build_rules.py
# 需要 PyYAML 6.0.3，以及自己核验过的官方可执行文件：
python3 -B scripts/validate_native.py --mihomo /path/to/mihomo --sing-box /path/to/sing-box
```

构建使用 Python 3.9+ 标准库，原生检查另外使用 PyYAML，同步工具需要 3.11+。无需项目密钥，勿使用 sudo。

数据来源为 Loyalsoldier 的 [v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat)（direct / proxy / reject）、[domain-list-custom](https://github.com/Loyalsoldier/domain-list-custom)（private）与 [geoip](https://github.com/Loyalsoldier/geoip)（中国 IP）。固定 URL 和每次输入摘要写入 manifest；海外原文 `proxy-source.txt` 与国内冲突清洗来自同一批下载。保留本仓库 [GPL-3.0 LICENSE](../LICENSE) 和来源说明。

提交问题请提供脱敏的环境、版本、generation、错误分类与复现步骤，不附节点密码、订阅令牌、浏览器 Cookie 或原始业务日志。
