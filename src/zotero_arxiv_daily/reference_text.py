"""Conservative plain-text math display for email, not a general TeX renderer.

Only the display copy changes. Raw evidence is retained for source verification.
Unknown syntax is withheld, rather than guessed or silently stripped.
"""

from dataclasses import dataclass
import re


FORMULA_NOTICE = "[复杂公式省略，请核对原文/PDF]"
_MATH = re.compile(
    r"\\begin\{(?P<environment>equation\*?|align\*?|aligned|gather\*?|multline\*?|displaymath)\}"
    r".*?\\end\{(?P=environment)\}"
    r"|\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<![\\$])\$(?!\$)(?:\\.|[^$\\])*?(?<!\\)\$(?!\$)",
    re.DOTALL,
)
_BROKEN_TEXT = re.compile(r"[\ufffd\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd\x00-\x08\x0b\x0c\x0e-\x1f]")
_COMMANDS = {
    "alpha": "alpha", "beta": "beta", "gamma": "gamma", "delta": "delta",
    "epsilon": "epsilon", "theta": "theta", "lambda": "lambda", "mu": "mu",
    "sigma": "sigma", "pi": "pi", "tau": "tau", "omega": "omega",
    "Delta": "Delta", "Sigma": "Sigma", "Omega": "Omega",
    "times": " × ", "cdot": " · ", "pm": " +/- ",
    "leq": " <= ", "le": " <= ", "geq": " >= ", "ge": " >= ",
    "neq": " != ", "approx": " approx. ", "infty": "infinity",
    "rightarrow": " -> ", "leftarrow": " <- ",
    "quad": " ", "qquad": " ", "left": "", "right": "",
}


@dataclass(frozen=True)
class ReferenceText:
    text: str
    simplified: bool = False
    omitted: bool = False


def _simple_inline_math(value: str) -> str | None:
    """Translate only a deliberately small subset with unambiguous grouping."""
    for _ in range(6):
        previous = value
        value = re.sub(r"\\(?:mathrm|textrm|text|operatorname)\{([^{}]*)\}", r"\1", value)
        value = re.sub(r"\\(?:frac|dfrac|tfrac)\{([^{}]*)\}\{([^{}]*)\}", r"((\1)/(\2))", value)
        if value == previous:
            break
    value = re.sub(r"\^\s*(?:\{\\circ\}|\\circ)(?![A-Za-z])", "°", value)
    value = re.sub(r"\\([A-Za-z]+)", lambda match: _COMMANDS.get(match[1], match[0]), value)
    for command, plain in ((r"\%", "%"), (r"\_", "_"), (r"\,", " "), (r"\;", " "), (r"\!", "")):
        value = value.replace(command, plain)
    # Nested subscripts/superscripts and unknown commands need a real TeX parser.
    value = re.sub(r"([_^])\{([^{}]*)\}", r"\1(\2)", value)
    if "\\" in value or "{" in value or "}" in value or len(value) > 240:
        return None
    return re.sub(r"\s+", " ", value).strip()


def format_reference_text(raw: str) -> ReferenceText:
    """Return display text and an explicit notice when the original is changed."""
    if _BROKEN_TEXT.search(raw):
        return ReferenceText("原文摘录含损坏或无法可靠显示的字符，未展示；请核对原文/PDF。", omitted=True)
    simplified, omitted = False, False

    def replace_math(match):
        nonlocal simplified, omitted
        token = match[0]
        if token.startswith(("$$", r"\[", r"\begin")):
            omitted = True
            return FORMULA_NOTICE
        body = token[2:-2] if token.startswith(r"\(") else token[1:-1]
        plain = _simple_inline_math(body)
        if plain is None:
            omitted = True
            return FORMULA_NOTICE
        simplified = True
        return plain

    display = _MATH.sub(replace_math, raw)
    # Source TeX also contains prose formatting and cross-references. Remove only
    # known style wrappers; retain citation/ref IDs explicitly, never invent numbers.
    before_markup = display
    for _ in range(6):
        previous = display
        display = re.sub(r"\\(?:textbf|textit|emph|textrm|textnormal|texttt)\{([^{}]*)\}", r"\1", display)
        if previous == display:
            break
    display = re.sub(r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear)\*?\{([^{}]*)\}",
                     lambda match: "[文献引用：" + match[1] + "]", display)
    display = re.sub(r"\\(?:ref|eqref|autoref|cref|Cref|pageref)\{([^{}]*)\}",
                     lambda match: "[原文交叉引用：" + match[1] + "]", display)
    display = display.replace("~", " ")
    simplified = simplified or before_markup != display
    # Undelimited/unbalanced TeX cannot be safely segmented from a prose quotation.
    if re.search(r"\\[A-Za-z]+|\\[()[\]]|(?<!\\)\$", display):
        return ReferenceText("原文摘录含无法安全显示的公式或排版命令，未展示；请核对原文/PDF。", omitted=True)
    if r"\%" in display:
        display = display.replace(r"\%", "%")
        simplified = True
    return ReferenceText(display, simplified=simplified, omitted=omitted)
