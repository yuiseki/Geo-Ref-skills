"""Check that the skills stay independent and consistent.

    python3 .agents/skills/check_skills.py

1. Every copy of a shared script (and its test) listed in COPIES is identical.
2. Every scripts/<name>.py has scripts/test_<name>.py beside it (evals/scripts too).
3. Every skill directory has a SKILL.md with name and description in its frontmatter, the name matching.
4. No SKILL.md points at another skill's directory.
5. No Markdown in the repository (tmp aside) uses bold or an em dash outside code.
"""

import filecmp
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
COPIES = {
    "webmercator.py": ["tile-reference", "feature-registration", "georef-gates", "gcp-refinement", "evals"],
    "tiles.py": ["tile-reference", "evals"],
    "transforms.py": ["georef-gates", "gcp-refinement", "evals"],
}


def script_dir(owner):
    return ROOT / "evals" / "scripts" if owner == "evals" else SKILLS / owner / "scripts"


def strip_code(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def main():
    errors = []
    for name, owners in COPIES.items():
        for f in (name, "test_" + name):
            first = script_dir(owners[0]) / f
            for o in owners[1:]:
                other = script_dir(o) / f
                if not other.exists() or not filecmp.cmp(first, other, shallow=False):
                    errors.append(f"copy differs or is missing: {other} vs {first}")
    dirs = [d / "scripts" for d in SKILLS.iterdir() if d.is_dir()] + [ROOT / "evals" / "scripts"]
    for d in dirs:
        for p in d.glob("*.py"):
            if not p.name.startswith("test_") and not (d / f"test_{p.name}").exists():
                errors.append(f"no test for {p}")
    names = sorted(d.name for d in SKILLS.iterdir() if d.is_dir() and not d.name.startswith("__"))
    for n in names:
        sk = SKILLS / n / "SKILL.md"
        if not sk.exists():
            errors.append(f"{n} has no SKILL.md")
            continue
        text = sk.read_text(encoding="utf-8")
        m = re.match(r"---\nname: (\S+)\ndescription: .+?\n---\n", text, flags=re.S)
        if not m or m.group(1) != n:
            errors.append(f"{sk}: frontmatter must start with name: {n} and a description")
        for other in names:
            if other != n and re.search(rf"(\.\./|skills/){re.escape(other)}\b", text):
                errors.append(f"{sk} points at the skill {other}")
    for md in ROOT.rglob("*.md"):
        parts = md.relative_to(ROOT).parts
        if "tmp" in parts or ".git" in parts or ".pytest_cache" in parts or "node_modules" in parts:
            continue
        body = strip_code(md.read_text(encoding="utf-8"))
        if "**" in body or "—" in body:
            errors.append(f"bold or em dash in {md.relative_to(ROOT)}")
    for e in errors:
        print(e)
    print("ok" if not errors else f"{len(errors)} problem(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
