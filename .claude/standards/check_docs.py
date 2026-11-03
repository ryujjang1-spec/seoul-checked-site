#!/usr/bin/env python3
"""Claude 스킬·문서 작성 규칙 검사기 (.claude/standards/SKILL_RULES.md 기준).

사용법:
    python3 .claude/standards/check_docs.py          # 검사만
    python3 .claude/standards/check_docs.py --fix    # 목차 자동 생성·갱신 후 검사
    python3 .claude/standards/check_docs.py PATH     # 다른 폴더 검사

필요 환경: Python 3.8+ (표준 라이브러리만 사용, 설치할 패키지 없음)
종료 코드: 0 = 통과, 1 = 오류 있음
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOC_LINE_LIMIT = 100      # 이 줄 수를 넘는 .md 문서는 목차 필수
SKILL_LINE_LIMIT = 500    # SKILL.md 최대 줄 수
TOC_SEARCH_LINES = 60     # 목차를 찾는 범위(문서 앞부분)
TOC_START = "<!-- TOC -->"
TOC_END = "<!-- /TOC -->"
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist",
    "build", ".next", ".turbo", ".cache", "coverage", "site-packages",
}
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LINK_RE = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def iter_md(root: Path):
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            yield path


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def headings(lines: list[str]) -> list[tuple[int, str]]:
    """코드 블록과 기존 목차 안을 제외한 제목 목록."""
    out, fence, in_toc = [], None, False
    for line in lines:
        s = line.strip()
        if s == TOC_START:
            in_toc = True
            continue
        if s == TOC_END:
            in_toc = False
            continue
        if in_toc:
            continue
        m = re.match(r"^(`{3,}|~{3,})", s)
        if m:
            mark = m.group(1)[0]
            if fence is None:
                fence = mark
            elif fence == mark:
                fence = None
            continue
        if fence:
            continue
        h = HEADING_RE.match(line)
        if h:
            out.append((len(h.group(1)), h.group(2).strip()))
    return out


def slugify(text: str, seen: dict[str, int]) -> str:
    """GitHub 방식 앵커(한글 유지)."""
    s = re.sub(r"[`*_~\[\]()<>]", "", text).strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    s = s.replace(" ", "-")
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if n == 0 else f"{s}-{n}"


def build_toc(lines: list[str]) -> list[str]:
    hs = headings(lines)
    level = 2 if sum(1 for lv, _ in hs if lv == 2) >= 2 else 3
    seen: dict[str, int] = {}
    items = []
    for lv, text in hs:
        anchor = slugify(text, seen)
        if lv == level or (level == 3 and lv == 2):
            indent = "  " if (level == 3 and lv == 3) else ""
            label = re.sub(r"[`*]", "", text)
            items.append(f"{indent}- [{label}](#{anchor})")
    return [TOC_START, "**목차**", "", *items, TOC_END]


def toc_block(lines: list[str]) -> tuple[int, int] | None:
    start = end = None
    for i, line in enumerate(lines[: TOC_SEARCH_LINES + 200]):
        if line.strip() == TOC_START and start is None:
            start = i
        elif line.strip() == TOC_END and start is not None:
            end = i
            break
    if start is None or end is None or start > TOC_SEARCH_LINES:
        return None
    return start, end


def apply_toc(path: Path) -> bool:
    lines = read_lines(path)
    new_toc = build_toc(lines)
    block = toc_block(lines)
    if block:
        s, e = block
        if lines[s : e + 1] == new_toc:
            return False
        lines[s : e + 1] = new_toc
    else:
        idx = 0
        if lines and lines[0].strip() == "---":           # frontmatter 건너뛰기
            for j in range(1, len(lines)):
                if lines[j].strip() == "---":
                    idx = j + 1
                    break
        for j in range(idx, min(len(lines), idx + 10)):    # 첫 H1 바로 아래
            if lines[j].startswith("# "):
                idx = j + 1
                break
        tail = [] if idx < len(lines) and lines[idx].strip() == "" else [""]
        lines[idx:idx] = ["", *new_toc, *tail]
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return True


def check_toc(path: Path, lines: list[str], errors: list[str]) -> None:
    if len(lines) <= TOC_LINE_LIMIT:
        return
    block = toc_block(lines)
    if not block:
        errors.append(f"{path}: {len(lines)}줄 — 앞부분에 목차가 없음 (--fix로 생성)")
    elif lines[block[0] : block[1] + 1] != build_toc(lines):
        errors.append(f"{path}: 목차가 현재 제목과 다름 (--fix로 갱신)")


def frontmatter(lines: list[str]) -> tuple[dict[str, str], int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    data: dict[str, str] = {}
    for j in range(1, len(lines)):
        if lines[j].strip() == "---":
            return data, j + 1
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", lines[j])
        if m:
            data[m.group(1)] = m.group(2).strip().strip("'\"")
    return {}, 0


def local_md_links(path: Path, lines: list[str]) -> list[Path]:
    out = []
    for target in LINK_RE.findall("\n".join(lines)):
        if "://" in target:
            continue
        p = (path.parent / target).resolve()
        if p.exists():
            out.append(p)
    return out


def check_skill(abspath: Path, path: Path, lines: list[str], errors: list[str], warns: list[str]) -> None:
    if len(lines) > SKILL_LINE_LIMIT:
        errors.append(f"{path}: {len(lines)}줄 — SKILL.md는 {SKILL_LINE_LIMIT}줄 이하 (reference/로 분리)")
    fm, body = frontmatter(lines)
    if not fm:
        errors.append(f"{path}: frontmatter(--- name/description ---)가 없음")
    else:
        name, desc = fm.get("name", ""), fm.get("description", "")
        if not NAME_RE.match(name) or len(name) > 64:
            errors.append(f"{path}: name은 영문 소문자·숫자·하이픈, 64자 이하")
        if not desc:
            errors.append(f"{path}: description이 비어 있음 (무엇을 + 언제 쓰는지)")
        elif len(desc) > 1024:
            errors.append(f"{path}: description {len(desc)}자 — 1024자 이하")
    head = "\n".join(lines[body : body + 15])
    if "대상 모델" not in head and "Target model" not in head:
        errors.append(f"{path}: 본문 첫머리에 '> 대상 모델: ...' 표기가 없음")
    text = "\n".join(lines)
    if re.search(r"\b(pip|npm|pnpm|yarn|brew|apt)\b|import ", text) and not re.search(
        r"구동 환경|설치|Requirements|Setup", text
    ):
        warns.append(f"{path}: 패키지를 쓰는데 '구동 환경/설치' 섹션이 없음")
    for ref in local_md_links(abspath, lines):
        nested = [p for p in local_md_links(ref, read_lines(ref)) if p != abspath.resolve()]
        if nested:
            errors.append(f"{path}: 참조 파일 {ref.name}이(가) 다른 문서를 다시 참조함 (1단계만 허용)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--fix", action="store_true", help="목차 자동 생성·갱신")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    if args.fix:
        for path in iter_md(root):
            if len(read_lines(path)) > TOC_LINE_LIMIT and apply_toc(path):
                print(f"목차 갱신: {path.relative_to(root)}")

    errors: list[str] = []
    warns: list[str] = []
    count = 0
    for path in iter_md(root):
        count += 1
        lines = read_lines(path)
        rel = path.relative_to(root)
        check_toc(rel, lines, errors)
        if path.name == "SKILL.md":
            check_skill(path, rel, lines, errors, warns)

    for w in warns:
        print(f"[경고] {w}")
    for e in errors:
        print(f"[오류] {e}")
    print(f"검사 {count}개 문서 — 오류 {len(errors)}건, 경고 {len(warns)}건")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
