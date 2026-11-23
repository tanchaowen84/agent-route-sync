# 维护与验证

只有仓库所有者授权的工作才可发布；公共读取不授予写权限。消费者操作见 [Agent 入口](../AGENTS.md)。

项目维护规则、公开格式、同步校验工具和执行规范；目标设备的具体配置与验收由使用者的 Agent 负责。接入主流程只规定目标、边界和完成条件，客户端字段、界面与命令由执行者按实际版本核对。[完整示例](../examples/README.md)是可选参考，维护者不承诺逐设备适配。

客户端示例版本用于说明历史证据与功能要求，不是所有使用者必须安装的版本，也不保证未来版本兼容。CI 核心、Action 和开发依赖继续固定以复现测试；规则集格式、Schema 版本和工具最低运行要求仍是接口约束。不要把这些不同用途的版本号一并删除或改成 latest；确需更新测试基线时单独核验。

来源以 sources.json 为登记入口。变更来源时同步核对公开作者、实际输入、许可证原文、处理方式与证据；NOTICE 引用必须对应登记。直接来源许可原文保存在 licenses 并随规则发布；间接贡献者按上游实际生成流程记录，未独立核验的许可明确标注，不能推断再授权。

生成器按每个上游仓库的固定提交下载；跨仓库是一次构建所选的多个快照，不声称它们来自同一时刻。支持普通后缀、domain:、full: 与点前缀；regexp:/keyword: 保持历史跳过行为并在 manifest 统计。其他不合法条目拒绝发布，优化模式不能绕过检查。

开发环境按 requirements-dev.txt 安装固定版本依赖。运行单元测试、优化模式测试、check_contracts.py、原生 validate_native.py；比较同批输入的旧九个数据文件。每日 UTC+8 06:30 计划和手动入口保留。Action 使用完整提交标识，原生工具下载校验 SHA-256。

发布有四步。test 在三平台跑离线测试。build 用标准库生成文本，再以固定原生工具编译可选格式，将含全部格式的候选作为一个工件上传，并记录 ID 和最终清单摘要。validate 按 ID 取回产物，核对摘要、实际文件、索引、清单及原生格式。publish 是唯一有写权限的任务，它取同一 ID 的产物，在独立目录准备提交，逐项核对 Git 实际收录的文件、模式和内容摘要。最后一步才使用写令牌推送这份提交。PR 只跑前三步。

release 每次发布都新建无父提交。构建在选上游输入前先记下当时的 release 提交，用该提交的索引做缩水比较。发布前再确认本次工作流使用的源码仍是 master 顶端，更新 release 时由 Git 检查它是否仍在构建所见的位置。首次发布只允许创建尚不存在的引用。只要另一份候选抢先发布，旧候选就失去写入资格。此时应从当前 master 发起新构建，重新比较。已离开分支的规则代不保证能从远端找回，可靠的数据回退依赖本地缓存。源码回退使用正常 revert 并保留公开地址。GitHub 重新运行旧任务会沿用原事件的源码提交。[工作流重跑](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs) · [Git 发布租约](https://git-scm.com/docs/git-push)

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

WebRTC 防护独立发布三种格式，不改变五类业务规则的十五个地址。构建从本地维护的端口与关键字生成资源；参考来源、固定提交和 MIT 许可记录在 sources 与 NOTICE。新增条件须验证三种格式的等效匹配、IP 字面量、IPv6、非标准端口边界、模板优先级和同步失败保留。Mihomo 的 classical 规则使用 YAML 和 `DST-PORT`，不转换为 MRS。原生检查读取候选 YAML 的 `payload`，作为内联 classical 规则交给 `mihomo -t` 逐条解析，并单独检查完整模板。Surge 使用 `DEST-PORT`。小火箭共用该文件，远程加载和命中证据单列。[客户端证据](CLIENT-EVIDENCE.md#客户端案例)

保持已发布的规则地址稳定，下游的配置里写的就是这些地址。下游的部署和更新方式由他们自己决定，本项目不提供这部分代码。

维护账号的安全就是所有下游的安全：开启两步验证，不把写权限交给不受信任的自动化。`master` 已禁止强推和删除。

## 修改规则定义

五类业务规则、WebRTC 防护和 DNS 辅助资源的用途、动作、顺序、格式与路径集中在[规则目录](../scripts/rule_catalog.py)。生成器从这里读取定义。改完目录后运行 `python3 -B scripts/update_rule_catalog.py --write`，更新四份客户端入口、首页规则表、Schema 中对应的约束和单文件同步工具内嵌的下载清单。省略 `--write` 会检查这些文件是否一致。旧版 v1 的顺序另有兼容用例。

两次构建对比时固定五个输入、来源版本和生成时间，核对整个输出目录，包含旧九文件和清单。[只读工具](INSPECT.md)可进一步解释哪份名单变了、一个样本会先命中哪组，以及各客户端验证到了哪一步。

## 为同一版文本生成试用格式

先运行 `scripts/build_rules.py` 得到 `generated/`。选择新的输出目录，使用与 CI 相同版本的 Mihomo 1.19.32、sing-box 1.14.4 执行以下命令。

```sh
python3 -B scripts/build_variants.py --source generated --output candidate --mihomo /path/to/mihomo --sing-box /path/to/sing-box
python3 -B scripts/check_contracts.py --generated candidate --require-variants
python3 -B scripts/check_public_suffixes.py --generated candidate
python3 -B scripts/validate_native.py --generated candidate --mihomo /path/to/mihomo --sing-box /path/to/sing-box
```

完整候选有 16 条可选格式记录。三份旧域名文件得到复用，因此实际新增 13 个文件。检查会从当代文本重新编译参考文件，用原生工具解开参考与候选并比较内容。Mihomo 的 classical 防护继续从 YAML 验证。旧代、文本构建和完整候选都可用普通 `--generated` 检查；发布任务要求 `--require-variants`，缺少新格式会失败。[可选格式](FORMATS.md)

## 构建与原生验证

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
python3 -B scripts/check_contracts.py
python3 -B scripts/build_rules.py
python3 -B scripts/check_contracts.py --generated generated
python3 -B scripts/check_public_suffixes.py --generated generated
# 需要 PyYAML 6.0.3，以及自己核验过的官方可执行文件：
python3 -B scripts/validate_native.py --mihomo /path/to/mihomo --sing-box /path/to/sing-box
# Linux / macOS 需要 dig。测试只在本机回环地址监听。
python3 -B scripts/check_sing_box_dns.py --sing-box /path/to/sing-box
```

最后一项用合成 DNS 答案和两个本地接收端，检查 sing-box 1.14.4 对名单外域名和裸 IP 选择的出口。测试通过表示复现了[示例说明](../examples/README.md)中的行为，包括双栈混合域名可能有一路直连。

文档检查使用固定版本的 lychee 离线核对本地链接、章节和图片。公共后缀检查读取仓库内固定版本的表，报告广告与内网名单是否会覆盖整个公共后缀。原生检查另外让 sing-box 对编译后的七份资源运行 18 个命中与不命中样本。[公共后缀结果判读](PUBLIC-SUFFIX.md)

无参数的合约检查使用测试数据并核对公开文档。带 `--generated` 的检查读取指定目录里的真实文件，核对五类业务规则的顺序、动作、路径，以及索引、清单和文件摘要。复查早期 v1 发布时，可用 `--generated <目录> --historical` 识别当时尚未提供的可选资源。CI 对新发布执行当前契约。维护验证环境按 `requirements-dev.txt` 安装，包括日期时间和 URI 格式检查所需的依赖。构建使用 Python 3.9+ 标准库，原生检查另外使用 PyYAML，同步工具需要 3.11+。本地运行这些命令无需项目密钥或 sudo。

数据来源为 Loyalsoldier 的 [v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat)（direct / proxy / reject）、[domain-list-custom](https://github.com/Loyalsoldier/domain-list-custom)（private）与 [geoip](https://github.com/Loyalsoldier/geoip)（中国 IP）。固定 URL 和每次输入摘要写入 manifest；海外原文 `proxy-source.txt` 与国内冲突清洗来自同一批下载。保留本仓库 [GPL-3.0 LICENSE](../LICENSE) 和来源说明。

提交问题请提供脱敏的环境、版本、generation、错误分类与复现步骤，不附节点密码、订阅令牌、浏览器 Cookie 或原始业务日志。
