#!/usr/bin/env python3
"""마크다운을 쓰거나 고친 직후에 문서화 규칙 위반을 검사한다

훅으로 실행되므로 두 가지를 지킨다
- 무엇이 잘못돼도 조용히 끝낸다, 문서 검사가 작업을 막으면 안 된다
- 고치라고 시키지 않는다, 무엇이 걸렸는지만 알린다
"""

# 타입 표기를 실행 중에 계산하지 않게 해 macOS 기본 파이썬 3.9 에서도 불러올 수 있게 한다
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "doccheck.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))

# 훅 한 번에 알릴 최대 건수, 넘으면 나머지는 건수만 알린다
MAX_REPORTED = 12


# MARK: - 검사 대상 가리기
def target_path(payload: dict) -> Path | None:
    """이번에 손댄 파일이 마크다운이면 그 경로를 돌려준다"""
    tool_input = payload.get("tool_input") or {}
    raw_path = tool_input.get("file_path")
    if not raw_path:
        return None
    p = Path(raw_path)
    if p.suffix.lower() not in {".md", ".markdown"}:
        return None
    return p if p.exists() else None


# MARK: - 알림 문구
def build_message(path: Path, findings: list) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.rule] = counts.get(f.rule, 0) + 1
    summary = ", ".join(f"{r} {n}건" for r, n in counts.items())

    lines = [f"방금 쓰거나 고친 {path.name}에서 문서화 규칙 위반을 찾았습니다: {summary}", ""]
    for f in findings[:MAX_REPORTED]:
        lines.append(f"  {path.name}:{f.line} {f.rule}  {f.matched[:60]}")
    remaining = len(findings) - MAX_REPORTED
    if remaining > 0:
        lines.append(f"  (그 밖에 {remaining}건)")
    lines += ["", "고치기 전에 사용자에게 무엇을 고칠지 묻습니다"]
    # 제목 안내는 제목 규칙에 걸렸을 때만 붙인다
    if any(f.rule.startswith("heading-") for f in findings):
        lines.append("제목을 명사구로 줄이면 결론이 사라지는 경우가 있으므로, 사라지는 결론은 본문 첫 줄로 옮깁니다")
    # 환경변수는 이 문구 안에서 값이 채워지지 않으므로 절대 경로를 넣는다
    lines.append(f"전부 보려면: python3 {shlex.quote(str(SCRIPT_PATH))} {shlex.quote(str(path))}")
    return "\n".join(lines)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    path = target_path(payload)
    if path is None:
        return 0

    try:
        from doccheck import check
        findings = check(path)
    except Exception:
        # 검사가 깨져도 사용자 작업은 계속돼야 한다
        return 0

    if not findings:
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": build_message(path, findings),
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
