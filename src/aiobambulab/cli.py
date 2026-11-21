"""Command to look at a Bambu Lab printer the way this library sees it.

It only reads: it asks the printer for its version and its status, like the
client does when it connects.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, Any, Final

from .client import BambuLabClient
from .exceptions import BambuLabError
from .models import (
    Ams,
    AmsInfo,
    ExternalSpool,
    Extruder,
    Filament,
    FilamentSource,
    Nozzle,
    PrinterInfo,
    PrinterState,
    RackSlot,
)

_NEEDS_MORE: Final = (
    "The command needs more to be installed: pip install aiobambulab[cli]"
)

try:
    from rich.columns import Columns
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError as err:  # pragma: no cover
    raise SystemExit(_NEEDS_MORE) from err

if TYPE_CHECKING:
    from datetime import timedelta

    from rich.console import RenderableType

ENV_HOST: Final = "BAMBULAB_HOST"
ENV_SERIAL: Final = "BAMBULAB_SERIAL"
ENV_ACCESS_CODE: Final = "BAMBULAB_ACCESS_CODE"

# The values that tell one printer, nozzle or spool from every other.
_IDENTIFIERS: Final = frozenset({"sn", "tag_uid", "tray_uuid"})
_KEPT_OF_SERIAL: Final = 3

# The parts of the state that the command shows in tables of their own.
_PARTS: Final = frozenset(
    {"extruders", "nozzle_rack", "ams", "external_spools", "errors"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Snapshot:
    """What a printer reported, and what the library makes of it."""

    info: PrinterInfo
    state: PrinterState
    modules: list[dict[str, Any]]
    report: dict[str, Any]


class _RecordingClient(BambuLabClient):
    """Client that keeps what the printer reported, next to what it means."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the client."""
        super().__init__(*args, **kwargs)
        self._modules: list[dict[str, Any]] = []

    def _handle_message(self, payload: Any) -> None:
        """Handle a message of the printer, and keep the modules it reports."""
        with contextlib.suppress(TypeError, ValueError, AttributeError):
            version = json.loads(payload).get("info")
            if isinstance(version, dict) and isinstance(version.get("module"), list):
                self._modules = version["module"]
        super()._handle_message(payload)

    def snapshot(self) -> _Snapshot:
        """Return what the printer reported so far."""
        return _Snapshot(
            info=self.info,
            state=self.state,
            modules=self._modules,
            report=self._report,
        )


def _client(host: str, serial: str, access_code: str) -> _RecordingClient:
    """Return a client for a printer."""
    return _RecordingClient(host, serial, access_code)


def _read_env_file(path: Path) -> dict[str, str]:
    """Return the values of a file with a `NAME=value` on each line."""
    values = {}
    with contextlib.suppress(OSError):
        for line in path.read_text().splitlines():
            name, separator, value = line.partition("=")
            if separator and not name.lstrip().startswith("#"):
                values[name.strip()] = value.strip().strip("'\"")
    return values


def _credentials(env_file: Path) -> tuple[str, str, str]:
    """Return the host, serial number and access code of the printer to look at."""
    values = {**_read_env_file(env_file), **os.environ}
    names = (ENV_HOST, ENV_SERIAL, ENV_ACCESS_CODE)
    if missing := [name for name in names if not values.get(name)]:
        msg = f"Set {', '.join(missing)} in the environment or in {env_file}"
        raise SystemExit(msg)
    return values[ENV_HOST], values[ENV_SERIAL], values[ENV_ACCESS_CODE]


def _load(path: Path) -> _Snapshot:
    """Return what a printer reported, from a file.

    The file holds a status message, optionally next to a version message, or
    only what is in a status message.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as err:
        msg = f"Could not read {path}: {err}"
        raise SystemExit(msg) from err
    if not isinstance(data, dict):
        msg = f"{path} does not hold what a printer reports"
        raise SystemExit(msg)
    report = data["print"] if isinstance(data.get("print"), dict) else data
    version = data.get("info")
    modules = version.get("module") if isinstance(version, dict) else None
    if not isinstance(modules, list):
        modules = []
    info = PrinterInfo.from_modules("", modules)
    return _Snapshot(
        info=info,
        state=PrinterState.from_report(report, info.model),
        modules=modules,
        report=report,
    )


def _masked(snapshot: _Snapshot, serial: str) -> dict[str, Any]:
    """Return what the printer reported, without what identifies it.

    Serial numbers keep how they start, which tells what they are of. The same
    one is replaced by the same one everywhere.
    """
    replaced: dict[str, str] = {}

    def replace(original: str, kept: int) -> str:
        if original not in replaced:
            number = f"{len(replaced) + 1:0{len(original) - kept}X}"
            replaced[original] = f"{original[:kept]}{number}"
        return replaced[original]

    def mask_text(key: str, value: str) -> str:
        if key in _IDENTIFIERS and value.strip("0") and value != "N/A":
            return replace(value, _KEPT_OF_SERIAL if key == "sn" else 0)
        if key == "rtsp_url":
            return re.sub(r"://[^/]+", "://192.0.2.1", value)
        if serial and serial in value:
            return value.replace(serial, replace(serial, _KEPT_OF_SERIAL))
        return value

    def mask(key: str, value: Any) -> Any:
        if isinstance(value, dict):
            return {name: mask(name, item) for name, item in value.items()}
        if isinstance(value, list):
            return [mask(key, item) for item in value]
        return mask_text(key, value) if isinstance(value, str) else value

    return {
        "info": {"command": "get_version", "module": mask("", snapshot.modules)},
        "print": mask("", snapshot.report),
    }


def _temperature(current: float | None, target: float | None) -> str:
    """Return a temperature as text, with what it is set to when that is on."""
    if current is None:
        return "-"
    return f"{current} °C" if not target else f"{current} °C, set to {target} °C"


def _duration(duration: timedelta | None) -> str:
    """Return how long something took as text."""
    if duration is None:
        return "-"
    minutes = int(duration.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60:02} min"


def _nozzle(nozzle: Nozzle | None) -> str:
    """Return a nozzle as text."""
    if nozzle is None:
        return "-"
    diameter = None if nozzle.diameter is None else f"{nozzle.diameter} mm"
    return " ".join(filter(None, (diameter, nozzle.type))) or "unknown"


def _filament(filament: Filament | None) -> Text:
    """Return a filament as text, with its color."""
    if filament is None:
        return Text("empty", style="dim")
    text = Text()
    if filament.color is not None:
        text.append("  ", style=f"on #{filament.color[:6]}")
        text.append(" ")
    text.append(filament.name or filament.type or "unknown")
    if filament.name is not None and filament.type not in (None, filament.name):
        text.append(f" ({filament.type})", style="dim")
    return text


def _source(state: PrinterState, source: FilamentSource | None) -> Text:
    """Return where an extruder takes its filament from as text."""
    if source is None:
        return Text("nothing loaded", style="dim")
    if source.external_spool is not None:
        place = f"{source.external_spool} external spool"
        filament = next(
            (
                spool.filament
                for spool in state.external_spools
                if spool.extruder is source.external_spool
            ),
            None,
        )
    else:
        place = f"AMS {source.ams_id} tray {source.tray_id}"
        filament = next(
            (
                tray.filament
                for unit in state.ams
                if unit.id == source.ams_id
                for tray in unit.trays
                if tray.id == source.tray_id
            ),
            None,
        )
    return Text.assemble(place, ": ", _filament(filament))


def _table(title: str, *columns: str) -> Table:
    """Return a table that takes little room on the screen."""
    table = Table(
        title=title,
        title_justify="left",
        title_style="bold",
        header_style="dim",
        box=None,
        pad_edge=False,
        padding=(0, 2, 0, 0),
    )
    for column in columns:
        table.add_column(column)
    return table


def _active(*, active: bool) -> Text:
    """Return the mark of what the printer prints with."""
    return Text("active", style="green") if active else Text("")


def _extruders_table(extruders: tuple[Extruder, ...], state: PrinterState) -> Table:
    """Return the table of the extruders."""
    table = _table(
        "Extruders", "Extruder", "", "Temperature", "Nozzle", "Serial", "Filament from"
    )
    for extruder in extruders:
        table.add_row(
            extruder.position,
            _active(active=extruder.active),
            _temperature(extruder.temperature, extruder.target_temperature),
            _nozzle(extruder.nozzle),
            (extruder.nozzle.serial if extruder.nozzle else None) or "-",
            _source(state, extruder.filament_source),
        )
    return table


def _rack_table(slots: tuple[RackSlot, ...]) -> Table:
    """Return the table of the nozzle rack."""
    table = _table("Nozzle rack", "Slot", "State", "Nozzle", "Serial", "Printed for")
    for slot in slots:
        table.add_row(
            str(slot.number),
            slot.state,
            _nozzle(slot.nozzle),
            (slot.nozzle.serial if slot.nozzle else None) or "-",
            _duration(slot.nozzle.print_time if slot.nozzle else None),
        )
    return table


def _remaining(filament: Filament | None) -> str:
    """Return how much of a filament is left as text."""
    if filament is None or filament.remaining is None:
        return "-"
    return f"{filament.remaining} %"


def _humidity(unit: Ams) -> str:
    """Return the humidity in an AMS as text."""
    parts = (
        None if unit.humidity is None else f"{unit.humidity} %",
        None if unit.humidity_index is None else f"index {unit.humidity_index}",
    )
    return ", ".join(part for part in parts if part) or "-"


def _ams_units_table(units: tuple[Ams, ...], info: dict[int, AmsInfo]) -> Table:
    """Return the table of what is known of each AMS as a whole."""
    table = _table(
        "AMS units",
        "AMS",
        "Kind",
        "Feeds",
        "Humidity",
        "Temperature",
        "Drying",
        "Serial",
        "Firmware",
    )
    for unit in units:
        unit_info = info.get(unit.id, AmsInfo(id=unit.id))
        drying = unit.drying_remaining_minutes
        table.add_row(
            str(unit.id),
            unit.model or unit_info.model or "-",
            f"{unit.extruder} extruder" if unit.extruder else "-",
            _humidity(unit),
            _temperature(unit.temperature, None),
            f"{drying} min left" if drying else "-",
            unit_info.serial or "-",
            unit_info.firmware_version or "-",
        )
    return table


def _trays_table(unit: Ams) -> Table:
    """Return the table of the trays of an AMS."""
    table = _table(f"AMS {unit.id}", "Tray", "", "Filament", "Left")
    for tray in unit.trays:
        table.add_row(
            str(tray.id),
            _active(active=tray.active),
            _filament(tray.filament),
            _remaining(tray.filament),
        )
    return table


def _external_spools_table(spools: tuple[ExternalSpool, ...]) -> Table:
    """Return the table of the external spools."""
    table = _table("External spools", "Extruder", "", "Filament", "Left")
    for spool in spools:
        table.add_row(
            spool.extruder,
            _active(active=spool.active),
            _filament(spool.filament),
            _remaining(spool.filament),
        )
    return table


def _printer_values(snapshot: _Snapshot) -> Group:
    """Return what the printer reports that is one value, in a few columns."""
    info = snapshot.info
    values = [("model", info.model_name or "unknown")]
    values.extend(
        (name, str(value))
        for name in ("firmware_version", "hardware_version")
        if (value := getattr(info, name)) is not None
    )
    values.extend(
        (field.name, str(value))
        for field in dataclasses.fields(snapshot.state)
        if field.name not in _PARTS
        and (value := getattr(snapshot.state, field.name)) is not None
    )
    values.extend(
        ("error", f"{error.code} ({error.severity or 'unknown'})")
        for error in snapshot.state.errors
    )
    return Group(
        Text("Printer", style="bold"),
        Columns(
            [Text.assemble((name, "dim"), " ", value) for name, value in values],
            column_first=True,
            padding=(0, 3),
        ),
    )


def _stack(*tables: Table) -> Table:
    """Return tables below each other, as one thing to put next to another."""
    stack = Table.grid()
    for index, table in enumerate(tables):
        if index:
            stack.add_row(Text())
        stack.add_row(table)
    return stack


def _row(*tables: Table) -> Columns:
    """Return tables next to each other, as far as the screen is wide enough."""
    return Columns(tables, padding=(0, 4, 1, 0))


def _view(snapshot: _Snapshot) -> RenderableType:
    """Return what the library makes of a printer, to show.

    Tables are next to each other where they fit, to keep it all on one screen.
    """
    state = snapshot.state
    info = {unit.id: unit for unit in snapshot.info.ams}
    left = []
    if state.extruders:
        left.append(_extruders_table(state.extruders, state))
    if state.ams:
        left.append(_ams_units_table(state.ams, info))
    toolhead = [_stack(*left)] if left else []
    if state.nozzle_rack:
        toolhead.append(_rack_table(state.nozzle_rack))
    spools = [_trays_table(unit) for unit in state.ams]
    if state.external_spools:
        spools.append(_external_spools_table(state.external_spools))
    parts: list[RenderableType] = [_printer_values(snapshot)]
    for tables in (toolhead, spools):
        if tables:
            parts.extend((Text(), _row(*tables)))
    return Group(*parts)


async def _watch(client: _RecordingClient, console: Console) -> None:
    """Show a printer, and what changes, until interrupted."""
    changed = asyncio.Event()
    client.add_listener(changed.set)

    def view() -> RenderableType:
        if not client.available:
            return Panel(f"The printer is not available: {client.error}")
        return _view(client.snapshot())

    with Live(view(), console=console, screen=True) as live:
        while True:
            await changed.wait()
            changed.clear()
            live.update(view())


async def _run(args: argparse.Namespace, console: Console) -> int:
    """Run the command, and return its exit code."""
    serial = ""
    if args.file is not None:
        snapshot = _load(args.file)
    else:
        host, serial, access_code = _credentials(args.env_file)
        try:
            async with _client(host, serial, access_code) as client:
                if args.command == "show" and args.watch:
                    await _watch(client, console)
                snapshot = client.snapshot()
        except BambuLabError as err:
            console.print(f"Could not connect: {err}", style="red")
            return 1
    if args.command == "dump":
        text = json.dumps(_masked(snapshot, serial.upper()), indent=2)
        if args.output is None:
            console.file.write(f"{text}\n")
        else:
            args.output.write_text(f"{text}\n")
    else:
        console.print(_view(snapshot))
    return 0


def _parser() -> argparse.ArgumentParser:
    """Return the parser of the arguments of the command."""
    source = argparse.ArgumentParser(add_help=False)
    source.add_argument(
        "--file",
        type=Path,
        help="read what a printer reported from a file, like one that dump wrote",
    )
    source.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="file with the host, serial number and access code (default: .env)",
    )
    parser = argparse.ArgumentParser(
        prog="aiobambulab",
        description=(
            "Look at a Bambu Lab printer the way aiobambulab sees it. Reads "
            f"{ENV_HOST}, {ENV_SERIAL} and {ENV_ACCESS_CODE} from the environment "
            "or from a .env file. It only asks the printer for its version and "
            "its status."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser(
        "show",
        parents=[source],
        help="show the printer: extruders, nozzles, rack, AMS units and spools",
    )
    show.add_argument(
        "--watch", action="store_true", help="keep showing the printer as it changes"
    )
    dump = commands.add_parser(
        "dump",
        parents=[source],
        help=(
            "write what the printer reports as JSON, with serial numbers and "
            "the ids of spools replaced. Names of print jobs stay."
        ),
    )
    dump.add_argument("-o", "--output", type=Path, help="file to write to")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command."""
    args = _parser().parse_args(argv)
    with contextlib.suppress(KeyboardInterrupt):
        return asyncio.run(_run(args, Console()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
