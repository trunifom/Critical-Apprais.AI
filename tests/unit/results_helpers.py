"""A project with a finished mock run, for the tests of results, charts and the Evaluation page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from crapai.llm.mock_provider import MockProvider
from crapai.project.workspace import Workspace
from crapai.services import screening as svc
from crapai.services.importing import ImportRequest, import_source
from crapai.services.preflight import check_project
from crapai.services.project import create_project

ABSTRACT = "The trial enrolled adults and measured outcomes over twelve months. " * 5


def project_with_run(
    tmp_path: Path, count: int = 24, scenario: str = "S12", *, with_run: bool = True
) -> Workspace:
    """``count`` records (every 6th has no abstract and every 5th says EXCLUDE_ME)."""
    parts = []
    for n in range(count):
        abstract = (
            ""
            if n % 6 == 5
            else f"AB  - {ABSTRACT} Record {n}."
            + (" EXCLUDE_ME" if n % 5 == 0 else (" UNSURE_ME" if n % 7 == 3 else ""))
        )
        lines = ["TY  - JOUR", f"TI  - Study number {n} on exercise", f"DO  - 10.1000/r{n}"]
        lines += [f"PY  - {2015 + n % 6}", f"JO  - Journal {n % 3}"]
        if abstract:
            lines.append(abstract)
        parts.append("\n".join([*lines, "ER  - "]))
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "s.ris"
    source.write_text("\n".join(parts) + "\n", encoding="utf-8")
    workspace = create_project(tmp_path / "p", template="demo")
    import_source(workspace, ImportRequest(source, label="PubMed"))
    data: dict[str, Any] = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data["llm"].update({"provider": "mock", "model": scenario, "base_url": None})
    data.setdefault("run", {}).update({"batch_size": 7, "retry_base_delay_s": 0.001})
    workspace.project_yaml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    check_project(workspace)  # marks the records without abstract
    if with_run:
        svc.screen_project(
            workspace, svc.RunOptions(provider=MockProvider(scenario), install_signal_handler=False)
        )
    return workspace
