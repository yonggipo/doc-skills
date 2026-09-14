#!/usr/bin/env python3
"""검사 스크립트와 훅이 규칙대로 동작하는지 확인한다

의존성이 없다, 레포 최상위에서 `python3 -m unittest discover tests` 로 실행한다
한 번 고친 결함은 회귀를 막으려고 사례로 남긴다
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "hooks"))

import doccheck  # noqa: E402
import posttool  # noqa: E402
import session  # noqa: E402


class Base(unittest.TestCase):
    """임시 폴더에 문서를 쓰고 검사하는 공통 도구"""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, text: str, name: str = "doc.md") -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def rules(self, text: str, **kwargs) -> list[str]:
        """검출된 규칙 이름을 줄 번호 순서로 돌려준다"""
        return [f.rule for f in doccheck.check(self.write(text), **kwargs)]

    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        """명령줄 실행 결과와 출력을 돌려준다"""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = doccheck.main(argv)
        return code, out.getvalue(), err.getvalue()


# MARK: - 줄표
class EmDashTest(Base):
    def test_산문의_줄표를_검출한다(self) -> None:
        self.assertEqual(self.rules("앞 — 뒤"), ["em-dash"])

    def test_표_칸에_홀로_있는_줄표는_값이므로_통과한다(self) -> None:
        self.assertEqual(self.rules("| 홈페이지 | — |\n|---|---|\n| 값 | — |"), [])

    def test_같은_표_줄에_섞여_있으면_진짜_줄표만_센다(self) -> None:
        self.assertEqual(self.rules("| — | 앞 — 뒤 |"), ["em-dash"])

    def test_인라인_코드_안의_줄표는_검사하지_않는다(self) -> None:
        self.assertEqual(self.rules("`앞 — 뒤` 를 쓴다"), [])


# MARK: - 제목
class HeadingTest(Base):
    def test_의문사가_있는_의문형_제목을_검출한다(self) -> None:
        self.assertEqual(self.rules("## 무엇을 적나"), ["heading-not-noun"])

    def test_서술형_제목을_검출한다(self) -> None:
        self.assertEqual(self.rules("## 줄표를 쓰지 않는다"), ["heading-not-noun"])

    def test_명사구_제목은_통과한다(self) -> None:
        self.assertEqual(self.rules("## 캐시 유지 시간"), [])

    def test_몇_가지는_의문사로_보지_않는다(self) -> None:
        self.assertEqual(self.rules("## 몇 가지 선택지 가운데 하나"), [])

    def test_제목_끝의_홀로_선_수사를_검출한다(self) -> None:
        self.assertEqual(self.rules("## 담는 것 여섯"), ["heading-bare-numeral"])

    def test_수사_뒤에_단위_명사가_오면_통과한다(self) -> None:
        self.assertEqual(self.rules("## 다섯 가지 원칙"), [])

    def test_조사가_붙은_명사_뒤의_수사는_통과한다(self) -> None:
        self.assertEqual(self.rules("## 필수 항목은 여섯"), [])


# MARK: - 표 칸
class TableCellTest(Base):
    def test_상한을_넘긴_칸을_검출한다(self) -> None:
        긴칸 = "가" * 31
        self.assertEqual(self.rules(f"| 항목 | {긴칸} |"), ["table-cell-long"])

    def test_상한을_넘겨_주면_통과한다(self) -> None:
        긴칸 = "가" * 31
        self.assertEqual(self.rules(f"| 항목 | {긴칸} |", limit=40), [])

    def test_인라인_코드는_글자_수에서_뺀다(self) -> None:
        self.assertEqual(self.rules(f"| 항목 | `{'a' * 40}` |"), [])


# MARK: - 문단과 줄바꿈
class ParagraphTest(Base):
    def test_네_줄을_넘는_문단을_검출한다(self) -> None:
        문단 = "\n".join(f"{n}째 줄입니다  " for n in "일이삼사오")
        self.assertIn("paragraph-cram", self.rules(문단))

    def test_네_줄_문단은_통과한다(self) -> None:
        문단 = "\n".join(f"{n}째 줄입니다  " for n in "일이삼사")
        self.assertEqual(self.rules(문단), [])

    def test_코드_블록이_앞뒤_문단을_가른다(self) -> None:
        self.assertEqual(self.rules("설명입니다\n```\ncode\n```\n다음 설명입니다"), [])


class SoftBreakTest(Base):
    def test_문단_안_줄바꿈에_공백이_없으면_검출한다(self) -> None:
        self.assertEqual(self.rules("첫 줄입니다\n둘째 줄입니다"), ["soft-break"])

    def test_공백_두_칸이_있으면_통과한다(self) -> None:
        self.assertEqual(self.rules("첫 줄입니다  \n둘째 줄입니다"), [])

    def test_인라인_코드로_시작하는_줄도_검사한다(self) -> None:
        self.assertEqual(self.rules("`session.py` 가 넣습니다\n다음 줄입니다"), ["soft-break"])

    def test_목록_항목에_이어지는_줄도_검사한다(self) -> None:
        self.assertEqual(self.rules("- 첫 줄입니다\n  이어지는 줄입니다"), ["soft-break"])

    def test_인용_블록_안의_줄도_검사한다(self) -> None:
        self.assertEqual(self.rules("> 첫 줄입니다\n> 둘째 줄입니다"), ["soft-break"])

    def test_이어지는_목록_항목은_검사하지_않는다(self) -> None:
        self.assertEqual(self.rules("- 첫 항목입니다\n- 둘째 항목입니다"), [])


# MARK: - 문장
class SentenceTest(Base):
    def test_한_줄에_두_문장을_검출한다(self) -> None:
        self.assertIn("line-multi-sentence", self.rules("설치한다. 다음을 본다."))

    def test_다음_문장이_굵게_표시로_시작해도_검출한다(self) -> None:
        self.assertIn("line-multi-sentence", self.rules("설치한다. **주의** 사항이다"))

    def test_다음_문장이_숫자로_시작해도_검출한다(self) -> None:
        self.assertIn("line-multi-sentence", self.rules("설치합니다 3번을 봅니다"))

    def test_종결어미_뒤_마침표를_검출한다(self) -> None:
        self.assertEqual(self.rules("캐시를 껐다."), ["trailing-period"])

    def test_인용_블록_안의_마침표도_검출한다(self) -> None:
        self.assertEqual(self.rules("> 캐시를 껐다."), ["trailing-period"])


class EnumerationTest(Base):
    def test_한_문단에_몰린_열거_표시를_검출한다(self) -> None:
        self.assertIn("mechanical-parallel", self.rules("첫째, 읽는다 둘째, 저장한다"))

    def test_조사가_붙은_열거_표시도_검출한다(self) -> None:
        self.assertIn("mechanical-parallel", self.rules("첫째로 읽는다 둘째로 저장한다"))

    def test_항목마다_나누면_통과한다(self) -> None:
        self.assertEqual(self.rules("- 첫째, 읽는다\n- 둘째, 저장한다"), [])


# MARK: - 검사에서 빼는 자리
class SkipTest(Base):
    def test_코드_블록_안은_검사하지_않는다(self) -> None:
        self.assertEqual(self.rules("```\n앞 — 뒤\n```"), [])

    def test_물결_울타리_블록도_검사하지_않는다(self) -> None:
        self.assertEqual(self.rules("~~~\n앞 — 뒤\n~~~"), [])

    def test_백틱_네_개_블록이_끝난_뒤를_검사한다(self) -> None:
        self.assertEqual(self.rules("````\n```\n안쪽\n```\n````\n\n앞 — 뒤"), ["em-dash"])

    def test_닫은_frontmatter_는_검사하지_않는다(self) -> None:
        self.assertEqual(self.rules("---\ntitle: 앞 — 뒤\n---\n\n본문입니다"), [])

    def test_닫지_않은_가로줄은_본문으로_본다(self) -> None:
        self.assertEqual(self.rules("---\n앞 — 뒤"), ["em-dash"])

    def test_줄_끝_주석은_그_줄을_건너뛴다(self) -> None:
        self.assertEqual(self.rules("앞 — 뒤 <!-- doccheck: off -->"), [])

    def test_주석만_있는_줄은_파일_전체를_끈다(self) -> None:
        self.assertEqual(self.rules("<!-- doccheck: off -->\n앞 — 뒤"), [])

    def test_규칙_이름을_적으면_그_규칙만_끈다(self) -> None:
        self.assertEqual(self.rules("<!-- doccheck: off em-dash -->\n앞 — 뒤  \n캐시를 껐다."), ["trailing-period"])

    def test_인자로_넘긴_규칙도_끈다(self) -> None:
        self.assertEqual(self.rules("앞 — 뒤", disabled={"em-dash"}), [])


# MARK: - 명령줄
class CommandLineTest(Base):
    def test_위반이_없으면_종료_코드가_0이다(self) -> None:
        path = self.write("본문입니다")
        self.assertEqual(self.run_main([str(path)])[0], 0)

    def test_error_가_있으면_종료_코드가_1이다(self) -> None:
        path = self.write("앞 — 뒤")
        self.assertEqual(self.run_main([str(path)])[0], 1)

    def test_기본값에서는_warning_만으로_1을_내지_않는다(self) -> None:
        path = self.write("## 무엇을 적나")
        self.assertEqual(self.run_main([str(path)])[0], 0)

    def test_fail_on_으로_기준을_낮춘다(self) -> None:
        path = self.write("## 무엇을 적나")
        self.assertEqual(self.run_main([str(path), "--fail-on", "warning"])[0], 1)

    def test_never_는_위반이_있어도_0이다(self) -> None:
        path = self.write("앞 — 뒤")
        self.assertEqual(self.run_main([str(path), "--fail-on", "never"])[0], 0)

    def test_없는_파일은_종료_코드_2를_낸다(self) -> None:
        code, _, err = self.run_main([str(self.dir / "없다.md")])
        self.assertEqual(code, 2)
        self.assertIn("파일이 없습니다", err)

    def test_마크다운이_아니면_종료_코드_2를_낸다(self) -> None:
        path = self.dir / "code.py"
        path.write_text("print()", encoding="utf-8")
        self.assertEqual(self.run_main([str(path)])[0], 2)

    def test_UTF8_이_아니면_종료_코드_2를_낸다(self) -> None:
        path = self.dir / "doc.md"
        path.write_bytes("한글 문서입니다".encode("euc-kr"))
        code, _, err = self.run_main([str(path)])
        self.assertEqual(code, 2)
        self.assertIn("UTF-8", err)

    def test_모르는_규칙_이름은_종료_코드_2를_낸다(self) -> None:
        path = self.write("본문입니다")
        code, _, err = self.run_main([str(path), "--disable", "em_dash"])
        self.assertEqual(code, 2)
        self.assertIn("모르는 규칙", err)

    def test_json_형식으로_출력한다(self) -> None:
        path = self.write("앞 — 뒤")
        _, out, _ = self.run_main([str(path), "--format", "json", "--fail-on", "never"])
        self.assertEqual(json.loads(out)[0]["rule"], "em-dash")

    def test_규칙_목록을_출력한다(self) -> None:
        _, out, _ = self.run_main(["--list-rules"])
        self.assertEqual(len(out.strip().splitlines()), len(doccheck.CHECKS))


class FixBreaksTest(Base):
    def test_줄_끝에_공백_두_칸을_붙인다(self) -> None:
        path = self.write("첫 줄입니다\n둘째 줄입니다\n")
        self.run_main(["--fix-breaks", str(path)])
        self.assertEqual(path.read_text(encoding="utf-8"), "첫 줄입니다  \n둘째 줄입니다\n")

    def test_줄_끝_표시를_그대로_둔다(self) -> None:
        path = self.dir / "crlf.md"
        path.write_bytes("첫 줄입니다\r\n둘째 줄입니다\r\n".encode("utf-8"))
        self.run_main(["--fix-breaks", str(path)])
        self.assertEqual(path.read_bytes(), "첫 줄입니다  \r\n둘째 줄입니다\r\n".encode("utf-8"))

    def test_검사를_끈_파일은_고치지_않는다(self) -> None:
        원본 = "<!-- doccheck: off -->\n첫 줄입니다\n둘째 줄입니다\n"
        path = self.write(원본)
        self.run_main(["--fix-breaks", str(path)])
        self.assertEqual(path.read_text(encoding="utf-8"), 원본)

    def test_없는_파일은_종료_코드_2를_낸다(self) -> None:
        self.assertEqual(self.run_main(["--fix-breaks", str(self.dir / "없다.md")])[0], 2)


# MARK: - 훅
class HookTest(Base):
    def test_마크다운이_아니면_대상에서_뺀다(self) -> None:
        self.assertIsNone(posttool.target_path({"tool_input": {"file_path": str(ROOT / "scripts/doccheck.py")}}))

    def test_없는_파일도_대상에서_뺀다(self) -> None:
        self.assertIsNone(posttool.target_path({"tool_input": {"file_path": str(self.dir / "없다.md")}}))

    def test_알림에_실행할_수_있는_절대_경로를_넣는다(self) -> None:
        path = self.write("앞 — 뒤", name="공백 있는.md")
        문구 = posttool.build_message(path, doccheck.check(path))
        self.assertIn(str(ROOT / "scripts" / "doccheck.py"), 문구)
        self.assertIn(f"'{path}'", 문구)

    def test_제목_안내는_제목_규칙에_걸릴_때만_붙인다(self) -> None:
        줄표 = self.write("앞 — 뒤", name="dash.md")
        제목 = self.write("## 무엇을 적나", name="heading.md")
        self.assertNotIn("명사구", posttool.build_message(줄표, doccheck.check(줄표)))
        self.assertIn("명사구", posttool.build_message(제목, doccheck.check(제목)))

    def test_세션_훅이_write_폴더의_지침을_모두_넣는다(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            session.main()
        지침 = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
        파일들 = sorted((ROOT / "prompts" / "write").glob("*.md"))
        self.assertTrue(파일들)
        for path in 파일들:
            self.assertIn(path.read_text(encoding="utf-8").strip().splitlines()[0], 지침)


# MARK: - 이 레포의 문서
class RepoDocsTest(Base):
    def test_레포_문서가_규칙을_지킨다(self) -> None:
        문서들 = [ROOT / "README.md", ROOT / "skills/doc-check/SKILL.md"]
        문서들 += sorted((ROOT / "prompts").rglob("*.md"))
        for path in 문서들:
            with self.subTest(문서=path.name):
                self.assertEqual(doccheck.check(path), [])


if __name__ == "__main__":
    unittest.main()
