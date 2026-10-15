# Zotero-arXiv-Daily

A daily bilingual paper digest based on your Zotero library, with historical external discovery and spaced library review.

## 当前部署入口

请按 [GitHub 每日推荐部署指南（中文）](docs/GITHUB_DEPLOYMENT.zh-CN.md) 操作：上传代码、配置 Secrets/Variables、启用工作流、手动验收和日常故障检查均在其中。

旧的 `CUSTOM_CONFIG`、`REPOSITORY`、`REF` Actions 变量不再被正式工作流读取。云端使用仓库内的 `config/github.yaml`，而不是把网页变量写成任意 YAML。

## 固定推荐规则

| 项目 | 规则 |
| --- | --- |
| 每日总量 | 最多15篇；不足不凑数 |
| 外部发现 | 最多12篇，arXiv + OpenAlex 索引的开放获取期刊/会议论文 |
| 库内复习 | 最多3篇，未推送优先，轮完后默认间隔90天 |
| 主题软目标 | VLN 5、Semantic Mapping 4、3D Reconstruction 3、SLAM 3 |
| 发表时间 | 不设年份窗口 |
| 简介 | 英文简介在前，中文简介在后 |
| 重复运行 | 有当天成功发送历史时跳过，不再发送第二批 |

正式入口在配置合并后应用 `src/zotero_arxiv_daily/policy.py`，固定总量、来源上限、主题目标和新推荐模式。修改环境变量、旧网页配置或命令行数量参数不能覆盖它们；有意改变规则必须修改代码。

## 邮件内容

英文原始标题、作者/机构、来源、发表日期、库相似度、主题标签、推荐理由，然后按以下顺序展示：

英文简介 → 中文简介 → 研究问题 → 核心方法 → 作者主张的贡献 → 实验验证 → 作者明确的局限 → 分析推断与启发 → 与 VLN/建图的关系 → 证据来源与阅读链接。

HTML 使用680px单栏表格与内联样式，同时提供纯文本版本。内容统一 HTML 转义，链接仅允许 HTTP/HTTPS，Code/Project 链接只从实际输入中提取。实验含原文支持片段；数字/证据核验失败时省略。生成失败保留原始摘要及失败状态，不伪造英中文解读。

## GitHub Actions

- `Send emails daily`：北京时间每天06:17计划触发，也支持手动运行；真实检索、调用模型和发送邮件。
- `Test`：仅生成15篇明确标注的虚构预览，不调用模型、不使用密钥、不发送邮件。
- `config/github.yaml`：云端配置；必填 Secrets 与可选 SMTP/模型变量见部署指南。
- 安装按 `uv.lock` 锁定；同分支串行运行；累计历史通过 `recommendation-state` 附件恢复/保存。

定时工作流必须存在于默认分支。GitHub 调度可能延迟/漏触发，公开仓库长期无活动可能被停用；不能保证准点、永不漏发。首次部署必须手动完成一次真实收信验收，并启用失败通知。[官方触发规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## Local use and offline preview

Requires Python 3.13+ and [uv](https://github.com/astral-sh/uv).

```bash
uv run --frozen python -m zotero_arxiv_daily.preview --output-dir previews
uv run --frozen python -m zotero_arxiv_daily.preview --output-dir previews --empty
uv run --frozen pytest
```

预览不需要任何密钥，HTML/纯文本输出到 `previews/`。仓库内 `assets/email-preview.html` 是已生成的虚构版式示例，不是真实研究结论。

配置好相应环境变量后，也可在本机使用同一云端配置入口：

```bash
uv run --frozen src/zotero_arxiv_daily/main.py --config-name github
```

上述命令会真实调用外部服务并发信。`config/default.yaml`/`config/custom.yaml` 仍可用于原有本地凭据与非敏感参数配置，但主入口也会应用固定推荐策略。旧 RSS 检索组件保留供代码级兼容使用，不通过网页变量切换正式日报。配置字段见 `config/base.yaml`。

## How recommendations work

1. Read synced Zotero personal-library metadata and apply optional include/ignore collection patterns.
2. Discover bounded historical arXiv/OpenAlex pages, combine cached public candidates, and exclude already-owned/sent external works.
3. Rank by abstract similarity. Recent Zotero *additions* carry more interest weight; publication age does not impose eligibility or a recency bonus.
4. Use bounded abstract-only model triage to assign one primary topic and a reading priority. Priority is heuristic, not a scientific paper-quality score.
5. Select up to12 external +3 internal papers under soft topic targets. Stronger relevant papers take precedence; source shortages are not swapped.
6. Extract text only for selected papers, generate bilingual structured analysis in one call and affiliations separately, and render/send one multipart email.
7. Mark identities and the delivery date only after SMTP accepts the message, then persist cumulative history.

DOI, versionless arXiv IDs and normalized exact titles identify duplicates. Changed titles without linked identifiers cannot always be merged. Internal similarity excludes the paper itself. A first/empty library or invalid credentials should be investigated, not treated as a normal empty recommendation day.

## Evidence and limitations

The default analysis input budget is12000 tokens for title, abstract and body excerpts; prompts are additional. Methods, experiments, discussion and conclusion are prioritized; otherwise the input samples across the text. Labels distinguish abstract-only, body excerpts and complete *extracted* text. The last label does not certify complete PDF extraction.

Experimental findings require a verbatim supporting span and matching numeric tokens. This mechanical check does not prove the interpretation correct. Author claims, explicit limitations and inferred insights are separated.

- OpenAlex is an index, not a promise that every full text can be fetched. Only explicit open-access locations are used.
- arXiv, OpenAlex, Zotero, model and SMTP availability/quotas remain external dependencies. API calls may cost money.
- GitHub runners access synced Zotero cloud data, not your computer's local Desktop API. Group libraries are not the current deployment profile.
- Artifacts contain cumulative identity/review/search metadata, not credentials, private body text or PDFs. Library identifiers can still be sensitive.
- Snapshots request90-day retention, subject to GitHub policy/quota. Back up before long pauses; missing state means fresh history.
- Same-day deduplication depends on preserved state. A crash between SMTP acceptance and state persistence remains ambiguous; exact-once delivery is not guaranteed.
- SMTP port465 uses verified SSL directly; other ports require verified STARTTLS with timeout. No plaintext password fallback.
- Real email-client rendering and final inbox delivery require actual recipient testing.

## License

See [LICENSE](LICENSE).
