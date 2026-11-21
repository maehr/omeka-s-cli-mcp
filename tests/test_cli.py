from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from typer.testing import CliRunner

from omeka_s_client import ResponseLost, TransportRequest, TransportResponse
from omeka_s_client.cli import build_app
from omeka_s_client.testing import FakeOmeka

runner = CliRunner()


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "URL",
        "KEY_IDENTITY",
        "KEY_CREDENTIAL",
        "TIMEOUT",
        "MCP_ALLOW_WRITES",
        "MCP_MAX_RECORDS",
        "MCP_WORKDIR",
    ):
        monkeypatch.delenv("OMEKA_" + key, raising=False)


def test_cli_settings_and_resource_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeOmeka({"items": [{"o:id": 1, "x-custom": {"flag": False}}], "media": []})
    app = build_app(transport=fake)
    dotenv = tmp_path / ".env"
    dotenv.write_text("OMEKA_URL=https://dotenv.example.org\nOMEKA_KEY_CREDENTIAL=dotenv-key\n")
    monkeypatch.chdir(tmp_path)
    bare = runner.invoke(app, ["get", "items", "1"])
    assert bare.exit_code == 2 and not fake.requests
    assert "URL" in bare.stderr and not bare.stdout
    credential = tmp_path / "credential"
    credential.write_text("file-secret\n")
    opts = [
        "--env-file",
        str(dotenv),
        "--key-identity",
        "key-id",
        "--key-credential-file",
        str(credential),
        "--url",
        "https://override.example.org/place",
    ]
    result = runner.invoke(app, [*opts, "get", "items", "1"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"o:id": 1, "x-custom": {"flag": False}}
    request = urlsplit(fake.requests[0].url)
    assert request.hostname == "override.example.org"
    assert parse_qs(request.query) == {
        "key_identity": ["key-id"],
        "key_credential": ["file-secret"],
    }
    result = runner.invoke(app, [*opts, "resources"])
    assert result.exit_code == 0, result.output
    assert [record["o:id"] for record in json.loads(result.stdout)] == ["items", "media"]
    result = runner.invoke(app, [*opts, "page", "items", "--page", "1", "--per-page", "1"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["total"] == 1


def test_cli_list_queries_verify_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeOmeka({"items": [{"o:id": 1}, {"o:id": 2}]})
    monkeypatch.setenv("OMEKA_URL", "https://example.org")
    app = build_app(transport=fake)
    expected = tmp_path / "expected.json"
    expected.write_text("[1, 2]")
    output = tmp_path / "records.jsonl"
    args = [
        "list",
        "items",
        "--filter",
        "tag=red",
        "--filter",
        "tag=blue",
        "--property",
        "dcterms:title",
        "eq",
        "a b",
        "--property",
        "10",
        "ex",
        "-",
        "--per-page",
        "1",
        "--expected-ids",
        str(expected),
        "--jsonl",
    ]
    result = runner.invoke(app, [*args, "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert not result.stdout
    assert [json.loads(line) for line in output.read_text().splitlines()] == [
        {"o:id": 1},
        {"o:id": 2},
    ]
    query = parse_qs(urlsplit(fake.requests[0].url).query)
    assert query["tag"] == ["red", "blue"]
    assert query["property[0][text]"] == ["a b"]
    assert "property[1][text]" not in query
    assert query["sort_order"] == ["asc"]
    result = runner.invoke(app, ["list", "items", "--verify"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)) == 2
    result = runner.invoke(app, ["list", "items", "--jsonl"])
    assert result.exit_code == 0
    assert len(result.stdout.splitlines()) == 2


def test_cli_create_patch_dry_run_and_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOmeka(
        {"item_sets": [{"o:id": 7}], "items": [], "media": []},
        files={"/download": b"file"},
    )
    app = build_app(transport=fake)
    monkeypatch.setenv("OMEKA_URL", "https://example.org")
    payload = tmp_path / "payload.json"
    payload.write_text('{"o:item_set":[{"o:id":7}]}')
    file = tmp_path / "upload.png"
    file.write_bytes(b"upload")
    args = ["create", "items", "--payload", str(payload)]
    for asset_args in ([], ["--file", str(file)], ["--asset-file", str(file)]):
        preview = runner.invoke(app, [*args, *asset_args, "--dry-run"])
        assert preview.exit_code == 0, preview.output
        assert json.loads(preview.stdout)["sent"] is False
    assert not fake.requests
    response = runner.invoke(app, args)
    assert response.exit_code == 0 and json.loads(response.stdout)["o:id"] == 1
    payload.write_text('{"dcterms:title":[{"@value":"Value"}]}')
    args = ["patch", "items", "1", "--payload", str(payload)]
    preview = runner.invoke(app, [*args, "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert not json.loads(preview.stdout)["sent"]
    response = runner.invoke(app, args)
    assert response.exit_code == 1 and len(fake.requests) == 1
    response = runner.invoke(app, [*args, "--replace-rdf-values"])
    assert response.exit_code == 0 and json.loads(response.stdout)["o:id"] == 1
    destination = tmp_path / "file"
    response = runner.invoke(app, ["download", "https://example.org/download", str(destination)])
    assert response.exit_code == 0 and json.loads(response.stdout)["size"] == 4
    assert destination.read_bytes() == b"file"
    for option, manifest in (
        ("raw", "download_metadata.json"),
        ("transformed", "transformation_metadata.json"),
        ("plain", "snapshot.json"),
    ):
        directory = tmp_path / option
        response = runner.invoke(
            app, ["snapshot", "capture", "7", str(directory), "--variant", option]
        )
        assert response.exit_code == 0, response.output
        assert json.loads(response.stdout)["items_count"] == 1
        assert (directory / manifest).exists()
        check = runner.invoke(app, ["snapshot", "check", str(directory)])
        assert check.exit_code == 0 and json.loads(check.stdout)["media_count"] == 0


def test_cli_errors_have_expected_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMEKA_URL", "https://example.org")
    payload = tmp_path / "payload.json"
    payload.write_text("{}")

    def transport(request: TransportRequest) -> TransportResponse:
        if request.method == "POST":
            raise ResponseLost(request.url)
        if request.url.split("?")[0].endswith("/items"):
            return TransportResponse(200, content=b'[{"o:id": 1}]')
        return TransportResponse(404, content=b"secret")

    app = build_app(transport=transport)
    cases = [
        (["list", "items", "--verify"], 3, "verification"),
        (["create", "items", "--payload", str(payload)], 4, "unknown"),
        (["get", "items", "1"], 1, "404"),
        (["list", "items", "--filter", "invalid"], 2, "KEY=VALUE"),
        (["snapshot", "capture", "1", str(tmp_path / "x"), "--variant", "invalid"], 2, "variant"),
        (
            [
                "create",
                "items",
                "--payload",
                str(payload),
                "--file",
                str(payload),
                "--asset-file",
                str(payload),
            ],
            2,
            "Choose",
        ),
        (["list", "items", "--output", str(tmp_path / "missing" / "list")], 2, "file input"),
        (["--key-identity", "secret", "get", "items", "1"], 2, "both Omeka keys"),
        (["--url", "https://example.org/?token=secret", "get", "items", "1"], 2, "installation"),
        (["mcp", "--transport", "bad"], 2, "transport"),
    ]
    for args, code, message in cases:
        result = runner.invoke(app, args)
        assert result.exit_code == code, result.output
        assert message in result.stderr
        assert (
            not result.stdout and "secret" not in result.stderr and "Traceback" not in result.stderr
        )
    monkeypatch.setenv("OMEKA_TIMEOUT", "secret")
    result = runner.invoke(app, ["get", "items", "1"])
    assert result.exit_code == 2 and "secret" not in result.stderr


def test_cli_main(monkeypatch: pytest.MonkeyPatch) -> None:
    import omeka_s_client.cli as cli

    calls: list[bool] = []
    monkeypatch.setattr(cli, "app", lambda: calls.append(True))
    cli.main()
    assert calls == [True]
