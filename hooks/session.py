#!/usr/bin/env python3
"""세션이 열릴 때 문서 지침을 한 번 넣는다

프롬프트로 시킨 것은 대개 지켜지지만 항상은 아니다
그래서 이 지침은 위반을 예방하는 용도이고, 지키지 않은 부분은 PostToolUse 훅이 검사해 알린다

글을 쓰는 순간에 필요한 `prompts/write/` 만 넣는다
다 쓴 뒤에 보는 `prompts/review/` 는 doc-check 스킬이 부를 때 읽는다
"""

import json
import sys
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts" / "write"


def main() -> int:
    try:
        # 파일 이름의 숫자 접두어가 넣는 순서를 정한다
        files = sorted(PROMPT_DIR.glob("*.md"))
        guidance = "\n\n".join(p.read_text(encoding="utf-8").strip() for p in files)
    except Exception:
        return 0
    if not guidance:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": guidance,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
