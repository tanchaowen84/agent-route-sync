# AgentRoute 同步仓库

同步公开项目 [ryuu-restart/agent-route](https://github.com/ryuu-restart/agent-route)。本仓库不包含个人节点、认证信息、本机配置或浏览器数据。

## 分支

- `main`：本仓库编写的同步代码、自动任务、测试与 `SYNC_STATE.json`。
- [`release`](https://github.com/tanchaowen84/agent-route-sync/tree/release)：上游发布数据的完整文件树，保留原始文件、哈希、许可和来源声明。
- [`source`](https://github.com/tanchaowen84/agent-route-sync/tree/source)：上游 master 文档、模板和源码快照，排除 `.github/`，避免执行上游工作流。源码只作为数据保存，不执行上游构建或测试代码。

每天北京时间 **08:17** 计划同步，也可在 Actions → Sync AgentRoute → Run workflow 手动运行。GitHub 调度可能延迟。`SYNC_STATE.json` 记录实际同步时间、上游完整提交及发布时间；以 Actions 成功结果和该文件为准，不把定时配置当作已运行证明。

同步读取固定上游，先固定 master/release SHA，再检查版本、同代时间、48小时新鲜度、五类 Surge 资源齐全、声明条目大于零、清单文件非空、manifest 全部文件的 SHA256 和 index 对应哈希。全部通过才以一次原子 push 更新三个分支；失败保留上一版本。分支保留自身提交历史，不强推。无变化不创建重复提交。

规则示例：

```
https://raw.githubusercontent.com/tanchaowen84/agent-route-sync/release/surge/proxy.list
```

其他五类规则、格式和索引保持上游路径。index 内原始 URL 未重写，以保留原始字节与哈希；使用镜像时按本仓库 release 相对路径取资源。

## 客户端与人工检查

此任务仅更新 GitHub 快照，**不自动修改或重载客户端**。目前本机 Shadowrocket 仍直接读取官方 release，保留已经验收的 DNS 和个人例外。

更新时比较 source 分支中的 `examples/full/`、`docs/CLIENTS.md`、`docs/DNS-WEBRTC.md`。模板变化需要备份后按字段合并和复测。由 private 名单生成的本地 Host/always-real-ip，以及 Tailscale 静态别名，需另外核对，不会被远程规则刷新自动更新。

本仓库使用自身 GITHUB_TOKEN，权限限本仓库 contents:write；不需要维护者密钥或额外长期令牌。同步过程只读取 Git 对象并复制文件树，不 checkout 或运行上游脚本。

上游项目 GPL-3.0；规则各自来源和许可见 release/source 中的 NOTICE.md、sources.json、licenses/。本仓库同步代码同以 GPL-3.0 发布。
