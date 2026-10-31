# 维护与验证

只有仓库所有者授权的工作才可发布；公共读取不授予写权限。消费者操作见 [Agent 入口](../AGENTS.md)。

来源以 sources.json 为登记入口。变更来源时同步核对公开作者、实际输入、许可证原文、处理方式与证据；NOTICE 引用必须对应登记。直接来源许可原文保存在 licenses 并随规则发布；间接贡献者按上游实际生成流程记录，未独立核验的许可明确标注，不能推断再授权。

生成器按每个上游仓库的固定提交下载；跨仓库是一次构建所选的多个快照，不声称它们来自同一时刻。支持普通后缀、domain:、full: 与点前缀；regexp:/keyword: 保持历史跳过行为并在 manifest 统计。其他不合法条目拒绝发布，优化模式不能绕过检查。

开发环境按 requirements-dev.txt 安装固定版本依赖。运行单元测试、优化模式测试、check_contracts.py、原生 validate_native.py；比较同批输入的旧九个数据文件。PR 仅校验；三平台测试通过后，master 的发布任务才有写权限。每日 UTC+8 06:30 计划和手动入口保留。Action 使用完整提交标识，原生工具下载校验 SHA-256。

release 保持滚动历史，发布用预期旧 SHA 保护并发；任何验证失败保持线上旧代。不修改 master 历史。回退代码用正常 revert，同时保留既有公开文件地址。

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
