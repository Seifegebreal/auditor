from src.main import _print_result


def test_print_result_shows_report_path_and_graph_errors(capsys):
    _print_result(
        {
            "report_path": "audit/report/audit_report.md",
            "errors": ["Prosecutor initialization failed: unauthorized"],
        }
    )

    captured = capsys.readouterr()
    assert captured.out.strip() == "audit/report/audit_report.md"
    assert "Audit completed with errors:" in captured.err
    assert "- Prosecutor initialization failed: unauthorized" in captured.err


def test_print_result_does_not_emit_error_header_without_errors(capsys):
    _print_result({"report_path": "audit/report/audit_report.md", "errors": []})

    captured = capsys.readouterr()
    assert captured.out.strip() == "audit/report/audit_report.md"
    assert captured.err == ""
