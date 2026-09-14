#!/usr/bin/env python3
"""마크다운 문서에서 형태로 판별할 수 있는 규칙 위반을 찾는다

의존성이 없고 파이썬 3.9 이상에서 실행된다
LLM 을 부르지 않고, 형태로 판별할 수 있는 규칙만 검사한다

**형태로 판별하는 규칙과 읽어서 판단하는 규칙을 나눈다**
줄표가 있는지, 표 칸이 몇 자인지, 제목이 의문형인지는 형태를 보면 판별된다
쉽게 썼는지, 이 문단이 필요한지는 형태로 판별할 수 없으므로 prompts/ 의 지침을 읽는 사람과 LLM 에게 맡긴다

코드 블록과 인라인 코드는 검사하지 않는다
그대로 실행되거나 복사되는 부분이라 문체를 고치면 동작이 달라진다

**검사를 끄는 방법을 둔다**
규칙 문서는 금지한 것을 예로 들어야 해서 스스로 규칙을 어긴다
「줄표를 쓰지 않는다, 예: 앞 — 뒤」 같은 줄이 그렇다
줄 끝에 `<!-- doccheck: off -->` 를 달면 그 줄을 건너뛴다
파일 첫머리에 `<!-- doccheck: off em-dash,trailing-period -->` 를 두면 그 파일 전체에서 끈다
"""

# 타입 표기를 실행 중에 계산하지 않게 해 macOS 기본 파이썬 3.9 에서도 불러올 수 있게 한다
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# MARK: - 기본값

# 표 칸이 이보다 길면 구(句)를 넘긴 것으로 본다
# 넘기면 표를 정의 목록으로 바꾸라는 뜻이지, 칸을 줄여 쓰라는 뜻이 아니다
CELL_LIMIT = 30

# 명사 없이 쓰인 수사, 무엇이 둘인지 제목만 보고 알 수 없다
#
# 제목 끝에 홀로 선 수사만 본다, 뒤에 단위 명사가 오면 무엇을 세는지 드러난다 (`다섯 가지 원칙`)
# 수사 앞 어절이 실질 명사면 이미 밝힌 것이라 통과시킨다 (`필수 항목 일곱`·`린트 툴 둘`)
# 관형형 어미로 끝나거나 의존명사 `것`이면 실질 명사가 없는 것이다 (`검사만 하는 둘`·`담는 것 여섯`)
_NUMERAL = re.compile(r"(?:^|[\s:：·])(둘|셋|넷|다섯|여섯|일곱)\s*$")
_ADNOMINAL = re.compile(r"(것|거|(하|되|있|없|지|보|쓰|오|가|주|받|드|만드|넘|담|나|내)(는|던))$")
# 어절 끝 조사, `항목은 여섯` 처럼 조사가 붙어도 앞말이 명사면 통과시키려고 뗀다
_PARTICLE = re.compile(r"(은|는|이|가|을|를|도|만)$")


# 명사구가 아닌 제목을 찾는다
#
# `나` 로 끝난다고 다 물음이 아니다, `하나`·`증가`·`평가` 가 걸린다
# 그래서 두 경우로 나눈다
# - 어미만 보고 확실한 것: `~는가`·`~을까`·`~합니다`
# - 어미가 애매한 것(`~나`·`~까`)은 의문사가 같이 있을 때만 본다
_QUESTION_ENDING = re.compile(
    r"(는가|은가|던가|을까|나요|습니까|입니까|랍니까|그런가|이런가|어떤가|"
    r"수 있나|수 없나|되나요)\s*$"
)
_AMBIGUOUS_QUESTION = re.compile(r"[가-힣](나|까)\s*$")
# `몇 가지` 는 수량을 밝히는 말이라 물음이 아니다
_INTERROGATIVE = re.compile(r"(무엇|어디|언제|왜|어떻게|누가|누구|얼마|몇(?!\s*가지)|어느)")
_DECLARATIVE = re.compile(
    r"(한다|된다|이다|있다|없다|같다|않다|는다|았다|었다|겠다|니다|해요|어요|이죠|"
    r"진다|린다|간다|온다|난다)\s*$"
)

# 줄표, 값 자체를 뜻하는 홀로 있는 줄표는 뺀다
_EM_DASH = re.compile(r"[—–]")

# 종결어미 뒤 마침표
_PERIOD = re.compile(r"(다|요|죠|까)\.\s*$")

# 한 줄 안에서 문장이 끝나고 다음 문장이 시작되는 곳을 찾는다
#
# 마침표를 쓰지 않는 문서라 종결어미로만 문장 끝을 판별한다
# 합쇼체 `니다` 는 뒤에 공백이 오면 반드시 문장 끝이다
# (`아닙니다만`·`합니다마는` 처럼 이어지는 꼴은 공백 없이 붙는다)
# `~한다` 는 `~한다 해도`·`~한다 치고` 처럼 종결형 뒤에 말이 이어지는 경우가 있어 마침표가 있을 때만 본다
# 괄호로 시작하는 부분은 앞 문장에 붙는 보충 설명이라 새 문장이 아니다
# 굵게 표시(`**`)나 숫자로 시작하는 다음 문장도 새 문장이다
_TWO_SENTENCES = re.compile(r"(니다|[다요죠까]\.)\s+(?=[가-힣A-Za-z0-9*「])")

# 열거 표시, 한 문단에 여럿 몰리면 항목마다 문단을 가져야 한다
# `첫째로`·`둘째는` 처럼 조사가 붙는 꼴도 본다
_ENUMERATION = re.compile(r"(?:^|[\s(（])(첫째|둘째|셋째|넷째|다섯째|여섯째)(?=[,，\s]|로|는|에)")

# 한 문단에 담을 문장 수 상한
# 한국어 기술 문서 6,387문단 가운데 98.2%가 4문장 이하였다
PARAGRAPH_LIMIT = 4

# 따옴표로 감싼 인용, 안쪽은 남의 문장이라 우리 규칙을 적용하지 않는다
_QUOTED = re.compile(r"[\u201c\u201d\"\u300c\u300e][^\u201c\u201d\"\u300d\u300f]*[\u201c\u201d\"\u300d\u300f]")


# MARK: - 결과 자료형
@dataclass(frozen=True)
class Finding:
    """규칙 하나가 검출한 위반 하나"""

    rule: str
    severity: str  # error · warning · suggestion
    message: str
    line: int
    matched: str
    why: str


_OFF_COMMENT = re.compile(r"<!--\s*doccheck:\s*off([^>]*)-->")

# 코드 블록 울타리, 백틱과 물결 둘 다 쓰이고 네 개 이상으로 감싸기도 한다
_FENCE = re.compile(r"^(`{3,}|~{3,})")


@dataclass
class Doc:
    """검사할 문서, 코드 블록과 검사를 끈 줄을 미리 표시해 둔다"""

    path: Path
    lines: list[str] = field(default_factory=list)
    skip_lines: set[int] = field(default_factory=set)
    file_off: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "Doc":
        raw = path.read_text(encoding="utf-8").splitlines()
        skip = set()
        file_off: set[str] = set()
        # 맨 앞 `---` 로 열고 닫는 frontmatter 는 도구가 읽어 가는 설정이라 산문이 아니다
        # 닫는 줄이 없으면 본문에 쓴 가로줄이므로 건너뛰지 않는다
        if raw and raw[0].strip() == "---":
            for i, l in enumerate(raw[1:], 2):
                if l.strip() == "---":
                    skip |= set(range(1, i + 1))
                    break
        # 연 울타리와 같은 문자가 같은 길이 이상일 때만 닫힌 것으로 본다
        fence = ""
        for i, l in enumerate(raw, 1):
            fence_mark = _FENCE.match(l.lstrip())
            if fence:
                skip.add(i)
                if fence_mark and fence_mark.group(1)[0] == fence[0] and len(fence_mark.group(1)) >= len(fence):
                    fence = ""
                continue
            if fence_mark:
                fence = fence_mark.group(1)
                skip.add(i)
                continue
            m = _OFF_COMMENT.search(l)
            if not m:
                continue
            rules = {x.strip() for x in m.group(1).replace(",", " ").split() if x.strip()}
            # 표시만 있고 앞에 글이 없으면 파일 전체를 끄는 선언으로 본다
            if not _OFF_COMMENT.sub("", l).strip():
                file_off |= rules or {"*"}
            else:
                skip.add(i)
        return cls(path=path, lines=raw, skip_lines=skip, file_off=file_off)

    def is_enabled(self, rule: str) -> bool:
        return not ({"*", rule} & self.file_off)

    @staticmethod
    def prose_text(l: str) -> str:
        """인라인 코드와 링크 주소를 뺀 줄을 돌려준다"""
        # 인라인 코드는 고치면 명령이 달라지므로 뺀다
        trimmed = re.sub(r"`[^`]*`", "", l)
        # 링크는 사람이 읽는 표시 텍스트만 남긴다
        # 주소를 남기면 표 칸 길이가 실제로 읽는 길이와 달라진다
        return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", trimmed)

    def prose_lines(self):
        """(줄 번호, 인라인 코드를 뺀 줄) 을 차례로 돌려준다"""
        for i, l in enumerate(self.lines, 1):
            if i in self.skip_lines:
                continue
            yield i, self.prose_text(l)


# MARK: - 검사
def em_dash(doc: Doc) -> list[Finding]:
    """줄표를 쓰지 않는다, 콜론이나 쉼표로 바꾸거나 줄을 나눈다"""
    out = []
    for i, l in doc.prose_lines():
        # 표 칸에 홀로 있는 줄표는 「값 없음」을 뜻하는 표시라 문장부호가 아니다
        # 앞뒤 공백만 보고 빼면 안 된다, 보통의 줄표도 공백 사이에 쓰이기 때문이다
        if l.strip().startswith("|"):
            cells = [c.strip() for c in l.strip().strip("|").split("|")]
            # 홀로 있는 줄표만 뺀 나머지 칸에서 진짜 줄표를 찾는다
            l = " ".join(c for c in cells if c not in {"—", "–"} and not set(c) <= set("-: "))
        for m in _EM_DASH.finditer(l):
            out.append(Finding(
                "em-dash", "error", "줄표가 있습니다", i, m.group(),
                "항목과 설명 사이면 콜론, 괄호 안 덧붙임이면 쉼표, 앞뒤가 문장이면 줄을 나눕니다",
            ))
    return out


def heading_form(doc: Doc) -> list[Finding]:
    """섹션 제목은 명사구로 쓴다, 의문형·서술형을 쓰지 않는다"""
    out = []
    for i, l in doc.prose_lines():
        m = re.match(r"^(#{1,6})\s+(.*)$", l)
        if not m:
            continue
        body = m.group(2).strip()
        # 번호를 뗀다
        body = re.sub(r"^\d+(\.\d+)*\.?\s*", "", body)
        # 콜론 뒤가 결론이면 그 뒤를 본다
        tail = body.split(":")[-1].strip() if ":" in body else body
        tail = tail.rstrip("?!.")
        if not tail:
            continue
        if _QUESTION_ENDING.search(tail):
            kind = "의문형"
        elif _AMBIGUOUS_QUESTION.search(tail) and _INTERROGATIVE.search(tail):
            # `무엇을 적나`·`어디를 뒤지나` 처럼 의문사가 같이 있을 때만 물음으로 본다
            kind = "의문형"
        elif _DECLARATIVE.search(tail):
            kind = "서술형"
        else:
            continue
        out.append(Finding(
            "heading-not-noun", "warning", f"제목이 {kind}입니다", i, body,
            "제목은 그 절이 다루는 대상을 명사로 적고, 제목이 결론을 담고 있으면 그 결론을 본문 첫 줄로 내립니다",
        ))
    return out


def table_cell(doc: Doc, limit: int = CELL_LIMIT) -> list[Finding]:
    """표 칸이 상한(기본 30자)을 넘기면 표 대신 정의 목록으로 바꾼다"""
    out = []
    for i, l in doc.prose_lines():
        if not l.strip().startswith("|"):
            continue
        # 구분선(|---|---|)은 건너뛴다
        if re.fullmatch(r"\s*\|[\s:|-]+\|?\s*", l):
            continue
        for cell in l.strip().strip("|").split("|"):
            cell_text = cell.strip()
            if len(cell_text) > limit:
                out.append(Finding(
                    "table-cell-long", "warning",
                    f"표 칸이 {len(cell_text)}자입니다 (상한 {limit})", i,
                    cell_text if len(cell_text) <= 46 else cell_text[:46] + "…",
                    "칸이 한 줄 구를 넘기면 표가 옆으로 넓어지므로, 칸이 문장인지 확인하고 문장이면 정의 목록(굵은 항목 + 설명)으로 바꿉니다",
                ))
    return out


def trailing_period(doc: Doc) -> list[Finding]:
    """종결어미 뒤에 마침표를 찍지 않는다"""
    out = []
    for i, l in doc.prose_lines():
        body = l.strip()
        if not body or body.startswith(("#", "|")):
            continue
        # 인용 블록도 사람이 읽는 산문이므로 표시만 떼고 본다
        body = re.sub(r"^>\s*", "", body).strip()
        m = _PERIOD.search(body)
        if m:
            out.append(Finding(
                "trailing-period", "suggestion", "줄 끝에 마침표가 있습니다", i, m.group(),
                "종결어미가 문장의 끝을 드러내므로, 줄 끝의 마침표를 지웁니다",
            ))
    return out


def _heading_lines(doc: Doc):
    """제목 줄에서 번호와 콜론 뒤 결론을 뗀 앞부분을 돌려준다"""
    import re as _re
    for i, l in doc.prose_lines():
        m = _re.match(r"^(#{1,6})\s+(.*)$", l)
        if not m:
            continue
        body = _re.sub(r"^\d+(\.\d+)*\.?\s*", "", m.group(2).strip())
        head = body.split(":")[0].strip() if ":" in body else body
        if head:
            yield i, body, head


def _has_no_noun(before: str) -> bool:
    """수사 앞에 무엇을 세는지 밝히는 명사가 없는지 확인한다"""
    words = before.strip().split()
    if not words:
        return True
    last = words[-1]
    if _ADNOMINAL.search(last):
        return True
    # 조사를 뗀 뒤에도 관형형이면 명사가 없는 것이다
    return bool(_ADNOMINAL.search(_PARTICLE.sub("", last)))


def bare_numeral(doc: Doc) -> list[Finding]:
    """제목에 명사 없이 수사만 있으면 무엇을 세는지 알 수 없다"""
    out = []
    for i, body, head in _heading_lines(doc):
        m = _NUMERAL.search(head)
        if m and _has_no_noun(head[:m.start(1)]):
            out.append(Finding(
                "heading-bare-numeral", "warning",
                f"제목의 「{m.group(1)}」에 명사가 없습니다", i, body,
                f"무엇이 {m.group(1)}인지 밝힙니다 (「담는 것 {m.group(1)}」이 아니라 「필수 항목 {m.group(1)}」)",
            ))
    return out


def multi_sentence(doc: Doc) -> list[Finding]:
    """한 줄에 문장이 둘 이상이면 줄을 나눈다"""
    out = []
    for i, l in doc.prose_lines():
        stripped = l.strip()
        # 표 줄은 칸마다 문장이 하나씩이라 대상이 아니다, 칸 길이는 따로 본다
        if stripped.startswith("|") or stripped.startswith("#"):
            continue
        # 인용·목록 표시를 떼고 본문만 본다
        body = re.sub(r"^[>\-*+]\s*", "", stripped)
        body = re.sub(r"^\d+[.)]\s*", "", body)
        # 따옴표 안은 인용한 원문이라 원래 모양 그대로 둔다
        body = _QUOTED.sub("", body)
        m = _TWO_SENTENCES.search(body)
        if not m:
            continue
        before = body[:m.end()].strip()
        out.append(Finding(
            "line-multi-sentence", "warning",
            "한 줄에 문장이 둘 이상입니다", i, before[-40:],
            "한 문장으로 합칠 수 있으면 합치고, 주제가 다르면 줄을 바꿉니다",
        ))
    return out


def _blocks(doc: Doc, kind: str = "prose") -> list[list[tuple[int, str]]]:
    """빈 줄로 나뉜 덩어리를 돌려준다

    `prose` 면 산문 문단만 돌려준다
    `all` 이면 목록 항목과 인용 블록도 함께 돌려주고, 목록 항목은 뒤에 이어지는 들여쓴 줄까지 한 덩어리로 묶는다
    """
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    current_kind = ""

    def flush() -> None:
        nonlocal current, current_kind
        if current and (kind == "all" or current_kind == "prose"):
            blocks.append(current)
        current, current_kind = [], ""

    # 원래 줄로 판단한다, 인라인 코드를 먼저 빼면 코드로 시작하는 줄이 들여쓴 줄로 보인다
    for i, raw in enumerate(doc.lines, 1):
        stripped = raw.strip()
        body = doc.prose_text(raw).strip()
        # 코드 블록과 frontmatter 는 화면에서 앞뒤 줄을 갈라 놓으므로 덩어리 경계로 본다
        if i in doc.skip_lines or not stripped or stripped.startswith(("|", "#")):
            flush()
            continue
        if stripped.startswith(">"):
            if current_kind != "quote":
                flush()
                current_kind = "quote"
            current.append((i, body))
            continue
        # `- ` 는 목록이지만 `**굵게**` 는 산문이다, 표시 뒤 공백으로 구분한다
        if re.match(r"^([-*+]|\d+[.)])\s", stripped):
            flush()
            current_kind = "list"
            current.append((i, body))
            continue
        # 들여쓴 줄은 앞 목록 항목에 이어지는 줄이다
        if raw.startswith((" ", "\t")):
            if current_kind == "list":
                current.append((i, body))
            else:
                flush()
            continue
        if current_kind != "prose":
            flush()
            current_kind = "prose"
        current.append((i, body))
    flush()
    return blocks


def paragraph_cram(doc: Doc) -> list[Finding]:
    """한 문단이 상한(4줄)을 넘으면 주제마다 문단을 나눈다"""
    out = []
    for block in _blocks(doc):
        if len(block) <= PARAGRAPH_LIMIT:
            continue
        i, first_line = block[0]
        out.append(Finding(
            "paragraph-cram", "warning",
            f"한 문단이 {len(block)}줄입니다 (상한 {PARAGRAPH_LIMIT})", i, first_line[:40],
            "문단에는 주제 하나만 담으므로, 주제가 바뀔 때 빈 줄을 넣어 나눕니다",
        ))
    return out


# 줄 끝 공백 두 칸이나 백슬래시가 있어야 화면에서도 줄이 바뀐다
_BREAK_MARK = re.compile(r"(  +|\\)$")


def soft_break(doc: Doc) -> list[Finding]:
    """문단 안에서 줄을 바꿨으면 줄 끝에 공백 두 칸을 둔다"""
    out = []
    # 목록 항목에 이어지는 줄과 인용 블록도 화면에서는 앞줄에 붙으므로 함께 본다
    for block in _blocks(doc, "all"):
        # 마지막 줄은 뒤에 이어질 줄이 없으므로 표시가 필요 없다
        for i, stripped in block[:-1]:
            if _BREAK_MARK.search(doc.lines[i - 1].rstrip("\n")):
                continue
            out.append(Finding(
                "soft-break", "warning",
                "줄 끝에 줄바꿈 표시가 없어 화면에서는 다음 줄이 이어 붙습니다", i, stripped[:40],
                "줄 끝에 공백 두 칸을 두면 화면에서도 줄이 바뀝니다",
            ))
    return out


def mechanical_parallel(doc: Doc) -> list[Finding]:
    """`첫째`·`둘째` 가 한 문단에 둘 이상 있으면 항목마다 문단을 나눈다"""
    out = []
    for block in _blocks(doc, "all"):
        found = []
        for i, l in block:
            for m in _ENUMERATION.finditer(l):
                found.append((i, m.group(1)))
        if len(found) < 2:
            continue
        i, _ = found[0]
        marks = "·".join(x[1] for x in found)
        out.append(Finding(
            "mechanical-parallel", "warning",
            f"열거 표시가 한 문단에 몰려 있습니다: {marks}", i, marks,
            "`첫째`·`둘째` 자체는 규칙 위반이 아니지만 한 문단에 여러 주제가 들어가므로, 항목마다 문단을 나누거나 목록으로 바꿉니다",
        ))
    return out


CHECKS = {
    "em-dash": em_dash,
    "heading-not-noun": heading_form,
    "heading-bare-numeral": bare_numeral,
    "line-multi-sentence": multi_sentence,
    "soft-break": soft_break,
    "paragraph-cram": paragraph_cram,
    "mechanical-parallel": mechanical_parallel,
    "table-cell-long": table_cell,
    "trailing-period": trailing_period,
}

_SEVERITY_ORDER = {"error": 0, "warning": 1, "suggestion": 2}


# MARK: - 실행
def check(
    path: Path,
    disabled: set[str] | None = None,
    limit: int = CELL_LIMIT,
) -> list[Finding]:
    """한 문서를 검사한다, 훅에서도 부르므로 인자에 기본값을 둔다"""
    disabled = disabled or set()
    doc = Doc.load(path)
    out: list[Finding] = []
    for name, fn in CHECKS.items():
        if name in disabled or not doc.is_enabled(name):
            continue
        if name == "table-cell-long":
            out += fn(doc, limit)
        else:
            out += fn(doc)
    out.sort(key=lambda f: (f.line, _SEVERITY_ORDER[f.severity], f.rule))
    return out


def _target_error(path: Path) -> str | None:
    """검사할 수 없는 파일이면 그 이유를 돌려준다"""
    if not path.exists():
        return "파일이 없습니다"
    # 규칙이 한국어 산문을 전제하므로 마크다운만 본다
    # 코드 파일을 넣으면 주석과 정규식 문자열이 모두 검출된다
    if path.suffix.lower() not in {".md", ".markdown"}:
        return "마크다운이 아닙니다, .md 와 .markdown 만 검사합니다"
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "UTF-8 로 읽을 수 없습니다"
    except OSError as e:
        return f"읽을 수 없습니다: {e.strerror}"
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="doccheck",
        description="마크다운 문서에서 형태로 판별할 수 있는 규칙 위반을 찾는다",
    )
    p.add_argument("paths", nargs="*", type=Path, help="검사할 .md·.markdown 파일")
    p.add_argument("--disable", default="", help="끌 규칙 이름, 쉼표로 구분")
    p.add_argument("--max-cell", type=int, default=CELL_LIMIT, help=f"표 칸 상한 (기본 {CELL_LIMIT})")
    p.add_argument("--format", default="text", choices=("text", "json"))
    p.add_argument("--fail-on", default="error", choices=("error", "warning", "suggestion", "never"))
    p.add_argument("--list-rules", action="store_true", help="규칙 목록을 출력하고 끝낸다")
    p.add_argument("--fix-breaks", action="store_true",
                   help="soft-break 를 고친다, 줄 끝에 공백 두 칸을 붙인다")
    a = p.parse_args(argv)

    if a.list_rules:
        for name, fn in CHECKS.items():
            print(f"{name:<20} {(fn.__doc__ or '').strip().splitlines()[0]}")
        return 0

    disabled = {x.strip() for x in a.disable.split(",") if x.strip()}
    unknown = disabled - set(CHECKS)
    if unknown:
        print(f"모르는 규칙 이름입니다: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    if a.fix_breaks:
        if not a.paths:
            p.error("고칠 파일을 지정하십시오")
        fixed = 0
        for path in a.paths:
            err = _target_error(path)
            if err:
                print(f"{path}: {err}", file=sys.stderr)
                return 2
            doc = Doc.load(path)
            # 검사에서 끈 파일은 고치지도 않는다
            if "soft-break" in disabled or not doc.is_enabled("soft-break"):
                continue
            targets = {f.line for f in soft_break(doc)}
            if not targets:
                continue
            # 줄 끝 표시를 그대로 둔다, 통째로 바꾸면 고치지 않은 줄까지 달라진다
            with path.open(encoding="utf-8", newline="") as f:
                lines = f.read().splitlines(keepends=True)
            for n in targets:
                body, last = lines[n - 1], ""
                while body.endswith(("\n", "\r")):
                    last = body[-1] + last
                    body = body[:-1]
                lines[n - 1] = body.rstrip() + "  " + last
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write("".join(lines))
            print(f"{path}: {len(targets)}줄")
            fixed += len(targets)
        print(f"모두 {fixed}줄")
        return 0

    if not a.paths:
        p.error("검사할 파일을 지정하십시오")

    results: list[tuple[Path, list[Finding]]] = []
    for path in a.paths:
        err = _target_error(path)
        if err:
            print(f"{path}: {err}", file=sys.stderr)
            return 2
        results.append((path, check(path, disabled, a.max_cell)))

    if a.format == "json":
        print(json.dumps(
            [{"path": str(p), **f.__dict__} for p, fs in results for f in fs],
            ensure_ascii=False, indent=2,
        ))
    else:
        for path, fs in results:
            for f in fs:
                mark = {"error": "E", "warning": "W", "suggestion": "S"}[f.severity]
                print(f"{path}:{f.line} {mark} {f.rule}: {f.message}")
                print(f"    {f.matched}")
                print(f"    -> {f.why}")
        total = sum(len(fs) for _, fs in results)
        print(f"\n발견 {total}건", file=sys.stderr)

    if a.fail_on == "never":
        return 0
    floor = _SEVERITY_ORDER[a.fail_on]
    if any(_SEVERITY_ORDER[f.severity] <= floor for _, fs in results for f in fs):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
