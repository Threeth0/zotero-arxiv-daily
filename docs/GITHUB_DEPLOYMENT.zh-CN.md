# GitHub 每日推荐部署指南

本文对应本仓库当前版本。只修改本地文件不会影响 GitHub，必须上传到远程仓库的默认分支后才会生效。本指南不要求把 Zotero 数据库或 PDF 上传到 GitHub。

## 1. 已固定的推荐规则

正式入口在所有配置合并后应用 `src/zotero_arxiv_daily/policy.py`：

| 项目 | 固定规则 |
| --- | --- |
| 每日总量 | 最多15篇，不强制凑数 |
| 外部发现 | 最多12篇 |
| Zotero 库内复习 | 最多3篇 |
| 主题软目标 | VLN 5、Semantic Mapping 4、3D Reconstruction 3、SLAM 3 |
| 时间窗口 | 不限制论文发表年份 |
| 简介顺序 | 英文简介 → 中文简介 → 研究问题 → 核心方法 → 贡献 → 实验 → 局限 → 推断 → 研究关系 |

候选不足时，不跨“外部/内部”来源凑数；主题之间仍按相关性与可用数量灵活分配。同一日期已有成功发送记录时，重复手动运行将跳过，不再发送第二批。这个保护依赖恢复到正确的历史快照；不要删除运行历史附件。

`MAX_PAPER_NUM`、`CUSTOM_CONFIG` 等 Actions 变量不能改变这些规则。正式工作流不读取旧的 `CUSTOM_CONFIG`、`REPOSITORY`、`REF`；配置入口改为版本控制内的 `config/github.yaml`。要有意修改固定数量或比例，需要修改 `policy.py` 并提交代码。

## 2. 上传当前本地修改

当前项目已经是 Git 仓库，`origin` 指向：

https://github.com/Threeth0/zotero-arxiv-daily.git

不需要再次 `git init`，也不需要重新添加 origin。先确认这是你有写权限、希望运行日报的仓库。

在终端中进入项目：

```bash
cd /home/rob508/Workspace/YJB/zotero-arxiv-daily
git status --short
git branch --show-current
git remote -v
```

当前工作分支为 `main`。先审查修改，确认没有真实 API Key、SMTP 授权码、密码或私人配置。不要上传 `.env`、`config/private.yaml`、`state/`、PDF 或 Zotero 数据库。`config/custom.yaml` 是旧本地配置入口，不要把真实密钥写进去后提交。

本次功能涉及的文件可以这样加入提交：

```bash
git add .github/workflows/main.yml .github/workflows/test.yml
git add src tests config/base.yaml config/github.yaml
git add README.md docs/GITHUB_DEPLOYMENT.zh-CN.md .gitignore
git add assets/email-preview.html assets/email-preview.txt assets/empty-preview.html assets/empty-preview.txt
git diff --cached --stat
git commit -m "Add bilingual summaries and freeze daily recommendation policy"
git push origin main
```

如果 GitHub 要求身份验证，使用 GitHub CLI 的 `gh auth login` 或你已经配置的 SSH/个人访问令牌。不要使用 GitHub 登录密码代替 Git 推送凭据；不要把令牌写进远程地址或文件。若提示无写权限，先核对账号及仓库归属；若提示分支领先/落后，先协调远端更新，**不要强制推送**。

若仓库有分支保护，需要先在你自己的功能分支提交，再通过 Pull Request 合并到默认分支。仅上传到非默认分支，不会启用该分支上的每日定时任务。

## 3. 准备 Zotero 云端访问

GitHub 托管的运行器无法访问你电脑的本地 Zotero API。需要：

1. 在 Zotero Desktop 中完成同步，让云端包含你希望参与推荐的论文题录与摘要。
2. 打开 https://www.zotero.org/settings/keys ，取得数字形式的 User ID，并创建 API Key。
3. Key 授予所用个人库的读取权限；不用写入权限。需要读取附件全文时，应具备相应文件读取权限，且全文在云端可用。

只有题录/摘要也可以运行；全文不可用时会按摘要依据生成解读。正式流程当前使用个人库，不是群组库。电脑之后可以关机，Zotero Desktop 不必一直开着，但以后新增的论文要同步到云端才会被看到。

## 4. 配置 Repository secrets

打开仓库：`Settings → Secrets and variables → Actions → Secrets → New repository secret`。

逐项新增，名称必须完全一致：

| Secret 名称 | 填写内容 |
| --- | --- |
| `ZOTERO_ID` | Zotero 数字 User ID，不是用户名 |
| `ZOTERO_KEY` | 上一步创建的只读 Zotero API Key |
| `SENDER` | 发件邮箱完整地址 |
| `RECEIVER` | 收件邮箱完整地址；当前实现使用单个收件人 |
| `SENDER_PASSWORD` | 邮箱提供商的 SMTP 授权码/应用专用密码，通常不是网页登录密码 |
| `OPENAI_API_KEY` | 所选兼容接口的模型 API Key |
| `OPENAI_API_BASE` | 所选兼容接口的基础地址，例如 `https://api.openai.com/v1`；不是聊天网页地址，也不是完整 `/chat/completions` 地址 |
| `OPENALEX_API_KEY` | 按 OpenAlex 当前访问要求配置；没有时其鉴权/配额限制可能使该来源不可用 |

前7项是工作流启动检查的必填项。`OPENALEX_API_KEY` 从程序角度为可选，但要稳定使用开放获取期刊/会议发现，应取得可用访问权限与配额。外部服务收费和额度独立于 GitHub Actions；ChatGPT 订阅不能代替 API Key。

不要把密钥放在 Variables、README、聊天截图或代码中。Secrets 保存后无法回读原文，需要替换时重新设置。

## 5. 配置 Repository variables

同一页面切到 `Variables → New repository variable`：

| Variable 名称 | 用途 | 未设置时 |
| --- | --- | --- |
| `SMTP_SERVER` | 发件邮箱服务商提供的 SMTP 主机 | `smtp.qq.com` |
| `SMTP_PORT` | SMTP 端口 | `465` |
| `LLM_MODEL` | API 账号实际可调用、支持聊天补全的模型 ID | `gpt-4o-mini` |

QQ 邮箱示例：开启邮箱设置中的 SMTP 服务，使用服务商生成的授权码，主机 `smtp.qq.com`，端口 `465`。其他邮箱请以服务商文档为准，不要只更换发件地址却保留 QQ 主机。

465 端口使用 SSL 直连；其他端口要求 STARTTLS。连接有超时，TLS 失败时不会回退到明文发送密码。不支持只接受 OAuth2、却不接受应用密码的 SMTP 账号直接登录。

如果使用非 OpenAI 服务，必须将 `LLM_MODEL` 改成该服务实际支持的模型 ID。旧 `CUSTOM_CONFIG` 不再参与正式工作流：其中的模型、SMTP、研究简介、分类筛选配置需迁移。模型和 SMTP 按上表设置；研究简介、筛选规则与其他非敏感参数直接编辑 `config/github.yaml`，然后提交。

默认嵌入排序使用本地模型，在 GitHub 运行器上首次下载可能较慢。无需另配 embedding API Key；如果想换成 API 排序，应有意修改仓库配置并配置对应密钥，不能假设所有聊天接口都支持 embeddings。

## 6. 启用并检查工作流

仓库内已包含工作流，不需要在网页“新建”一份重复文件：

- `.github/workflows/main.yml`，显示名 `Send emails daily`：正式检索、分析、发送。
- `.github/workflows/test.yml`，显示名 `Test`：生成15篇虚构离线预览，不调用模型、不发送邮件，也不使用 Secrets。

检查：

1. 在仓库 `Settings → General` 确认默认分支为你已上传这些文件的 `main`。
2. 在 `Settings → Actions → General` 确认允许工作流与所用的 checkout、setup-uv、upload-artifact actions。
3. 打开仓库 `Actions`。若是 fork 后看到禁用提示，按页面提示启用，并检查具体工作流没有处于 Disabled 状态。
4. 本工作流已经声明 `contents: read` 和 `actions: read`。不需要为了日报开启全仓库写权限，也不需要另建 PAT 存历史。

每天计划在 UTC 22:17，即**北京时间次日06:17**触发。邮件实际到达还要加上下载依赖、检索、模型分析和发送耗时。主题日期按 `Asia/Shanghai` 生成。若想改触发时间，编辑 `main.yml` 的 cron 并提交；这不会改变论文数量。

工作流只检出当前仓库此次运行的代码，不受旧 `REPOSITORY / REF` 变量影响。安装依赖使用 `uv.lock` 的锁定版本。

## 7. 先预览，再手动做一次真实验收

### 离线预览

`Actions → Test → Run workflow → 选择 main → Run workflow`。

成功后打开该次运行，在 Artifacts 下载 `email-previews`，打开其中 HTML。该结果是明确标记的虚构样例，只验证版式，不能证明 Zotero、模型或邮箱已连通。

### 真实发送

配置完所有 Secrets/Variables 后：

`Actions → Send emails daily → Run workflow → 选择 main → Run workflow`。

这会真实调用外部服务并发送一封日报，可能产生 API 费用。依次检查：

1. `Check required secrets` 成功，没有缺失项。
2. 依赖安装完成。
3. 首次恢复历史时允许出现“没有历史快照”的警告；后续应能恢复 `recommendation-state`。
4. 运行日志显示固定规则 `at most 15 papers; external 12 + internal 3; soft topics 5/4/3/3`。
5. 日志能获取 Zotero 论文，检索来源可用，没有持续鉴权/配额错误。
6. 正常发送时出现 `Sent N recommendations; delivery history updated`；若当日已成功发送，会明确跳过。
7. 收件箱或垃圾箱收到邮件；每篇英文简介在中文简介之前；篇数不超过15。
8. 运行底部存在 `recommendation-state` 附件。第二天运行会继续使用累计历史。

如果没有合格候选，GitHub 部署配置会发送明确的空状态日报；它不会捏造15篇。若 Zotero 完全没有可用摘要，任务会报错，不会把配置问题伪装成正常的“无论文”。候选短缺、正文不可提取和分析降级会在邮件/日志说明。

同一天重复手动运行不会再发第二批；这不意味着每次点击都能测试 SMTP。若只是检查版式，请使用 Test。不要为反复测试随意删除正式历史。

## 8. 每天运行的可靠性边界

GitHub Actions 的 schedule **不是准点投递保证**：高峰时可能延迟，严重负载下可能丢弃排队任务。已选非整点时间以降低高峰影响，但不能承诺永不漏发。

还需要注意：

- 定时只运行默认分支上的工作流。
- 公开仓库60天无仓库活动，定时工作流可能被自动禁用；定期检查 Actions 状态，不要仅凭过去成功过就认为一直有效。
- 账号的 Actions 用量/计费额度、外部 API 余额、服务可用性、SMTP 授权码及垃圾邮件过滤都可能影响收信。
- 在 GitHub 账号通知设置中启用 Actions 失败通知。如果未收到日报，先看 Actions 运行记录，再检查邮件垃圾箱；从未触发的任务不会产生失败通知。
- 工作流失败后修复首个报错再重跑，不对整条发送流程做盲目重试。SMTP 已接受邮件、但历史尚未上传就发生崩溃，仍存在重复发送的边界情况。
- 若要求“任何情况下都不能漏掉某一天”，还需要独立的外部可用性监控或备用调度；本仓库没有替你额外开通这些服务。

## 9. 历史保留与隐私

同分支运行串行执行，避免同时覆盖历史。历史以 `recommendation-state` 附件恢复与保存，包含累计去重标识、发送日期、复习历史、检索游标及公开候选元数据，不包含 API 密钥、私人正文或 PDF。

每个快照申请90天保留，实际还受仓库/组织策略与配额限制。每天正常运行会不断生成新的累计快照，但长时间停用、手动删除附件或保留策略缩短都可能丢失历史。停用前下载最新快照备份。库内标识可能敏感，优先考虑私有仓库并控制访问者；不要把状态提交到公共 Git。

## 10. 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 看不到 Run workflow | 文件是否已推送到默认分支、Actions 是否启用、是否有操作权限 |
| 缺少 Secret | 必填名称是否一致，是否建成 Repository secret 而不是 Variable |
| Zotero 401/403 或无摘要 | User ID、Key 权限、个人库同步与摘要字段 |
| 模型401/404/限额 | API Key、基础地址、模型 ID、余额/配额 |
| OpenAlex 失败 | 对应 Key/配额，其他来源是否正常；不能把来源失败当作当天没有文献 |
| SMTP 认证失败 | SMTP 是否启用、是否用了授权码、服务器与发件地址是否匹配 |
| 任务绿灯但没新邮件 | 日志是否“今日已发送”；是否在垃圾箱；SMTP 接受不等于最终进收件箱 |
| 总是重复推荐 | 历史附件是否被删除/过期，恢复步骤是否成功，是否换了运行分支 |
| 少于15篇 | 合格数量、去重、内部复习间隔、来源失败；不强行凑数 |

## 官方参考

- [上传本地代码](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github?platform=linux)
- [Actions Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [Actions Variables](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables)
- [定时与手动触发规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
