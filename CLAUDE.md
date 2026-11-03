# CLAUDE.md

Claude가 이 저장소에서 작업할 때 따르는 규칙.

## Claude 문서·스킬 작성 규칙

- 스킬(`SKILL.md`)이나 Claude·AI가 읽는 문서를 만들거나 고칠 때는 [.claude/standards/SKILL_RULES.md](.claude/standards/SKILL_RULES.md)를 따른다.
- 문서 작업 끝에 `python3 .claude/standards/check_docs.py`를 실행하고 오류가 0건이 될 때까지 고친다. 목차는 `--fix`로 자동 갱신한다.
