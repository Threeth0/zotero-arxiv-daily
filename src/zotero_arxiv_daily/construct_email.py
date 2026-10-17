"""Email-safe single-column digest with a matching plain-text alternative."""

from collections import Counter
from datetime import date as Date, datetime
from html import escape
import math
from zoneinfo import ZoneInfo

from .analysis import EVIDENCE_LABELS, RELATION_LABELS, extract_resource_links, safe_url
from .protocol import Paper
from .reference_text import format_reference_text


def _settings(config):
    return config.get("email", {}) if config is not None else {}


def report_date(config=None, date=None) -> Date:
    zone = ZoneInfo(_settings(config).get("timezone", "Asia/Shanghai"))
    if date is None:
        return datetime.now(zone).date()
    if isinstance(date, datetime):
        if date.tzinfo is None:
            date = date.replace(tzinfo=zone)
        return date.astimezone(zone).date()
    return date if isinstance(date, Date) else Date.fromisoformat(date)


def email_subject(count: int, config=None, date=None) -> str:
    prefix = _settings(config).get("subject_prefix", "论文研究日报")
    return f"{prefix}｜{report_date(config, date).isoformat()}｜{str(count) + '篇' if count else '暂无符合条件的论文'}"


def _text(value):
    return str(value).strip() if value is not None and str(value).strip() else "未提供"


def _e(value):
    return escape(_text(value), quote=True)


def _authors(p):
    authors = list(p.authors or [])
    return ", ".join(authors if len(authors) <= 5 else authors[:3] + ["..."] + authors[-2:]) or "未提供"


def _affiliations(p):
    return (", ".join((p.affiliations or [])[:5]) + (", ..." if len(p.affiliations or []) > 5 else "")) or "未提供"


def _score(p):
    return f"{float(p.score):.1f}" if p.score is not None and math.isfinite(float(p.score)) else "未提供"


def paper_links(p):
    links = [(label, url) for label, value in (("原文", p.url), ("PDF", p.pdf_url)) if (url := safe_url(value))]
    links += extract_resource_links((p.abstract or "") + "\n" + (p.full_text or ""))
    result, seen = [], set()
    for label, url in links:
        if url not in seen:
            result.append((label, url))
            seen.add(url)
    return result


def paper_sections(p):
    a = p.analysis
    if not a or a.status != "ok":
        return [("分析状态", ["结构化解读生成失败；以下保留原始摘要。" if a else "尚未生成结构化解读。"]),
                ("原始摘要" if a else "简要摘要", [(p.abstract if a else p.tldr or p.abstract) or "未提供"]),
                ("实验原文参考", experiment_references(p))]
    experiments = [f"[{i}] {finding.text}" for i, finding in enumerate(a.experiments, 1)]
    if a.omitted_findings:
        experiments.append("部分实验陈述因证据或数字核验未通过，已省略。")
    return [("英文简介", [a.summary_en]), ("中文简介", [a.summary]),
            ("研究问题", [a.problem]), ("核心方法", [a.method]),
            ("作者主张的贡献", a.contributions), ("实验验证", experiments),
            ("实验原文参考", experiment_references(p)),
            ("作者明确的局限", a.author_limitations), ("分析推断与启发", a.inferred_insights),
            ("与VLN / 建图的关系", [a.relation_reason])]


def _evidence(p):
    if not p.analysis:
        return "未分析"
    label = EVIDENCE_LABELS.get(p.analysis.evidence_source, "摘要依据")
    return label + ("（指本次提取文本，不保证覆盖原始论文全部内容）" if p.analysis.evidence_source == "full_text" else "")


def experiment_references(p):
    """One shared, numbered reference section for HTML and plain-text email."""
    values = ["参考范围：" + _evidence(p)]
    if not p.analysis or p.analysis.status != "ok" or not p.analysis.experiments:
        return values + ["未获得通过核验的实验原文摘录。"]
    for i, finding in enumerate(p.analysis.experiments, 1):
        display = format_reference_text(finding.evidence)
        notices = []
        if display.simplified:
            notices.append("简单公式/排版引用已转为可读文字")
        if display.omitted:
            notices.append("复杂公式或损坏字符未完整展示，以原文/PDF为准")
        label = "原文摘录" if not notices else "原文参考（显示已调整：" + "；".join(notices) + "）"
        values.append(f"[{i}] {label}：{display.text}")
    return values


def _overview(papers):
    origins = Counter(p.origin for p in papers)
    topics = Counter(p.primary_topic for p in papers)
    relations = Counter(p.analysis.relation for p in papers if p.analysis and p.analysis.status == "ok")
    return (f"共{len(papers)}篇 · 外部发现{origins['external']}篇 · 库内精读{origins['internal']}篇",
            " · ".join(f"{topic} {count}" for topic, count in topics.items()),
            " · ".join(f"{RELATION_LABELS[key]} {relations[key]}" for key in ("direct", "indirect", "weak")))


def _shortage(papers, config):
    if config is None or not config.get("recommendation", {}).get("enabled", False):
        return ""
    params = config.recommendation
    counts = Counter(p.origin for p in papers)
    shortages = [f"{label}{counts[origin]}/{params.get(key, default)}篇"
                 for origin, label, key, default in (("external", "外部发现", "external_count", 12), ("internal", "库内精读", "internal_count", 3))
                 if counts[origin] < params.get(key, default)]
    return ("今日未满额：" + "，".join(shortages) + "。可能受合格候选、去重、复习间隔或来源可用性影响；详情见运行日志。") if shortages else ""


def _row(label, values):
    body = "<br>".join(_e(value) for value in values) if values else "未提供"
    return f'<tr><td style="padding:8px 0;font-size:14px;line-height:1.75;color:#334155;overflow-wrap:anywhere;word-break:break-word;"><strong style="color:#0f172a;">{escape(label)}</strong><br>{body}</td></tr>'


def get_empty_html():
    return '<p style="padding:24px;color:#475569;line-height:1.8;">今日暂无符合条件的论文。<br>No Papers Today</p>'


def _card(p, number):
    a = p.analysis
    relation = RELATION_LABELS.get(a.relation, "未分析") if a and a.status == "ok" else "未分析"
    origin = "库内精读" if p.origin == "internal" else "外部发现"
    metadata = f"{origin} · {p.source} · {p.primary_topic} · 发表日期：{p.published_date or '未提供'}"
    topics = ", ".join(a.topics) if a and a.topics else p.primary_topic
    rows = _row("推荐理由", [p.recommendation_reason]) if p.recommendation_reason else ""
    rows += "".join(_row(label, values) for label, values in paper_sections(p))
    buttons = " ".join(f'<a href="{escape(url, quote=True)}" style="display:inline-block;margin:4px 8px 4px 0;padding:8px 14px;background:#e8eefb;color:#1e40af;text-decoration:none;border-radius:4px;font-size:13px;">{label}</a>' for label, url in paper_links(p))
    return f'''<tr><td id="paper-{number}" style="padding:24px 22px;border-top:1px solid #dbe2ea;background:#ffffff;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;">
<tr><td style="font-size:12px;line-height:1.7;color:#64748b;overflow-wrap:anywhere;">{number:02d} · {_e(metadata)}</td></tr>
<tr><td style="padding:8px 0;font-size:21px;line-height:1.4;font-weight:700;color:#0f172a;overflow-wrap:anywhere;word-break:break-word;">{_e(p.title)}</td></tr>
<tr><td style="font-size:12px;line-height:1.8;color:#64748b;overflow-wrap:anywhere;">{_e(_authors(p))}<br>{_e(_affiliations(p))}</td></tr>
<tr><td style="padding:10px 0;font-size:12px;line-height:1.8;color:#1e40af;overflow-wrap:anywhere;">库相似度 {_score(p)} · {_e(relation)}<br>{_e(topics)}</td></tr>
{rows}<tr><td style="padding-top:12px;">{buttons or '阅读链接：未提供'}</td></tr></table></td></tr>'''


def render_email(papers: list[Paper], config=None, date=None) -> str:
    heading = _settings(config).get("subject_prefix", "论文研究日报")
    overview = _overview(papers)
    directory = "".join(f'<p style="margin:7px 0;font-size:13px;line-height:1.6;"><a href="#paper-{i}" style="color:#1e40af;text-decoration:none;">{i:02d}. {_e(p.title)}</a></p>' for i, p in enumerate(papers, 1))
    content = "".join(_card(p, i) for i, p in enumerate(papers, 1)) if papers else f"<tr><td>{get_empty_html()}</td></tr>"
    shortage = _shortage(papers, config)
    note = f'<p style="font-size:12px;line-height:1.7;color:#92400e;">{_e(shortage)}</p>' if shortage else ""
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(heading)}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,'Microsoft YaHei',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px 8px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;table-layout:fixed;background:#ffffff;">
<tr><td style="padding:26px 22px;background:#0f2747;color:#ffffff;">
<p style="margin:0 0 8px;font-size:12px;letter-spacing:1px;">RESEARCH DIGEST · {report_date(config, date).isoformat()}</p>
<h1 style="margin:0;font-size:26px;line-height:1.4;">{_e(heading)}</h1>
<p style="margin:12px 0 0;font-size:13px;line-height:1.8;">{_e(overview[0])}<br>{_e(overview[1])}<br>{_e(overview[2])}</p></td></tr>
<tr><td style="padding:18px 22px;background:#f8fafc;overflow-wrap:anywhere;">
<strong style="font-size:14px;color:#0f172a;">今日阅读目录</strong>{directory}{note}
<p style="font-size:12px;line-height:1.7;color:#64748b;">库相似度用于衡量与Zotero参考论文的接近程度，不代表论文质量。主题配额灵活分配，不限制发表年份。</p></td></tr>
{content}
<tr><td style="padding:22px;font-size:12px;line-height:1.8;color:#64748b;background:#f8fafc;">结构化解读由模型基于本次可获得的文本生成；实验原文参考与实验结果编号对应，公式显示调整会明确标记，以原文/PDF为准。分析推断已单独标记。<br>停止接收：停用GitHub Actions定时任务，或调整收件人配置。</td></tr>
</table></td></tr></table></body></html>'''


def render_email_text(papers: list[Paper], config=None, date=None) -> str:
    lines = [email_subject(len(papers), config, date), "", *_overview(papers), _shortage(papers, config)]
    if not papers:
        lines.append("今日暂无符合条件的论文。No Papers Today")
    for i, p in enumerate(papers, 1):
        relation = RELATION_LABELS.get(p.analysis.relation, "未分析") if p.analysis and p.analysis.status == "ok" else "未分析"
        lines.extend(["", "─" * 36, f"{i:02d}. {p.title}", f"{'库内精读' if p.origin == 'internal' else '外部发现'} · {p.primary_topic} · {p.source}",
                      f"发表日期：{p.published_date or '未提供'}", _authors(p), _affiliations(p), f"库相似度：{_score(p)} · {relation}"])
        if p.recommendation_reason:
            lines.extend(["推荐理由", p.recommendation_reason])
        for label, values in paper_sections(p):
            lines.extend(["", label, *(values or ["未提供"])])
        lines.extend(f"{label}：{url}" for label, url in paper_links(p))
    lines.extend(["", "库相似度不是论文质量评分。停止接收请停用GitHub Actions定时任务或调整收件人。"])
    return "\n".join(lines)


def get_block_html(title: str, authors: str, rate: str, tldr: str, pdf_url: str, affiliations=None):
    """Legacy helper, with escaping and URL validation."""
    p = Paper(source="arxiv", title=title, authors=[authors], abstract=tldr or "", url="", pdf_url=pdf_url,
              affiliations=[affiliations] if affiliations else None)
    return _card(p, 1) + f'<p>库相似度：{_e(rate)}</p>'


def get_stars(score: float):
    if score <= 6:
        return ""
    half_count = min(10, math.ceil((score - 6) / .2))
    return '<span class="full-star">⭐</span>' * (half_count // 2) + '<span class="half-star">⭐</span>' * (half_count % 2)
