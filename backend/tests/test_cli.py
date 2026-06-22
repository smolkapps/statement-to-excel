import json

from statement_to_excel.cli import main


def test_cli_csv_to_file(fixtures_dir, tmp_path, capsys):
    out = tmp_path / "out.csv"
    rc = main([str(fixtures_dir / "acmebank.pdf"), "-o", str(out)])
    assert rc == 0
    text = out.read_text()
    assert text.splitlines()[0] == "date,description,amount,balance,currency,type"
    assert "PAYROLL" in text or "DEPOSIT" in text


def test_cli_json_stdout(fixtures_dir, capsys):
    rc = main([str(fixtures_dir / "acmebank.pdf"), "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data["transactions"]) == 5


def test_cli_xlsx_file(fixtures_dir, tmp_path):
    out = tmp_path / "out.xlsx"
    rc = main([str(fixtures_dir / "acmebank.pdf"), "-o", str(out)])
    assert rc == 0
    assert out.exists() and out.stat().st_size > 0


def test_cli_missing_file_returns_2(capsys):
    rc = main(["/no/such/file.pdf"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_cli_xlsx_to_stdout_rejected(fixtures_dir, capsys):
    rc = main([str(fixtures_dir / "acmebank.pdf"), "--format", "xlsx"])
    assert rc == 2
    assert "requires -o" in capsys.readouterr().err


def test_cli_unparseable_returns_1(fixtures_dir, capsys):
    rc = main([str(fixtures_dir / "scanned_empty.pdf"), "--format", "csv"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
