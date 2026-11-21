"""Models for aiobambulab."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
import math
from typing import Any, Final, Self

from .stages import STAGES, PrintStage


class PrinterModel(StrEnum):
    """The printer models this library knows."""

    A1 = "A1"
    A1_MINI = "A1 mini"
    A2L = "A2L"
    H2C = "H2C"
    H2D = "H2D"
    H2D_PRO = "H2D Pro"
    H2S = "H2S"
    H3C = "H3C"
    P1P = "P1P"
    P1S = "P1S"
    P2S = "P2S"
    X1C = "X1 Carbon"
    X1E = "X1E"
    X2D = "X2D"


class PrintState(StrEnum):
    """What the printer is doing with its print job."""

    IDLE = "idle"
    INITIALIZING = "initializing"
    SLICING = "slicing"
    PREPARING = "preparing"
    PRINTING = "printing"
    PAUSED = "paused"
    FINISHED = "finished"
    FAILED = "failed"


class SpeedProfile(StrEnum):
    """The speed profile of the printer."""

    SILENT = "silent"
    STANDARD = "standard"
    SPORT = "sport"
    LUDICROUS = "ludicrous"


class Fan(StrEnum):
    """The fans of a printer that can be set to a speed."""

    PART_COOLING = "part_cooling"
    AUXILIARY = "auxiliary"
    CHAMBER = "chamber"


class ErrorSeverity(StrEnum):
    """How bad a problem is that the printer reports."""

    FATAL = "fatal"
    SERIOUS = "serious"
    COMMON = "common"
    INFO = "info"


class AmsModel(StrEnum):
    """The kinds of AMS this library knows."""

    AMS = "AMS"
    AMS_LITE = "AMS Lite"
    AMS_2_PRO = "AMS 2 Pro"
    AMS_HT = "AMS HT"


class ExtruderPosition(StrEnum):
    """Where an extruder is on the toolhead.

    A printer with one extruder has the right one.
    """

    RIGHT = "right"
    LEFT = "left"


class RackSlotState(StrEnum):
    """What a slot of the nozzle rack holds.

    The nozzle of a slot that is mounted is on an extruder.
    """

    DOCKED = "docked"
    MOUNTED = "mounted"
    EMPTY = "empty"


_PRODUCT_NAME_PREFIX: Final = "Bambu Lab "

# Product names that differ from the name of the model.
_MODEL_ALIASES: Final = {"X1-Carbon": PrinterModel.X1C}

# These models have no video stream: they send images of their camera.
MODELS_WITH_CAMERA_IMAGES: Final = frozenset(
    {
        PrinterModel.A1,
        PrinterModel.A1_MINI,
        PrinterModel.A2L,
        PrinterModel.P1P,
        PrinterModel.P1S,
    }
)

# These models report a chamber temperature, but have no sensor to measure it.
_MODELS_WITHOUT_CHAMBER_SENSOR: Final = frozenset(
    {
        PrinterModel.A1,
        PrinterModel.A1_MINI,
        PrinterModel.A2L,
        PrinterModel.P1P,
        PrinterModel.P1S,
    }
)

# The states of a print job, as a printer reports them.
_PRINT_STATES: Final = {
    "IDLE": PrintState.IDLE,
    "INIT": PrintState.INITIALIZING,
    "SLICING": PrintState.SLICING,
    "PREPARE": PrintState.PREPARING,
    "RUNNING": PrintState.PRINTING,
    "PAUSE": PrintState.PAUSED,
    "FINISH": PrintState.FINISHED,
    "FAILED": PrintState.FAILED,
}

SPEED_PROFILES: Final = {
    1: SpeedProfile.SILENT,
    2: SpeedProfile.STANDARD,
    3: SpeedProfile.SPORT,
    4: SpeedProfile.LUDICROUS,
}

_CHAMBER_LIGHT: Final = "chamber_light"

_ERROR_SEVERITIES: Final = {
    1: ErrorSeverity.FATAL,
    2: ErrorSeverity.SERIOUS,
    3: ErrorSeverity.COMMON,
    4: ErrorSeverity.INFO,
}

# A printer reports the speed of a fan as a level up to this one.
_MAX_FAN_LEVEL: Final = 15

# What a printer reports as the tray it prints from, when that is not a tray
# of an AMS.
_EXTERNAL_SPOOL: Final = 254
# An AMS with one tray has an id from this number on, and is the tray itself.
_FIRST_SINGLE_TRAY_AMS: Final = 128
_TRAYS_PER_AMS: Final = 4

# A printer with one external spool reports it with the first id. A printer
# with two extruders has one for each, and the second id is the left one.
_EXTERNAL_SPOOLS: Final = {
    255: ExtruderPosition.RIGHT,
    254: ExtruderPosition.LEFT,
}
# What an extruder reports as its tray when no filament is loaded.
_NO_TRAY: Final = 0xFF

_EXTRUDER_POSITIONS: Final = {0: ExtruderPosition.RIGHT, 1: ExtruderPosition.LEFT}

# A nozzle has the id of where it is: an extruder, or from this id on a slot
# of the nozzle rack.
_FIRST_RACK_SLOT: Final = 16
_RACK_SLOTS: Final = 6

# The kind of an AMS, as the last digit of what it reports about itself.
_AMS_MODELS: Final = {
    1: AmsModel.AMS,
    2: AmsModel.AMS_LITE,
    3: AmsModel.AMS_2_PRO,
    4: AmsModel.AMS_HT,
}

# The kind of an AMS, as the start of the name of its module.
_AMS_MODULES: Final = {
    "ams": AmsModel.AMS,
    "ams_f1": AmsModel.AMS_LITE,
    "n3f": AmsModel.AMS_2_PRO,
    "n3s": AmsModel.AMS_HT,
}

# How a printer tells that it only accepts commands that are signed.
_FUN_SIGNATURE_REQUIRED: Final = 0x20000000
_FLAG3_AUTHORIZATION_CONTROL: Final = 0x10


def _as_float(value: Any) -> float | None:
    """Return the value as a float, or None if it is not a finite number."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_int(value: Any) -> int | None:
    """Return the value as an integer, or None if it is not a number."""
    number = _as_float(value)
    return None if number is None else int(number)


def _as_degrees(value: Any) -> int | None:
    """Return a temperature in whole degrees, like the printer shows it.

    Some printers report temperatures in steps of 1/32 degree. That is more
    than their sensors can tell, and it changes with every report.
    """
    number = _as_float(value)
    return None if number is None else round(number)


def _as_text(value: Any) -> str | None:
    """Return the value as text, or None if it is empty or not text."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _model_from_hardware(
    hardware_version: str, project_name: str
) -> PrinterModel | None:
    """Return the model of a printer that does not report its product name."""
    if hardware_version == "AP02":
        return PrinterModel.X1E
    if project_name == "N1":
        return PrinterModel.A1_MINI
    return {
        ("AP04", "C11"): PrinterModel.P1P,
        ("AP04", "C12"): PrinterModel.P1S,
        ("AP05", "N2S"): PrinterModel.A1,
        ("AP05", ""): PrinterModel.X1C,
    }.get((hardware_version, project_name))


@dataclass(frozen=True, slots=True, kw_only=True)
class AmsInfo:
    """What an AMS is: its kind, its serial number and its versions.

    The id is the one of the `Ams` in the state of the printer.
    """

    id: int
    model: AmsModel | None = None
    serial: str | None = None
    firmware_version: str | None = None
    hardware_version: str | None = None


def _ams_info(modules: list[dict[str, Any]]) -> tuple[AmsInfo, ...]:
    """Return the AMS units among the modules a printer reports."""
    units = []
    for module in modules:
        kind, _, number = str(module.get("name", "")).partition("/")
        if kind not in _AMS_MODULES or not number.isdecimal():
            continue
        units.append(
            AmsInfo(
                id=int(number),
                model=_AMS_MODULES[kind],
                serial=_as_text(module.get("sn")),
                firmware_version=_as_text(module.get("sw_ver")),
                hardware_version=_as_text(module.get("hw_ver")),
            )
        )
    return tuple(sorted(units, key=lambda unit: unit.id))


@dataclass(frozen=True, slots=True, kw_only=True)
class PrinterInfo:
    """What a printer is: its model and its versions, and the same of each AMS."""

    serial: str
    model: PrinterModel | None = None
    model_name: str | None = None
    firmware_version: str | None = None
    hardware_version: str | None = None
    ams: tuple[AmsInfo, ...] = ()

    @classmethod
    def from_modules(cls, serial: str, modules: Any) -> Self:
        """Create the info from the modules a printer reports for its version."""
        if not isinstance(modules, list):
            modules = []
        modules = [module for module in modules if isinstance(module, dict)]
        ota: dict[str, Any] = next(
            (mod for mod in modules if mod.get("name") == "ota"), {}
        )
        # The mainboard is the module with an "AP" hardware version.
        board: dict[str, Any] = next(
            (mod for mod in modules if str(mod.get("hw_ver", "")).startswith("AP")),
            {},
        )
        hardware_version = _as_text(board.get("hw_ver"))

        model: PrinterModel | None = None
        model_name = _as_text(ota.get("product_name"))
        if model_name is not None:
            model_name = model_name.removeprefix(_PRODUCT_NAME_PREFIX)
            try:
                model = PrinterModel(model_name)
            except ValueError:
                model = _MODEL_ALIASES.get(model_name)
        elif hardware_version is not None:
            # Older firmware does not report a product name.
            model = _model_from_hardware(
                hardware_version, str(board.get("project_name", ""))
            )
        if model is not None:
            model_name = model.value

        return cls(
            serial=serial,
            model=model,
            model_name=model_name,
            firmware_version=_as_text(ota.get("sw_ver")),
            hardware_version=hardware_version,
            ams=_ams_info(modules),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PrinterError:
    """A problem the printer reports, which Bambu Lab calls an HMS code.

    The code is the one to look up at Bambu Lab, like `0300_0100_0001_0007`.
    """

    code: str
    severity: ErrorSeverity | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Filament:
    """The filament on a spool.

    The color is `RRGGBBAA`. What remains is a percentage, and only known for
    a spool with a tag of Bambu Lab.
    """

    type: str | None = None
    name: str | None = None
    color: str | None = None
    remaining: int | None = None
    nozzle_temperature_min: int | None = None
    nozzle_temperature_max: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AmsTray:
    """A tray of an AMS. The filament is None when the tray is empty.

    The tray is active when the extruder that prints takes its filament from it.
    """

    id: int
    filament: Filament | None = None
    active: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Ams:
    """An AMS: the unit that feeds filament to the printer.

    The humidity index is the level from 1 to 5 that the printer shows. Newer
    units also report the humidity as a percentage. A unit that dries its
    filament reports the minutes that takes from now, and 0 when it does not.

    The extruder is the one that the unit feeds. It is None when the printer
    does not tell, or when the unit can feed both.
    """

    id: int
    model: AmsModel | None = None
    extruder: ExtruderPosition | None = None
    humidity_index: int | None = None
    humidity: int | None = None
    temperature: float | None = None
    drying_remaining_minutes: int | None = None
    trays: tuple[AmsTray, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalSpool:
    """A spool next to the printer, that feeds one extruder without an AMS.

    The filament is None when the printer does not know of a spool. What
    remains of it is only known for a spool with a tag that the printer read.
    The spool is active when its extruder prints from it.
    """

    extruder: ExtruderPosition
    filament: Filament | None = None
    active: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class FilamentSource:
    """Where the filament in an extruder comes from.

    That is a tray of an AMS, by the id of both, or an external spool, by the
    extruder it belongs to.
    """

    ams_id: int | None = None
    tray_id: int | None = None
    external_spool: ExtruderPosition | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Nozzle:
    """A nozzle: the part that can be taken off an extruder.

    Only a nozzle that the printer can tell apart has a serial number, and a
    time that it printed for.
    """

    diameter: float | None = None
    type: str | None = None
    serial: str | None = None
    print_time: timedelta | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Extruder:
    """An extruder: a fixed place on the toolhead that melts filament.

    The active extruder is the one that prints. The nozzle is None when there
    is none on the extruder, or the printer does not tell which. The filament
    source is None when no filament is loaded.
    """

    position: ExtruderPosition
    temperature: int | None = None
    target_temperature: int | None = None
    active: bool = False
    nozzle: Nozzle | None = None
    filament_source: FilamentSource | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RackSlot:
    """A slot of the nozzle rack, numbered from 1.

    A slot keeps its nozzle while that one is mounted on an extruder.
    """

    number: int
    state: RackSlotState = RackSlotState.EMPTY
    nozzle: Nozzle | None = None


def _fan_speed(value: Any) -> int | None:
    """Return the speed of a fan as a percentage, in steps of ten.

    The level a printer reports wavers between two neighbors for one speed.
    Rounding up to the step the speed is set in keeps it steady.
    """
    level = _as_int(value)
    if level is None or not 0 <= level <= _MAX_FAN_LEVEL:
        return None
    return -(-level * 10 // _MAX_FAN_LEVEL) * 10  # pylint: disable=invalid-unary-operand-type


def _print_error(report: dict[str, Any]) -> str | None:
    """Return the code of the error of the print job, like `0700_8006`."""
    if not (code := _as_int(report.get("print_error"))) or code < 0:
        return None
    text = f"{code:08X}"
    return f"{text[:4]}_{text[4:]}"


def _errors(report: dict[str, Any]) -> tuple[PrinterError, ...]:
    """Return the problems the printer reports."""
    entries = report.get("hms")
    if not isinstance(entries, list):
        return ()
    errors = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        attr = _as_int(entry.get("attr"))
        code = _as_int(entry.get("code"))
        if not attr or not code or attr < 0 or code < 0:
            continue
        errors.append(
            PrinterError(
                code=(
                    f"{attr >> 16:04X}_{attr & 0xFFFF:04X}"
                    f"_{code >> 16:04X}_{code & 0xFFFF:04X}"
                ),
                severity=_ERROR_SEVERITIES.get(code >> 16),
            )
        )
    return tuple(errors)


def _color(value: Any) -> str | None:
    """Return a color as `RRGGBBAA`, or None if it is not one."""
    color = _as_text(value)
    if color is None or len(color) != 8:
        return None
    try:
        int(color, 16)
    except ValueError:
        return None
    return color.upper()


def _filament(tray: dict[str, Any]) -> Filament | None:
    """Return the filament of a tray, or None if the tray is empty."""
    kind = _as_text(tray.get("tray_type"))
    if kind is None and _as_text(tray.get("tray_info_idx")) is None:
        # An empty tray only has an id.
        return None
    remaining = _as_int(tray.get("remain"))
    return Filament(
        type=kind,
        name=_as_text(tray.get("tray_sub_brands")),
        color=_color(tray.get("tray_color")),
        remaining=(
            remaining if remaining is not None and 0 <= remaining <= 100 else None
        ),
        nozzle_temperature_min=_as_int(tray.get("nozzle_temp_min")) or None,
        nozzle_temperature_max=_as_int(tray.get("nozzle_temp_max")) or None,
    )


def _entries(value: Any) -> list[dict[str, Any]]:
    """Return the objects of a list a printer reports, and nothing else."""
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _device(report: dict[str, Any], part: str) -> dict[str, Any]:
    """Return what the printer reports about one of its parts."""
    device = report.get("device")
    block = device.get(part) if isinstance(device, dict) else None
    return block if isinstance(block, dict) else {}


def _in_range(value: int | None, low: int, high: int) -> int | None:
    """Return the value if it is in the range, and None if not."""
    return value if value is not None and low <= value <= high else None


def _legacy_filament_source(report: dict[str, Any]) -> FilamentSource | None:
    """Return where the filament comes from, for a printer with one number for it."""
    ams = report.get("ams")
    tray = _as_int(ams.get("tray_now")) if isinstance(ams, dict) else None
    if tray is None or tray < 0 or tray > _EXTERNAL_SPOOL:
        return None
    if tray == _EXTERNAL_SPOOL:
        return FilamentSource(external_spool=ExtruderPosition.RIGHT)
    if tray >= _FIRST_SINGLE_TRAY_AMS:
        return FilamentSource(ams_id=tray, tray_id=0)
    ams_id, tray_id = divmod(tray, _TRAYS_PER_AMS)
    return FilamentSource(ams_id=ams_id, tray_id=tray_id)


def _filament_source(value: Any) -> FilamentSource | None:
    """Return where the filament in an extruder comes from.

    The low 8 bits hold the tray, the next 8 bits hold the AMS. An external
    spool has the id of an AMS.
    """
    packed = _as_int(value)
    if packed is None or packed < 0 or packed & 0xFF == _NO_TRAY:
        return None
    ams_id, tray_id = packed >> 8 & 0xFF, packed & 0xFF
    if ams_id in _EXTERNAL_SPOOLS:
        return FilamentSource(external_spool=_EXTERNAL_SPOOLS[ams_id])
    return FilamentSource(ams_id=ams_id, tray_id=tray_id)


def _nozzle(entry: dict[str, Any]) -> Nozzle:
    """Return a nozzle the printer reports."""
    serial = _as_text(entry.get("sn"))
    if serial == "N/A":
        serial = None
    seconds = _as_int(entry.get("p_t"))
    return Nozzle(
        diameter=_as_float(entry.get("diameter")) or None,
        type=_as_text(entry.get("type")),
        serial=serial,
        print_time=(
            timedelta(seconds=seconds)
            if serial is not None and seconds is not None and seconds >= 0
            else None
        ),
    )


def _nozzles(report: dict[str, Any]) -> dict[int, Nozzle]:
    """Return the nozzles of the printer, by the id of where each one is."""
    block = _device(report, "nozzle")
    # Each bit tells whether there is a nozzle at the place with that id.
    present = _as_int(block.get("exist"))
    nozzles = {}
    for entry in _entries(block.get("info")):
        place = _as_int(entry.get("id"))
        if place is None or place < 0:
            continue
        if present is not None and not present >> place & 1:
            continue
        nozzles[place] = _nozzle(entry)
    return nozzles


def _legacy_extruder(report: dict[str, Any]) -> tuple[Extruder, ...]:
    """Return the extruder of a printer that only reports about its nozzle."""
    temperature = _as_degrees(report.get("nozzle_temper"))
    target_temperature = _as_degrees(report.get("nozzle_target_temper"))
    diameter = _as_float(report.get("nozzle_diameter")) or None
    kind = _as_text(report.get("nozzle_type"))
    if all(
        value is None for value in (temperature, target_temperature, diameter, kind)
    ):
        return ()
    return (
        Extruder(
            position=ExtruderPosition.RIGHT,
            temperature=temperature,
            target_temperature=target_temperature,
            active=True,
            nozzle=(
                None
                if diameter is None and kind is None
                else Nozzle(diameter=diameter, type=kind)
            ),
            filament_source=_legacy_filament_source(report),
        ),
    )


def _extruders(
    report: dict[str, Any], nozzles: dict[int, Nozzle]
) -> tuple[Extruder, ...]:
    """Return the extruders of the printer, the right one first."""
    block = _device(report, "extruder")
    entries = {
        extruder_id: entry
        for entry in _entries(block.get("info"))
        if (extruder_id := _as_int(entry.get("id"))) in _EXTRUDER_POSITIONS
    }
    if not entries:
        return _legacy_extruder(report)
    # The low 4 bits hold the number of extruders, the next 4 bits hold the
    # one that prints. That is none of them while the printer switches.
    state = _as_int(block.get("state"))
    active = 0 if state is None else state >> 4 & 0xF
    extruders = []
    for extruder_id, entry in sorted(entries.items()):
        # The low 16 bits hold the current temperature, the high 16 bits hold
        # the target.
        temperature = _as_int(entry.get("temp"))
        if temperature is not None and temperature < 0:
            temperature = None
        nozzle_id = _as_int(entry.get("hnow"))
        extruders.append(
            Extruder(
                position=_EXTRUDER_POSITIONS[extruder_id],
                temperature=None if temperature is None else temperature & 0xFFFF,
                target_temperature=(
                    None if temperature is None else temperature >> 16 & 0xFFFF
                ),
                active=extruder_id == active,
                nozzle=nozzles.get(extruder_id if nozzle_id is None else nozzle_id),
                filament_source=_filament_source(entry.get("snow")),
            )
        )
    return tuple(extruders)


def _nozzle_rack(
    report: dict[str, Any], nozzles: dict[int, Nozzle]
) -> tuple[RackSlot, ...]:
    """Return the slots of the nozzle rack, or nothing without a rack."""
    device = report.get("device")
    has_rack = isinstance(device, dict) and isinstance(device.get("holder"), dict)
    last = max(nozzles, default=0)
    if not has_rack and last < _FIRST_RACK_SLOT:
        return ()
    # The slot that the nozzle on the right extruder goes back to.
    home = _as_int(_device(report, "nozzle").get("tar_id"))
    mounted = nozzles.get(0)
    slots = []
    for place in range(_FIRST_RACK_SLOT, max(last + 1, _FIRST_RACK_SLOT + _RACK_SLOTS)):
        number = place - _FIRST_RACK_SLOT + 1
        if place in nozzles:
            slot = RackSlot(
                number=number, state=RackSlotState.DOCKED, nozzle=nozzles[place]
            )
        elif place == home and mounted is not None and mounted.serial is not None:
            slot = RackSlot(number=number, state=RackSlotState.MOUNTED, nozzle=mounted)
        else:
            slot = RackSlot(number=number)
        slots.append(slot)
    return tuple(slots)


def _ams_flags(unit: dict[str, Any]) -> int | None:
    """Return what an AMS reports about itself, which is a number as text."""
    info = unit.get("info")
    try:
        return int(info, 16) if isinstance(info, str) else None
    except ValueError:
        return None


def _ams(report: dict[str, Any], active: FilamentSource | None) -> tuple[Ams, ...]:
    """Return the AMS units of the printer."""
    ams = report.get("ams")
    result = []
    for unit in _entries(ams.get("ams") if isinstance(ams, dict) else None):
        if (ams_id := _as_int(unit.get("id"))) is None:
            continue
        drying = _as_int(unit.get("dry_time"))
        # The last digit holds the kind of the unit, the third to last holds
        # the extruder that it feeds.
        info = _ams_flags(unit)
        result.append(
            Ams(
                id=ams_id,
                model=None if info is None else _AMS_MODELS.get(info & 0xF),
                extruder=(
                    None if info is None else _EXTRUDER_POSITIONS.get(info >> 8 & 0xF)
                ),
                humidity_index=_in_range(_as_int(unit.get("humidity")), 1, 5),
                humidity=_in_range(_as_int(unit.get("humidity_raw")), 0, 100),
                temperature=_as_float(unit.get("temp")),
                drying_remaining_minutes=(
                    drying if drying is not None and drying >= 0 else None
                ),
                trays=tuple(
                    AmsTray(
                        id=tray_id,
                        filament=_filament(tray),
                        active=active == FilamentSource(ams_id=ams_id, tray_id=tray_id),
                    )
                    for tray in _entries(unit.get("tray"))
                    if (tray_id := _as_int(tray.get("id"))) is not None
                ),
            )
        )
    return tuple(result)


def _external_filament(tray: dict[str, Any]) -> Filament | None:
    """Return the filament of an external spool, or None if there is none."""
    filament = _filament(tray)
    tags = (_as_text(tray.get(key)) for key in ("tag_uid", "tray_uuid"))
    if filament is None or any(tag and tag.strip("0") for tag in tags):
        return filament
    # Without a tag, the printer reports that nothing remains.
    return replace(filament, remaining=None)


def _external_spools(
    report: dict[str, Any], active: FilamentSource | None
) -> tuple[ExternalSpool, ...]:
    """Return the external spools of the printer, the right one first."""
    filaments = {}
    if isinstance(slots := report.get("vir_slot"), list):
        for slot in _entries(slots):
            if (spool_id := _as_int(slot.get("id"))) in _EXTERNAL_SPOOLS:
                filaments[_EXTERNAL_SPOOLS[spool_id]] = _external_filament(slot)
    elif isinstance(tray := report.get("vt_tray"), dict):
        # Older firmware only knows of one external spool.
        filaments[ExtruderPosition.RIGHT] = _external_filament(tray)
    return tuple(
        ExternalSpool(
            extruder=position,
            filament=filaments[position],
            active=active == FilamentSource(external_spool=position),
        )
        for position in ExtruderPosition
        if position in filaments
    )


def _enabled(value: Any) -> bool | None:
    """Return whether something is enabled, the way a printer reports that."""
    return {"enable": True, "disable": False}.get(value) if value else None


def _camera_setting(report: dict[str, Any], setting: str) -> bool | None:
    """Return whether a setting of the camera is enabled."""
    ipcam = report.get("ipcam")
    return _enabled(ipcam.get(setting)) if isinstance(ipcam, dict) else None


def _available_firmware_version(report: dict[str, Any]) -> str | None:
    """Return the version of the firmware that the printer can update to."""
    upgrade = report.get("upgrade_state")
    if not isinstance(upgrade, dict):
        return None
    if (version := _as_text(upgrade.get("ota_new_version_number"))) is not None:
        return version
    # Some printers list the new versions of all their parts.
    versions = upgrade.get("new_ver_list")
    for part in versions if isinstance(versions, list) else []:
        if isinstance(part, dict) and part.get("name") == "ota":
            return _as_text(part.get("new_ver"))
    return None


def _stage(report: dict[str, Any], print_state: PrintState | None) -> PrintStage | None:
    """Return what the printer is doing right now."""
    stage = _as_int(report.get("stg_cur"))
    # A printer keeps the stage of a print job that failed, and reports
    # printing when it starts up. Neither is what it is doing.
    if print_state is PrintState.FAILED or (
        stage == 0 and report.get("print_type") == "idle"
    ):
        return PrintStage.IDLE
    return None if stage is None else STAGES.get(stage)


def _chamber_temperature(
    report: dict[str, Any], model: PrinterModel | None
) -> int | None:
    """Return the temperature of the chamber, if the printer measures it."""
    if model in _MODELS_WITHOUT_CHAMBER_SENSOR:
        return None
    if (temperature := _as_degrees(report.get("chamber_temper"))) is not None:
        return temperature
    # Newer firmware reports the chamber as a device. The low 16 bits hold
    # the current temperature, the high 16 bits hold the target.
    try:
        packed = report["device"]["ctc"]["info"]["temp"]
    except (KeyError, TypeError):
        return None
    if (value := _as_int(packed)) is None:
        return None
    return value & 0xFFFF


def _chamber_light_on(report: dict[str, Any]) -> bool | None:
    """Return whether the light in the chamber is on."""
    lights = report.get("lights_report")
    if not isinstance(lights, list):
        return None
    for light in lights:
        if isinstance(light, dict) and light.get("node") == _CHAMBER_LIGHT:
            return bool(light.get("mode") != "off")
    return None


def _accepts_commands(report: dict[str, Any]) -> bool:
    """Return whether the printer accepts commands that control it."""
    fun = report.get("fun")
    if isinstance(fun, str) and fun:
        try:
            return not int(fun, 16) & _FUN_SIGNATURE_REQUIRED
        except ValueError:
            return True
    # Some firmware reports this elsewhere.
    flag3 = _as_int(report.get("flag3"))
    return flag3 is None or not flag3 & _FLAG3_AUTHORIZATION_CONTROL


def _camera_stream_enabled(report: dict[str, Any]) -> bool | None:
    """Return whether the printer serves its video stream on the network."""
    ipcam = report.get("ipcam")
    if not isinstance(ipcam, dict) or "rtsp_url" not in ipcam:
        return None
    # The printer reports where the stream is, or that it is disabled.
    return str(ipcam["rtsp_url"]).startswith(("rtsp://", "rtsps://"))


def _print_state(report: dict[str, Any]) -> PrintState | None:
    """Return the state of the print job."""
    return _PRINT_STATES.get(str(report.get("gcode_state")).upper())


def _wifi_signal(report: dict[str, Any]) -> int | None:
    """Return the Wi-Fi signal strength in dBm."""
    signal = report.get("wifi_signal")
    if isinstance(signal, str):
        signal = signal.removesuffix("dBm")
    return _as_int(signal)


@dataclass(frozen=True, slots=True, kw_only=True)
class PrinterState:
    """What a printer is doing right now.

    A value is None when the printer does not report it. Temperatures are in
    whole degrees Celsius.

    Newer firmware only accepts commands when the printer is in developer
    mode. `accepts_commands` tells whether it does. The chamber light is the
    exception: a printer always accepts the command for it.

    `camera_stream_enabled` is None for a printer without a video stream. A
    printer that has one only serves it on the network when that is turned on
    on the printer.

    The speed of a fan is a percentage. `print_error` is the code of what went
    wrong with the print job, and `errors` are the problems the printer has.

    A printer has one or two extruders, each with its temperature and its
    nozzle. The nozzle rack has no slots on a printer without one.
    """

    print_state: PrintState | None = None
    job_name: str | None = None
    progress: int | None = None
    remaining_minutes: int | None = None
    current_layer: int | None = None
    total_layers: int | None = None
    bed_temperature: int | None = None
    bed_target_temperature: int | None = None
    chamber_temperature: int | None = None
    speed_profile: SpeedProfile | None = None
    chamber_light_on: bool | None = None
    wifi_signal: int | None = None
    accepts_commands: bool = True
    camera_stream_enabled: bool | None = None
    stage: PrintStage | None = None
    speed_percentage: int | None = None
    part_fan_speed: int | None = None
    aux_fan_speed: int | None = None
    chamber_fan_speed: int | None = None
    heatbreak_fan_speed: int | None = None
    print_error: str | None = None
    errors: tuple[PrinterError, ...] = ()
    extruders: tuple[Extruder, ...] = ()
    nozzle_rack: tuple[RackSlot, ...] = ()
    ams: tuple[Ams, ...] = ()
    external_spools: tuple[ExternalSpool, ...] = ()
    sd_card_present: bool | None = None
    timelapse_enabled: bool | None = None
    recording_enabled: bool | None = None
    available_firmware_version: str | None = None

    @classmethod
    def from_report(
        cls, report: dict[str, Any], model: PrinterModel | None = None
    ) -> Self:
        """Create the state from the status a printer reports."""
        speed_level = _as_int(report.get("spd_lvl"))
        print_state = _print_state(report)
        sd_card = report.get("sdcard")
        nozzles = _nozzles(report)
        extruders = _extruders(report, nozzles)
        # Where the extruder that prints takes its filament from.
        active = next(
            (extruder.filament_source for extruder in extruders if extruder.active),
            _legacy_filament_source(report) if not extruders else None,
        )
        return cls(
            print_state=print_state,
            job_name=_as_text(report.get("subtask_name")),
            progress=_as_int(report.get("mc_percent")),
            remaining_minutes=_as_int(report.get("mc_remaining_time")),
            current_layer=_as_int(report.get("layer_num")),
            total_layers=_as_int(report.get("total_layer_num")),
            bed_temperature=_as_degrees(report.get("bed_temper")),
            bed_target_temperature=_as_degrees(report.get("bed_target_temper")),
            chamber_temperature=_chamber_temperature(report, model),
            speed_profile=(
                None if speed_level is None else SPEED_PROFILES.get(speed_level)
            ),
            chamber_light_on=_chamber_light_on(report),
            wifi_signal=_wifi_signal(report),
            accepts_commands=_accepts_commands(report),
            camera_stream_enabled=_camera_stream_enabled(report),
            stage=_stage(report, print_state),
            speed_percentage=_as_int(report.get("spd_mag")),
            part_fan_speed=_fan_speed(report.get("cooling_fan_speed")),
            aux_fan_speed=_fan_speed(report.get("big_fan1_speed")),
            chamber_fan_speed=_fan_speed(report.get("big_fan2_speed")),
            heatbreak_fan_speed=_fan_speed(report.get("heatbreak_fan_speed")),
            print_error=_print_error(report),
            errors=_errors(report),
            extruders=extruders,
            nozzle_rack=_nozzle_rack(report, nozzles),
            ams=_ams(report, active),
            external_spools=_external_spools(report, active),
            sd_card_present=sd_card if isinstance(sd_card, bool) else None,
            timelapse_enabled=_camera_setting(report, "timelapse"),
            recording_enabled=_camera_setting(report, "ipcam_record"),
            available_firmware_version=_available_firmware_version(report),
        )
