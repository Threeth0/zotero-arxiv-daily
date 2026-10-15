"""Offline, synthetic examples: no API keys, model calls, downloads or SMTP."""

import argparse
from datetime import date
from pathlib import Path

from .analysis import ExperimentFinding, PaperAnalysis
from .construct_email import render_email, render_email_text
from .protocol import Paper


def example_papers():
    papers = []
    topics = ["VLN"] * 5 + ["Semantic Mapping"] * 4 + ["3D Reconstruction"] * 3 + ["SLAM"] * 3
    for i, topic in enumerate(topics, 1):
        abstract = "Synthetic preview only. The simulated demo success rate is 82.5%. Project: https://example.org/project/demo"
        p = Paper(
            source="zotero" if i > 12 else ("arxiv" if i % 2 else "openalex"),
            title=f"[Demo {i:02d}] {topic}: Task-Aware Spatial Understanding for Indoor Mobile Robots",
            authors=["Example Author A", "Example Author B", "Example Author C"], abstract=abstract,
            url=f"https://example.org/paper/{i}", pdf_url=f"https://example.org/paper/{i}.pdf",
            origin="internal" if i > 12 else "external", primary_topic=topic,
            published_date="2019-06-01" if i % 3 == 0 else "2026-10-01", score=8.1 - i * .1,
            affiliations=["Example Research Institute"],
            recommendation_reason=f"演示：展示与{topic}有关的方法、实验依据和可借鉴思路。此条不是实际论文推荐。",
            analysis=PaperAnalysis(
                summary_en="This fictional example illustrates a bilingual research digest. It is not a real paper recommendation.",
                summary="此卡片使用人工编写的虚构示例，演示每日简报的排版。真实运行时由本次获得的论文文本生成中文解读。",
                problem="演示问题：机器人如何把语言目标与室内空间中的对象联系起来？",
                method="演示方法：结合层级空间记忆与局部观测，在任务执行过程中检索与更新相关信息。",
                contributions=["演示贡献：组织不同粒度的空间信息。", "演示贡献：根据任务选择需要补充的观测。"],
                experiments=[ExperimentFinding("虚构示例的模拟成功率为82.5%，仅用于演示数字与原文依据。", "The simulated demo success rate is 82.5%.")],
                author_limitations=["示例仅覆盖室内场景。"],
                inferred_insights=["演示推断：可比较不同地图粒度对导航成功率和资源开销的影响。"],
                relation="direct" if i < 10 else "indirect",
                relation_reason="演示：可用于理解空间表示、导航决策或机器人状态估计之间的关系。",
                topics=[topic, "Embodied Navigation"], evidence_source="excerpts",
            ),
        )
        if i == 13:
            p.affiliations, p.pdf_url = None, None
            p.analysis.evidence_source = "abstract"
        if i == 14:
            p.analysis = PaperAnalysis(summary=abstract, status="failed")
        if i == 15:
            p.analysis.evidence_source = "full_text"
        papers.append(p)
    return papers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="previews")
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--empty", action="store_true")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    papers = [] if args.empty else example_papers()
    config = {"email": {"subject_prefix": "离线示例 · 虚构论文研究日报", "timezone": "Asia/Shanghai"}}
    stem = "empty-preview" if args.empty else "email-preview"
    (output / f"{stem}.html").write_text(render_email(papers, config, args.date), encoding="utf-8")
    (output / f"{stem}.txt").write_text(render_email_text(papers, config, args.date), encoding="utf-8")
    print(f"Offline preview ({len(papers)} synthetic papers): {output / (stem + '.html')}")


if __name__ == "__main__":
    main()
