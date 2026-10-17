import pytest

from tests.canned_responses import make_sample_paper
from tests.test_recommendation_digest import analysis_json
from zotero_arxiv_daily.analysis import ExperimentFinding, PaperAnalysis, parse_analysis
from zotero_arxiv_daily.construct_email import render_email, render_email_text, experiment_references
from zotero_arxiv_daily.reference_text import FORMULA_NOTICE, format_reference_text


def paper_with_evidence(evidence, **kwargs):
    return make_sample_paper(analysis=PaperAnalysis(
        summary="中文简介", summary_en="English overview.",
        experiments=[ExperimentFinding("成功率为82.5%。", evidence)], **kwargs,
    ))


@pytest.mark.parametrize("render", [render_email, render_email_text])
def test_combines_scope_and_numbered_excerpt_directly_after_experiments(render):
    paper = paper_with_evidence("Success is 82.5%.", evidence_source="excerpts")
    output = render([paper])
    assert output.count("实验原文参考") >= 1
    assert "证据来源" not in output and "实验原文依据" not in output
    assert output.index("实验验证") < output.index("实验原文参考") < output.index("作者明确的局限")
    assert "参考范围：正文节选依据" in output
    assert "[1] 成功率为82.5%。" in output
    assert "[1] 原文摘录：Success is 82.5%." in output


@pytest.mark.parametrize("raw,expected", [
    (r"Success is \(\mathrm{SR}=82.5\%\).", "Success is SR=82.5%."),
    (r"Error is $x_{i}^{2} + \alpha \leq 0.5$.", "Error is x_(i)^(2) + alpha <= 0.5."),
    (r"Ratio $\frac{a+b}{c+d}$.", "Ratio ((a+b)/(c+d))."),
    (r"Area is $\mathrm{cm}^{2}$.", "Area is cm^(2)."),
    (r"Accuracy is 82.5\%.", "Accuracy is 82.5%."),
])
def test_supported_inline_math_uses_explicit_plain_text(raw, expected):
    display = format_reference_text(raw)
    assert display.text == expected
    assert display.simplified and not display.omitted


@pytest.mark.parametrize("raw", [
    r"Measured 82.5%. $$\sum_{i=1}^{N}s_i$$ remains.",
    r"Measured 82.5%. \[\frac{a}{b}\] remains.",
    r"Measured 82.5%. \begin{align} a &= b \\ c &= d \end{align} remains.",
    r"Measured 82.5%. $\unknownmacro{x}$ remains.",
    r"Measured 82.5%. $x_{i_{j}}$ remains.",
])
def test_complex_math_is_not_guessed(raw):
    display = format_reference_text(raw)
    assert display.omitted and FORMULA_NOTICE in display.text
    assert "82.5%" in display.text and "remains" in display.text
    assert "\\" not in display.text and "$$" not in display.text


@pytest.mark.parametrize("raw", [
    "Success is 82.5%. \ufffd", "Success is 82.5%. \ue001",
    "Success is 82.5%. \x0c", r"Success is 82.5%. \frac{a}{b}",
    r"Success is 82.5%. \(x + y", "Success is $82.5%.",
])
def test_corrupt_or_unsegmented_source_is_withheld(raw):
    display = format_reference_text(raw)
    assert display.omitted and "未展示" in display.text
    assert "原文/PDF" in display.text


def test_unmodified_prose_is_kept_verbatim():
    raw = 'TUM-RGBD evaluates ATE; accuracy is 82.5%, with x < y & "A".'
    display = format_reference_text(raw)
    assert display.text == raw and not display.simplified and not display.omitted


def test_verification_uses_original_evidence_and_never_display_copy():
    raw = r"Success is \(\mathrm{SR}=82.5\%\)."
    analysis = parse_analysis(analysis_json(experiments=[
        {"text": "成功率82.5%", "evidence": raw},
    ]), raw, "excerpts")
    paper = make_sample_paper(analysis=analysis)
    html = render_email([paper])
    assert "SR=82.5%" in html and "显示已调整" in html
    assert analysis.experiments[0].evidence == raw
    unsupported = parse_analysis(analysis_json(experiments=[
        {"text": "成功率82.5%", "evidence": "Success is SR=82.5%."},
    ]), raw, "excerpts")
    assert not unsupported.experiments and unsupported.omitted_findings == 1


def test_reference_content_remains_html_escaped():
    paper = paper_with_evidence(r"Success 82.5%, $a < b$ <script>alert(1)</script> & text.")
    output = render_email([paper])
    assert "&lt;script&gt;" in output and "<script>" not in output
    assert "a &lt; b" in output


@pytest.mark.parametrize("status", ["ok", "failed"])
def test_no_verified_excerpt_does_not_invent_one(status):
    paper = make_sample_paper(analysis=PaperAnalysis(summary="Summary", status=status))
    assert "未获得通过核验" in " ".join(experiment_references(paper))


def test_failed_analysis_does_not_display_stale_experiments():
    paper = paper_with_evidence("STALE EVIDENCE", status="failed")
    assert "STALE EVIDENCE" not in render_email([paper])


def test_full_extracted_text_disclaimer_is_preserved_without_pdf():
    paper = paper_with_evidence("Success is 82.5%.", evidence_source="full_text")
    paper.pdf_url = None
    assert "不保证覆盖原始论文全部内容" in render_email_text([paper])
    assert 'href="None"' not in render_email([paper])


def test_goal2pixel_user_example_renders_prose_math_and_references_safely():
    raw = r"""On R2R-CE Val-Unseen it achieves 54.1% SR and 52.5% SPL with just 7.75 VLM calls per episode, 6x fewer than the 46.62 required by direct action prediction at 32.9% SR.
The same trend holds on RxR-CE.
For \textbf{training}, Goal2Pixel is initialized from InternVL3~\cite{internvl} and fine-tuned for one epoch on our 2.64M-sample VLN-CE corpus from R2R-CE~\cite{r2r-ce} and RxR-CE~\cite{rxr}. We fully fine-tune the LLM backbone and projection layers while freezing the vision encoder. The learning rate is $2\times10^{-5}$, with at most 8 history images. The numeric and angular loss weights are 0.3 and 0.03. The 2B and 7B models require 80 and 176 H100 GPU hours, respectively.
Following the common VLN-CE protocol, the RGB camera has a $90^\circ$ horizontal field of view and produces observations with a resolution of $256 \times 256$ pixels.
We conduct 16 real-world navigation trials to qualitatively evaluate the transferability of Goal2Pixel to a physical robot. Fig.~\ref{fig:real_world demo} shows two representative examples, with more in Appendix~\ref{app:real_world}."""
    analysis = parse_analysis(analysis_json(experiments=[{
        "text": "R2R-CE Val-Unseen：SR54.1%、SPL52.5%，平均调用7.75次。", "evidence": raw,
    }]), raw, "excerpts")
    display = format_reference_text(raw)
    assert display.simplified and not display.omitted
    assert "For training" in display.text
    for expected in ("2 × 10^(-5)", "90°", "256 × 256", "[文献引用：internvl]",
                     "[原文交叉引用：fig:real_world demo]", "16 real-world"):
        assert expected in display.text
    assert "\\" not in display.text and "$" not in display.text
    assert analysis.experiments[0].evidence == raw
    paper = make_sample_paper(analysis=analysis)
    for output in (render_email([paper]), render_email_text([paper])):
        assert "90°" in output and "256 × 256" in output
        assert "显示已调整" in output


def test_citation_markup_does_not_allow_html_injection():
    paper = paper_with_evidence(r"Result 82.5%. \cite{<script>alert(1)</script>}.")
    output = render_email([paper])
    assert "文献引用：&lt;script&gt;" in output and "<script>" not in output
