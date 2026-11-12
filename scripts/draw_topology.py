import argparse
from pathlib import Path

from dotenv import load_dotenv

from src.graph import build_graph


ROLE_STYLES = {
    "setup": ("#dbeafe", "#2563eb", "ContextBuilder"),
    "detectives": (
        "#dcfce7",
        "#16a34a",
        "RepoInvestigator,DocAnalyst,VisionInspector",
    ),
    "aggregation": ("#fef3c7", "#d97706", "EvidenceAggregator"),
    "dispatch": ("#ede9fe", "#7c3aed", "JudicialDispatch"),
    "judges": ("#fce7f3", "#db2777", "Prosecutor,Defense,TechLead"),
    "justice": ("#cffafe", "#0891b2", "ChiefJustice"),
    "error": ("#fee2e2", "#dc2626", "ErrorReport"),
}


def _set_default_text_color(mermaid: str) -> str:
    lines = mermaid.splitlines()
    for index, line in enumerate(lines):
        prefix = "classDef default "
        stripped = line.lstrip()
        if stripped.startswith(prefix):
            if "color:" in stripped:
                return mermaid
            indentation = line[: len(line) - len(stripped)]
            styles = stripped[len(prefix) :]
            lines[index] = f"{indentation}{prefix}color:#222,{styles}"
            return "\n".join(lines)
    raise RuntimeError("Generated Mermaid graph has no default class definition")


def _set_start_node_style(mermaid: str) -> str:
    lines = mermaid.splitlines()
    for index, line in enumerate(lines):
        prefix = "classDef first "
        stripped = line.lstrip()
        if stripped.startswith(prefix):
            indentation = line[: len(line) - len(stripped)]
            styles = [
                style
                for style in stripped[len(prefix) :].split(",")
                if not style.startswith("fill-opacity:")
            ]
            styles.extend(
                ["fill:#dbeafe", "stroke:#2563eb", "color:#222", "fill-opacity:1"]
            )
            lines[index] = f"{indentation}{prefix}{','.join(styles)}"
            return "\n".join(lines)
    raise RuntimeError("Generated Mermaid graph has no first-node class definition")


def _add_role_colors(mermaid: str) -> str:
    styling = []
    for role, (fill, stroke, nodes) in ROLE_STYLES.items():
        styling.append(f"classDef {role} fill:{fill},stroke:{stroke},color:#222")
        styling.append(f"class {nodes} {role}")
    return f"{mermaid.rstrip()}\n" + "\n".join(styling)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Render the compiled Automaton Auditor topology."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional Mermaid output path; defaults to standard output",
    )
    arguments = parser.parse_args()
    mermaid = _add_role_colors(
        _set_start_node_style(
            _set_default_text_color(build_graph().get_graph().draw_mermaid())
        )
    )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(mermaid + "\n", encoding="utf-8")
        print(arguments.output)
    else:
        print(mermaid)


if __name__ == "__main__":
    main()
