"""Tests for the command of aiobambulab."""

# pylint: disable=protected-access,redefined-outer-name

from __future__ import annotations

import asyncio
import io
import json
from typing import TYPE_CHECKING, Any

import pytest
from rich.console import Console

from aiobambulab import BambuLabClient, cli

from .conftest import ACCESS_CODE, FIXTURES, SERIAL, load_fixture

if TYPE_CHECKING:
    from pathlib import Path
    import ssl

    from .fake_printer import FakePrinter


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run the command in an empty directory, on a wide screen."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    for name in (cli.ENV_HOST, cli.ENV_SERIAL, cli.ENV_ACCESS_CODE):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def live(
    monkeypatch: pytest.MonkeyPatch, printer: FakePrinter, ssl_context: ssl.SSLContext
) -> FakePrinter:
    """Return a running P1S that the command looks at."""
    monkeypatch.setenv(cli.ENV_HOST, "127.0.0.1")
    monkeypatch.setenv(cli.ENV_SERIAL, SERIAL.lower())
    monkeypatch.setenv(cli.ENV_ACCESS_CODE, ACCESS_CODE)
    monkeypatch.setattr(
        cli,
        "_client",
        lambda host, serial, access_code: cli._RecordingClient(
            host,
            serial,
            access_code,
            port=printer.port,
            ssl_context=ssl_context,
            timeout=2,
        ),
    )
    return printer


def _console(*, terminal: bool = False) -> Console:
    return Console(file=io.StringIO(), width=200, force_terminal=terminal)


def _output(console: Console) -> str:
    assert isinstance(console.file, io.StringIO)
    return console.file.getvalue()


async def _run(*arguments: str) -> tuple[int, str]:
    console = _console()
    code = await cli._run(cli._parser().parse_args(arguments), console)
    return code, _output(console)


def _words(output: str) -> str:
    return " ".join(output.split())


def test_show_a_printer_with_a_nozzle_rack(capsys: pytest.CaptureFixture[str]) -> None:
    """The command shows the extruders, the rack, the AMS units and the spools."""
    file = str(FIXTURES / "h2c_status.json")

    assert cli.main(["show", "--file", file]) == 0

    output = capsys.readouterr().out
    # Tables that fit are next to each other.
    assert any(
        "Extruders" in line and "Nozzle rack" in line for line in output.splitlines()
    )
    words = _words(output)
    # The file does not tell what the printer is.
    assert "Model unknown" in words
    assert "External spools" in words
    assert "right active 27 °C 0.4 mm HS01 20D00A000000001 nothing loaded" in words
    assert "left 23 °C 0.4 mm HS01 - nothing loaded" in words
    assert "6 mounted 0.4 mm HS01 20D00A000000001 71 h 28 min" in words
    assert "0 AMS 2 Pro - 34 %, index 3 22.2 °C - - -" in words
    assert "128 AMS HT - 37 %, index 2 20.1 °C - - -" in words
    assert "2 empty -" in words
    assert "3 PLA Matte (PLA) 81 %" in words


async def test_show_what_an_extruder_is_loaded_from(tmp_path: Path) -> None:
    """The command tells which tray or spool the filament in an extruder is of."""
    report = load_fixture("h2c_status.json")["print"]
    report["device"]["extruder"]["info"][0]["snow"] = 0x8000
    report["device"]["extruder"]["info"][1]["snow"] = 0xFE00
    report["device"]["extruder"]["state"] = 0x12
    report["ams"]["ams"][0]["dry_time"] = 90
    report["nozzle_target_temper"] = 220
    report["device"]["extruder"]["info"][1]["temp"] = 220 << 16 | 23
    report["hms"] = [{"attr": 0x03000100, "code": 0x00010007}]
    report["device"]["nozzle"]["exist"] &= ~(1 << 16)
    file = tmp_path / "report.json"
    file.write_text(json.dumps(report))

    code, output = await _run("show", "--file", str(file))

    assert code == 0
    words = _words(output)
    assert "Model unknown" in words
    assert "AMS 128 tray 0: Support for PLA (PLA-S)" in words
    assert "left external spool: empty" in words
    assert "23 °C, set to 220 °C" in words
    assert "0 AMS 2 Pro - 34 %, index 3 22.2 °C 90 min left" in words
    assert "Error 0300_0100_0001_0007 (fatal)" in words
    assert words.count("1 empty - - -") == 1
    # The left extruder, and its external spool.
    assert output.count("active") == 2


async def test_show_a_printer_that_only_reports_its_nozzle(tmp_path: Path) -> None:
    """The command shows a file with the version and the status of a printer."""
    report: dict[str, Any] = {"nozzle_temper": 20, "vt_tray": {"tray_type": "PLA"}}
    file = tmp_path / "printer.json"
    file.write_text(json.dumps(load_fixture("h2d_version.json") | {"print": report}))

    code, output = await _run("show", "--file", str(file))

    assert code == 0
    words = _words(output)
    assert "Model H2D" in words
    assert "Firmware 01.01.01.00" in words
    assert "right active 20 °C - - nothing loaded" in words
    assert "Nozzle rack" not in output
    assert "AMS" not in output

    # What an AMS is comes with the version of the printer.
    report["ams"] = {"ams": [{"id": "0"}]}
    file.write_text(json.dumps(load_fixture("h2d_version.json") | {"print": report}))

    code, output = await _run("show", "--file", str(file))

    assert code == 0
    assert "0 AMS 2 Pro - - - - 19C00A000000001 02.00.19.47" in _words(output)


def test_show_a_printer_without_a_nozzle_rack(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command shows which extruder an AMS feeds, and no rack without one."""
    assert cli.main(["show", "--file", str(FIXTURES / "p2s_status.json")]) == 0

    output = capsys.readouterr().out
    assert "Nozzle rack" not in output
    words = _words(output)
    assert "0 AMS 2 Pro right extruder 34 %, index 3 19.2 °C - - -" in words
    assert "right PLA -" in words


async def test_show_a_printer_that_reports_little(tmp_path: Path) -> None:
    """The command shows what it knows, and no more."""
    file = tmp_path / "report.json"
    file.write_text(json.dumps({"device": {"extruder": {"info": [{"id": 0}]}}}))

    code, output = await _run("show", "--file", str(file))

    assert code == 0
    assert "right active - - - nothing loaded" in _words(output)

    file.write_text("{}")

    code, output = await _run("show", "--file", str(file))

    assert code == 0
    assert "Extruders" not in output


@pytest.mark.parametrize("content", ["nothing", "[]"])
def test_file_that_is_not_a_report(tmp_path: Path, content: str) -> None:
    """The command tells when it cannot make anything of a file."""
    file = tmp_path / "report.json"
    file.write_text(content)

    with pytest.raises(SystemExit, match=r"report\.json"):
        cli.main(["show", "--file", str(file)])


def test_dump_replaces_what_identifies(tmp_path: Path) -> None:
    """A dump does not tell which printer, nozzles and spools it is of."""
    source = tmp_path / "report.json"
    source.write_text(
        json.dumps(
            {
                "info": {"module": [{"name": "ota", "sn": "0948AB123456789"}]},
                "print": {
                    "ipcam": {"rtsp_url": "rtsps://192.168.1.50:322/streaming/live/1"},
                    "device": {
                        "nozzle": {
                            "info": [
                                {"id": 0, "sn": "20D11B7C3300999", "p_t": 5},
                                {"id": 1, "sn": "N/A"},
                                {"id": 21, "sn": "20D11B7C3300999"},
                            ]
                        }
                    },
                    "vir_slot": [
                        {"id": "255", "tag_uid": "A1B2C3D400000100"},
                        {"id": "254", "tag_uid": "0000000000000000"},
                    ],
                },
            }
        )
    )
    output = tmp_path / "dump.json"

    assert cli.main(["dump", "--file", str(source), "-o", str(output)]) == 0

    assert json.loads(output.read_text()) == {
        "info": {
            "command": "get_version",
            "module": [{"name": "ota", "sn": "094000000000001"}],
        },
        "print": {
            "ipcam": {"rtsp_url": "rtsps://192.0.2.1/streaming/live/1"},
            "device": {
                "nozzle": {
                    "info": [
                        {"id": 0, "sn": "20D000000000002", "p_t": 5},
                        {"id": 1, "sn": "N/A"},
                        {"id": 21, "sn": "20D000000000002"},
                    ]
                }
            },
            "vir_slot": [
                {"id": "255", "tag_uid": "0000000000000003"},
                {"id": "254", "tag_uid": "0000000000000000"},
            ],
        },
    }


async def test_dump_a_printer(live: FakePrinter) -> None:
    """The command asks a printer what it is and how it is, and nothing else."""
    assert live.status is not None
    live.status["print"]["upload"] = {"path": f"/{SERIAL}/model.3mf"}

    code, output = await _run("dump")

    assert code == 0
    assert SERIAL not in output
    dump = json.loads(output)
    assert dump["print"]["subtask_name"] == "Benchy"
    assert dump["print"]["upload"] == {"path": "/01P000000000001/model.3mf"}
    assert [module["sn"] for module in dump["info"]["module"]] == [
        "01P000000000001",
        "01P000000000001",
        "01P000000000002",
    ]
    assert [next(iter(request.values()))["command"] for request in live.requests] == [
        "get_version",
        "pushall",
    ]


async def test_show_a_printer(live: FakePrinter) -> None:
    """The command shows a printer without telling how it got to it."""
    code, output = await _run("show")

    assert code == 0
    assert "P1S" in output
    assert "01.08.02.00" in output
    assert "42 %, layer 96 of 240" in output
    assert "sport, 124 %" in output
    assert "60 °C, set to 60 °C" in output
    for secret in (SERIAL, ACCESS_CODE, "127.0.0.1"):
        assert secret not in output
    assert live.connections == 1


async def test_watch_a_printer(live: FakePrinter) -> None:
    """The command keeps showing a printer while it changes."""
    # Only a terminal is shown again what changed.
    console = _console(terminal=True)
    task = asyncio.create_task(
        cli._run(cli._parser().parse_args(["show", "--watch"]), console)
    )

    async def shows(text: str) -> None:
        async with asyncio.timeout(5):
            while text not in _output(console):  # noqa: ASYNC110
                await asyncio.sleep(0.01)

    await shows("Benchy")
    live.push({"print": {"command": "push_status", "msg": 1, "subtask_name": "Boat"}})
    await shows("Boat")
    await live.stop()
    await shows("The printer is not available")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_printer_that_refuses_the_access_code(
    live: FakePrinter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command tells why it could not look at a printer."""
    monkeypatch.setenv(cli.ENV_ACCESS_CODE, "87654321")

    code, output = await _run("show")

    assert code == 1
    assert "Could not connect: The printer rejected the access code" in output
    assert "87654321" not in output
    assert live.connections == 1


def test_credentials_of_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment tells which printer to look at, before a file does."""
    file = tmp_path / "printer.env"
    file.write_text(
        "# The printer in the office\n"
        f"{cli.ENV_HOST}=192.168.1.50\n"
        f"{cli.ENV_SERIAL} = '{SERIAL}'\n"
        f'{cli.ENV_ACCESS_CODE}="{ACCESS_CODE}"\n'
        "not a value\n"
    )
    monkeypatch.setenv(cli.ENV_HOST, "printer.local")

    assert cli._credentials(file) == ("printer.local", SERIAL, ACCESS_CODE)


def test_client_of_the_command() -> None:
    """The command looks at a printer with a client of the library."""
    client = cli._client("192.168.1.50", SERIAL, ACCESS_CODE)

    assert isinstance(client, BambuLabClient)
    assert client.snapshot().report == {}


def test_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The command tells what it needs to look at a printer."""
    monkeypatch.setenv(cli.ENV_HOST, "printer.local")

    with pytest.raises(SystemExit) as error:
        cli.main(["show"])

    assert str(error.value) == (
        f"Set {cli.ENV_SERIAL}, {cli.ENV_ACCESS_CODE} in the environment or in .env"
    )


def test_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The command stops without a word when it is interrupted."""

    async def interrupted(*_: Any) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run", interrupted)

    assert cli.main(["show", "--watch"]) == 0
