"""Fail-closed static security checks for the public PAPER-only repository."""
from __future__ import annotations
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".jsonl",
    ".txt",
    ".gitignore",
}
IGNORE_DIRS = {"__pycache__", ".git"}

SECRET_PATTERNS = {
    "PRIVATE_KEY": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "GITHUB_PAT": re.compile(
        r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"
    ),
    "AWS_KEY": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "SLACK_TOKEN": re.compile(
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
    ),
    "OPENAI_KEY": re.compile(
        r"\bsk-[A-Za-z0-9_-]{20,}\b"
    ),
    "ASSIGNED_SECRET": re.compile(
        r"(?i)\b(?:api[_-]?key|password|passwd|secret|access[_-]?token)"
        r"\s*=\s*[\"\'][^\"\']{6,}[\"\']"
    ),
}

FORBIDDEN_CODE = {
    "LIVE_HTTP_WRITE": re.compile(
        r"(?i)\b(?:requests|httpx)\.(?:post|put|patch|delete)\s*\("
    ),
    "SHELL_EXEC": re.compile(
        r"\b(?:os\.system|subprocess\.(?:run|Popen|call|check_call|check_output))\s*\("
    ),
    "DYNAMIC_EXEC": re.compile(r"\b(?:eval|exec)\s*\("),
}

FORBIDDEN_WORKFLOW = {
    "SECRET_REFERENCE": re.compile(r"\bsecrets\."),
    "WRITE_PERMISSION": re.compile(
        r"(?mi)^\s*(?:contents|actions|checks|deployments|issues|packages|"
        r"pull-requests|repository-projects|security-events|statuses|id-token)"
        r"\s*:\s*write\s*$"
    ),
    "UNTRUSTED_PR_TRIGGER": re.compile(
        r"(?mi)^\s*(?:pull_request|pull_request_target|issue_comment|"
        r"repository_dispatch|workflow_run)\s*:\s*$"
    ),
}

PERSONAL_PATTERNS = {
    "EMAIL": re.compile(
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
    ),
    "JP_PHONE": re.compile(
        r"(?<!\d)(?:070|080|090)-?\d{4}-?\d{4}(?!\d)"
    ),
}

ALLOWED_EMAIL_LITERALS = {"example@example.com"}
ALLOWED_ACTION = (
    "actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830"
)


def iter_text_files(root: Path):
    for p in root.rglob("*"):
        if (
            not p.is_file()
            or any(part in IGNORE_DIRS for part in p.parts)
        ):
            continue
        if (
            p.name == ".coverage"
            or (
                p.suffix.lower() not in TEXT_SUFFIXES
                and p.name != ".gitignore"
            )
        ):
            continue
        yield p


def main(root: Path) -> int:
    failures: list[str] = []
    workflows = root / ".github" / "workflows"

    for p in iter_text_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(
                f"NON_UTF8:{p.relative_to(root)}"
            )
            continue

        rel = p.relative_to(root)

        for label, pat in SECRET_PATTERNS.items():
            if pat.search(text):
                failures.append(f"{label}:{rel}")

        for label, pat in PERSONAL_PATTERNS.items():
            for m in pat.finditer(text):
                if (
                    label == "EMAIL"
                    and (
                        m.group(0) in ALLOWED_EMAIL_LITERALS
                        or m.group(0)
                        .lower()
                        .endswith(".example")
                    )
                ):
                    continue
                failures.append(
                    f"POSSIBLE_{label}:{rel}:{m.group(0)}"
                )

        if p.suffix == ".py":
            for label, pat in FORBIDDEN_CODE.items():
                if pat.search(text):
                    failures.append(f"{label}:{rel}")

        if workflows in p.parents:
            for label, pat in FORBIDDEN_WORKFLOW.items():
                if pat.search(text):
                    failures.append(f"{label}:{rel}")

            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("uses:"):
                    value = stripped.split(":", 1)[1].strip()
                    if value != ALLOWED_ACTION:
                        failures.append(
                            f"UNPINNED_OR_UNAPPROVED_ACTION:{rel}"
                        )

            if "permissions: {}" not in text:
                failures.append(
                    f"WORKFLOW_NOT_ZERO_PERMISSION:{rel}"
                )

    if not (root / "readonly_fetch.py").is_file():
        failures.append("MISSING_READONLY_FETCH")

    for forbidden_name in (
        ".env",
        "credentials.json",
        "secrets.json",
    ):
        if (root / forbidden_name).exists():
            failures.append(
                f"FORBIDDEN_FILE:{forbidden_name}"
            )

    if failures:
        print("SECURITY_GUARD_BLOCKED")
        for item in sorted(set(failures)):
            print(item)
        return 1

    print("SECURITY_GUARD_OK")
    return 0


if __name__ == "__main__":
    target = Path(
        sys.argv[1] if len(sys.argv) > 1 else "."
    ).resolve()
    raise SystemExit(main(target))
