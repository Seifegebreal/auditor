import argparse
import os

from dotenv import load_dotenv

from src.graph import build_graph


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit a GitHub repository and its architectural report."
    )
    parser.add_argument("--repo-url", required=True, help="HTTPS GitHub repository URL")
    parser.add_argument(
        "--pdf",
        required=True,
        help="Path to the report (PDF, Markdown, or plain text)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("AUDIT_OUTPUT_DIR"),
        help="Directory for the Markdown audit report",
    )
    parser.add_argument(
        "--rubric",
        default=os.getenv("AUDITOR_RUBRIC"),
        help="Path to rubric JSON (or set AUDITOR_RUBRIC)",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    arguments = _arguments()
    if not arguments.output_dir:
        raise SystemExit("--output-dir or AUDIT_OUTPUT_DIR is required")
    if not arguments.rubric:
        raise SystemExit("--rubric or AUDITOR_RUBRIC is required")
    result = build_graph().invoke(
        {
            "repo_url": arguments.repo_url,
            "pdf_path": arguments.pdf,
            "output_dir": arguments.output_dir,
            "rubric_path": arguments.rubric,
            "repo_manifest": [],
            "claimed_paths": [],
            "errors": [],
            "evidences": {},
            "opinions": [],
        },
        config={
            "run_name": "automaton-auditor",
            "tags": ["week2", "automaton-auditor"],
            "metadata": {
                "rubric_path": arguments.rubric,
                "output_dir": arguments.output_dir,
            },
        },
    )
    print(result["report_path"])


if __name__ == "__main__":
    main()
