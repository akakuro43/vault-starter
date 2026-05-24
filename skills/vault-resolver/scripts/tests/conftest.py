"""
conftest.py: pytest fixtures for vault-resolver tests.

Provides a `fake_vault` fixture that builds a minimal vault tree under tmp_path
and monkeypatches the path constants in lib.vault_io so no test touches the
real vault/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `lib` importable from inside the tests/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def fake_vault(tmp_path, monkeypatch):
    """Create a minimal vault tree and redirect vault_io path constants to it.

    Tree layout
    -----------
    tmp_path/vault/
    ├── 02_people/
    │   └── 田中太郎.md          (frontmatter: type: person)
    ├── 01_projects/
    │   └── foo-project/
    │       └── foo-project.md   (frontmatter: type: project)
    ├── 03_companies/
    │   └── 株式会社サンプル.md   (frontmatter: type: company)
    └── 06_knowledge/
        ├── insights/
        │   ├── AI研修方法論.md
        │   └── 知識の構造化.md
        ├── frameworks/
        │   └── ai-tool-levels/
        │       └── tool-level-framework.md
        └── references/
            └── claude-code/
                └── api-reference.md
    """
    vault = tmp_path / "vault"

    # 02_people
    _write(
        vault / "02_people" / "田中太郎.md",
        "---\ntype: person\nname: 田中太郎\n---\n",
    )

    # 01_projects
    _write(
        vault / "01_projects" / "foo-project" / "foo-project.md",
        "---\ntype: project\nname: Foo Project\n---\n",
    )

    # 03_companies
    _write(
        vault / "03_companies" / "株式会社サンプル.md",
        "---\ntype: company\nname: 株式会社サンプル\n---\n",
    )

    # 06_knowledge/insights
    _write(vault / "06_knowledge" / "insights" / "AI研修方法論.md", "# AI研修方法論\n")
    _write(vault / "06_knowledge" / "insights" / "知識の構造化.md", "# 知識の構造化\n")

    # 06_knowledge/frameworks (nested)
    _write(
        vault / "06_knowledge" / "frameworks" / "ai-tool-levels" / "tool-level-framework.md",
        "# Tool Level Framework\n",
    )

    # 06_knowledge/references (nested)
    _write(
        vault / "06_knowledge" / "references" / "claude-code" / "api-reference.md",
        "# API Reference\n",
    )

    # Monkeypatch vault_io path constants
    import lib.vault_io as vault_io

    monkeypatch.setattr(vault_io, "VAULT_DIR", vault)
    monkeypatch.setattr(vault_io, "PEOPLE_DIR", vault / "02_people")
    monkeypatch.setattr(vault_io, "PROJECTS_DIR", vault / "01_projects")
    monkeypatch.setattr(vault_io, "COMPANIES_DIR", vault / "03_companies")
    monkeypatch.setattr(vault_io, "KNOWLEDGE_DIR", vault / "06_knowledge")

    yield vault
