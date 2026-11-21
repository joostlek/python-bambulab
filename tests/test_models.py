"""Tests for the models of aiobambulab."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from aiobambulab import (
    Ams,
    AmsInfo,
    AmsModel,
    AmsTray,
    ErrorSeverity,
    ExternalSpool,
    Extruder,
    ExtruderPosition,
    Filament,
    FilamentSource,
    Nozzle,
    PrinterError,
    PrinterInfo,
    PrinterModel,
    PrinterState,
    PrintStage,
    PrintState,
    RackSlot,
    RackSlotState,
    SpeedProfile,
)

from .conftest import SERIAL, load_fixture


def _report(name: str) -> dict[str, Any]:
    report: dict[str, Any] = load_fixture(name)["print"]
    return report


def _info(name: str) -> PrinterInfo:
    return PrinterInfo.from_modules(SERIAL, load_fixture(name)["info"]["module"])


def test_state_of_an_idle_printer() -> None:
    """A printer with a chamber sensor reports everything."""
    assert PrinterState.from_report(
        _report("x1c_status.json"), PrinterModel.X1C
    ) == PrinterState(
        print_state=PrintState.IDLE,
        job_name=None,
        progress=0,
        remaining_minutes=0,
        current_layer=0,
        total_layers=0,
        bed_temperature=24,
        bed_target_temperature=0,
        chamber_temperature=26,
        speed_profile=SpeedProfile.STANDARD,
        chamber_light_on=True,
        wifi_signal=-45,
        stage=PrintStage.IDLE,
        speed_percentage=100,
        extruders=(
            Extruder(
                position=ExtruderPosition.RIGHT,
                temperature=25,
                target_temperature=0,
                active=True,
                nozzle=Nozzle(diameter=0.4),
            ),
        ),
    )


def test_state_of_a_printer_without_chamber_sensor() -> None:
    """A P1S reports a chamber temperature that it does not measure."""
    assert PrinterState.from_report(
        _report("p1s_status.json"), PrinterModel.P1S
    ) == PrinterState(
        print_state=PrintState.PRINTING,
        job_name="Benchy",
        progress=42,
        remaining_minutes=73,
        current_layer=96,
        total_layers=240,
        # The printer reports 59.6875.
        bed_temperature=60,
        bed_target_temperature=60,
        chamber_temperature=None,
        speed_profile=SpeedProfile.SPORT,
        chamber_light_on=False,
        wifi_signal=-58,
        stage=PrintStage.PRINTING,
        speed_percentage=124,
        extruders=(
            Extruder(
                position=ExtruderPosition.RIGHT,
                # The printer reports 219.90625.
                temperature=220,
                target_temperature=220,
                active=True,
                nozzle=Nozzle(diameter=0.4, type="stainless_steel"),
            ),
        ),
    )


def test_state_of_a_printer_that_reports_the_chamber_as_a_device() -> None:
    """Newer firmware packs the chamber temperature and its target together."""
    state = PrinterState.from_report(_report("h2d_status.json"), PrinterModel.H2D)

    assert state.print_state is PrintState.PAUSED
    assert state.chamber_temperature == 35
    assert state.chamber_light_on is True


def test_state_without_a_known_model_keeps_the_chamber_temperature() -> None:
    """Only a known model is known to have no chamber sensor."""
    state = PrinterState.from_report(_report("p1s_status.json"))

    assert state.chamber_temperature == 5


def test_state_of_an_empty_report() -> None:
    """Nothing is known when the printer reports nothing."""
    assert PrinterState.from_report({}) == PrinterState()


@pytest.mark.parametrize(
    "report",
    [
        {"gcode_state": "DANCING"},
        {"gcode_state": "OFFLINE"},
        {"gcode_state": None},
        {"subtask_name": 5},
        {"subtask_name": "   "},
        {"mc_percent": "many"},
        {"mc_percent": True},
        {"mc_percent": float("nan")},
        {"mc_percent": "nan"},
        {"mc_remaining_time": float("inf")},
        {"nozzle_temper": float("-inf")},
        {"mc_remaining_time": None},
        {"nozzle_temper": [1]},
        {"spd_lvl": 9},
        {"spd_lvl": "fast"},
        {"wifi_signal": "strong"},
        {"wifi_signal": None},
        {"lights_report": "on"},
        {"lights_report": ["on", {"node": "work_light", "mode": "on"}]},
        {"device": None},
        {"device": {"ctc": None}},
        {"device": {"ctc": {"info": {}}}},
        {"device": {"ctc": {"info": {"temp": "warm"}}}},
    ],
)
def test_state_ignores_values_it_does_not_understand(report: dict[str, Any]) -> None:
    """A value of an unexpected type or meaning is not known."""
    assert PrinterState.from_report(report) == PrinterState()


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        ({"mc_percent": "37"}, PrinterState(progress=37)),
        ({"mc_percent": 37.9}, PrinterState(progress=37)),
        ({"wifi_signal": -61}, PrinterState(wifi_signal=-61)),
        ({"bed_temper": "60.6"}, PrinterState(bed_temperature=61)),
        ({"bed_temper": 59.4}, PrinterState(bed_temperature=59)),
        ({"gcode_state": "finish"}, PrinterState(print_state=PrintState.FINISHED)),
        (
            {"lights_report": [{"node": "chamber_light", "mode": "flashing"}]},
            PrinterState(chamber_light_on=True),
        ),
    ],
)
def test_state_accepts_values_in_other_notations(
    report: dict[str, Any], expected: PrinterState
) -> None:
    """Printers do not agree on numbers as text, or on capitals."""
    assert PrinterState.from_report(report) == expected


def test_info_of_a_printer_that_reports_its_product_name() -> None:
    """Newer firmware reports the name of the product."""
    assert _info("p1s_version.json") == PrinterInfo(
        serial=SERIAL,
        model=PrinterModel.P1S,
        model_name="P1S",
        firmware_version="01.08.02.00",
        hardware_version="AP04",
    )


def test_info_of_a_printer_without_a_mainboard_module() -> None:
    """Not every printer reports a mainboard."""
    assert _info("h2d_version.json") == PrinterInfo(
        serial=SERIAL,
        model=PrinterModel.H2D,
        model_name="H2D",
        firmware_version="01.01.01.00",
        hardware_version=None,
        ams=(
            AmsInfo(
                id=0,
                model=AmsModel.AMS_2_PRO,
                serial="19C00A000000001",
                firmware_version="02.00.19.47",
                hardware_version="N3F05",
            ),
        ),
    )


def test_info_of_a_printer_with_older_firmware() -> None:
    """Older firmware only reports its hardware, which tells the model."""
    assert _info("x1c_version.json") == PrinterInfo(
        serial=SERIAL,
        model=PrinterModel.X1C,
        model_name="X1 Carbon",
        firmware_version="01.07.00.00",
        hardware_version="AP05",
    )


@pytest.mark.parametrize(
    ("hardware_version", "project_name", "model"),
    [
        ("AP02", "", PrinterModel.X1E),
        ("AP04", "C11", PrinterModel.P1P),
        ("AP04", "C12", PrinterModel.P1S),
        ("AP04", "N1", PrinterModel.A1_MINI),
        ("AP05", "N1", PrinterModel.A1_MINI),
        ("AP05", "N2S", PrinterModel.A1),
        ("AP05", "", PrinterModel.X1C),
        ("AP09", "", None),
    ],
)
def test_info_tells_the_model_from_the_hardware(
    hardware_version: str, project_name: str, model: PrinterModel | None
) -> None:
    """The mainboard and the project name tell which printer it is."""
    info = PrinterInfo.from_modules(
        SERIAL,
        [
            {"name": "ota", "sw_ver": "01.04.00.00", "hw_ver": "OTA"},
            {
                "name": "esp32",
                "project_name": project_name,
                "sw_ver": "01.07.23.47",
                "hw_ver": hardware_version,
            },
        ],
    )

    assert info.model is model
    assert info.model_name == (model.value if model else None)
    assert info.hardware_version == hardware_version


@pytest.mark.parametrize(
    ("product_name", "model", "model_name"),
    [
        ("Bambu Lab A1 mini", PrinterModel.A1_MINI, "A1 mini"),
        ("Bambu Lab H2D Pro", PrinterModel.H2D_PRO, "H2D Pro"),
        ("Bambu Lab X1-Carbon", PrinterModel.X1C, "X1 Carbon"),
        ("Bambu Lab Z9", None, "Z9"),
        ("Something else", None, "Something else"),
    ],
)
def test_info_tells_the_model_from_the_product_name(
    product_name: str, model: PrinterModel | None, model_name: str
) -> None:
    """A printer this library does not know yet keeps the name it reports."""
    info = PrinterInfo.from_modules(
        SERIAL, [{"name": "ota", "sw_ver": "01.00.00.00", "product_name": product_name}]
    )

    assert info.model is model
    assert info.model_name == model_name


@pytest.mark.parametrize("modules", [None, "ota", [], ["ota", 5], [{"name": "mc"}]])
def test_info_without_usable_modules(modules: Any) -> None:
    """Nothing is known about a printer that reports no usable modules."""
    assert PrinterInfo.from_modules(SERIAL, modules) == PrinterInfo(serial=SERIAL)


@pytest.mark.parametrize(
    ("reported", "state"),
    [
        ("IDLE", PrintState.IDLE),
        ("INIT", PrintState.INITIALIZING),
        ("SLICING", PrintState.SLICING),
        ("PREPARE", PrintState.PREPARING),
        ("RUNNING", PrintState.PRINTING),
        ("PAUSE", PrintState.PAUSED),
        ("FINISH", PrintState.FINISHED),
        ("FAILED", PrintState.FAILED),
    ],
)
def test_print_states(reported: str, state: PrintState) -> None:
    """Every state of a print job has a name that says what it is."""
    assert PrinterState.from_report({"gcode_state": reported}).print_state is state


@pytest.mark.parametrize(
    ("report", "accepts_commands"),
    [
        ({}, True),
        # Developer mode is on, and off.
        ({"fun": "3EC18FFF9CFF"}, True),
        ({"fun": "3EC1AFFF9CFF"}, False),
        # What "fun" tells counts, when the printer reports it.
        ({"fun": "3EC18FFF9CFF", "flag3": 671}, True),
        ({"fun": "", "flag3": 671}, False),
        ({"fun": "", "flag3": 15}, True),
        ({"flag3": 31}, False),
        ({"fun": "no number", "flag3": 31}, True),
        ({"fun": 5, "flag3": "no number"}, True),
    ],
)
def test_accepts_commands(report: dict[str, Any], accepts_commands: bool) -> None:  # noqa: FBT001
    """Newer firmware tells when it only accepts commands in developer mode."""
    assert PrinterState.from_report(report).accepts_commands is accepts_commands


@pytest.mark.parametrize(
    ("report", "stage"),
    [
        ({"gcode_state": "RUNNING", "stg_cur": 0}, PrintStage.PRINTING),
        ({"gcode_state": "RUNNING", "stg_cur": 1}, PrintStage.AUTO_BED_LEVELING),
        ({"gcode_state": "PAUSE", "stg_cur": 6}, PrintStage.PAUSED_FILAMENT_RUNOUT),
        ({"gcode_state": "RUNNING", "stg_cur": "14"}, PrintStage.CLEANING_NOZZLE_TIP),
        ({"gcode_state": "IDLE", "stg_cur": -1}, PrintStage.IDLE),
        ({"gcode_state": "FINISH", "stg_cur": 255}, PrintStage.IDLE),
        # A printer that starts up reports that it prints.
        ({"gcode_state": "IDLE", "stg_cur": 0, "print_type": "idle"}, PrintStage.IDLE),
        # A printer keeps the stage of a print job that failed.
        ({"gcode_state": "FAILED", "stg_cur": 4}, PrintStage.IDLE),
        ({"gcode_state": "RUNNING", "stg_cur": 9999}, None),
        ({"gcode_state": "RUNNING"}, None),
        ({"gcode_state": "RUNNING", "stg_cur": "soon"}, None),
    ],
)
def test_stage(report: dict[str, Any], stage: PrintStage | None) -> None:
    """The stage tells what the printer is doing right now."""
    assert PrinterState.from_report(report).stage is stage


@pytest.mark.parametrize(
    ("level", "percentage"),
    [
        ("0", 0),
        ("1", 10),
        ("2", 20),
        ("3", 20),
        ("7", 50),
        ("8", 60),
        (14, 100),
        ("15", 100),
        ("16", None),
        ("-1", None),
        ("fast", None),
        (None, None),
    ],
)
def test_fan_speed(level: Any, percentage: int | None) -> None:
    """The speed of a fan is a percentage, in the steps it is set in."""
    state = PrinterState.from_report(
        {
            "cooling_fan_speed": level,
            "big_fan1_speed": level,
            "big_fan2_speed": level,
            "heatbreak_fan_speed": level,
        }
    )

    assert state.part_fan_speed == percentage
    assert state.aux_fan_speed == percentage
    assert state.chamber_fan_speed == percentage
    assert state.heatbreak_fan_speed == percentage


@pytest.mark.parametrize(
    ("report", "print_error"),
    [
        ({"print_error": 117473286}, "0700_8006"),
        ({"print_error": "83886107"}, "0500_001B"),
        ({"print_error": 0}, None),
        ({"print_error": -5}, None),
        ({"print_error": "broken"}, None),
        ({}, None),
    ],
)
def test_print_error(report: dict[str, Any], print_error: str | None) -> None:
    """The error of a print job is the code to look up at Bambu Lab."""
    assert PrinterState.from_report(report).print_error == print_error


def test_errors() -> None:
    """The problems of a printer have a code to look up, and a severity."""
    state = PrinterState.from_report(
        {
            "hms": [
                {"attr": 50331904, "code": 65543},
                {"attr": 117440768, "code": 131078},
                {"attr": 201327360, "code": 196609},
                {"attr": 83886336, "code": 262146},
                {"attr": 83886336, "code": 589825},
                # Not a problem, or not one that can be read.
                {"attr": 0, "code": 0},
                {"attr": -1, "code": 5},
                {"attr": "many", "code": 5},
                {"code": 5},
                "broken",
            ]
        }
    )

    assert state.errors == (
        PrinterError(code="0300_0100_0001_0007", severity=ErrorSeverity.FATAL),
        PrinterError(code="0700_0100_0002_0006", severity=ErrorSeverity.SERIOUS),
        PrinterError(code="0C00_0300_0003_0001", severity=ErrorSeverity.COMMON),
        PrinterError(code="0500_0100_0004_0002", severity=ErrorSeverity.INFO),
        PrinterError(code="0500_0100_0009_0001", severity=None),
    )


@pytest.mark.parametrize("hms", [None, "none", {"attr": 1, "code": 1}, []])
def test_no_errors(hms: Any) -> None:
    """A printer without problems has no errors."""
    assert PrinterState.from_report({"hms": hms}).errors == ()  # pylint: disable=use-implicit-booleaness-not-comparison


AMS_REPORT: dict[str, Any] = {
    "ams": {
        "ams": [
            {
                "id": "0",
                "humidity": "4",
                "humidity_raw": "23",
                "temp": "24.5",
                "tray": [
                    {"id": "0"},
                    {
                        "id": "1",
                        "tray_type": "PLA",
                        "tray_sub_brands": "PLA Basic",
                        "tray_color": "f95959ff",
                        "tray_info_idx": "GFA00",
                        "remain": 80,
                        "nozzle_temp_min": "190",
                        "nozzle_temp_max": "240",
                    },
                    {
                        "id": "2",
                        "tray_type": "PETG",
                        "tray_sub_brands": "",
                        "tray_color": "not a color",
                        "tray_info_idx": "GFG99",
                        "remain": -1,
                        "nozzle_temp_min": "0",
                        "nozzle_temp_max": "0",
                    },
                    {"id": "3", "tray_type": "", "tray_info_idx": "GFL99"},
                    {"tray_type": "PLA"},
                    "broken",
                ],
            },
            {"id": "1", "humidity": "9", "humidity_raw": "150", "temp": "warm"},
            {"humidity": "3"},
            "broken",
        ],
        "tray_now": "1",
    },
    "vt_tray": {
        "id": "254",
        "tray_type": "TPU",
        "tray_color": "00112233",
        "remain": 0,
    },
}


def test_ams() -> None:
    """The printer tells about its AMS units, and the filament in their trays."""
    state = PrinterState.from_report(AMS_REPORT)

    assert state.ams == (
        Ams(
            id=0,
            humidity_index=4,
            humidity=23,
            temperature=24.5,
            trays=(
                AmsTray(id=0),
                AmsTray(
                    id=1,
                    filament=Filament(
                        type="PLA",
                        name="PLA Basic",
                        color="F95959FF",
                        remaining=80,
                        nozzle_temperature_min=190,
                        nozzle_temperature_max=240,
                    ),
                    active=True,
                ),
                AmsTray(id=2, filament=Filament(type="PETG")),
                AmsTray(id=3, filament=Filament()),
            ),
        ),
        Ams(id=1),
    )
    assert state.external_spools == (
        ExternalSpool(
            extruder=ExtruderPosition.RIGHT,
            # Nothing tells what remains of a spool without a tag.
            filament=Filament(type="TPU", color="00112233"),
        ),
    )


@pytest.mark.parametrize(
    ("tray_now", "active", "external_spool_active"),
    [
        ("0", {(0, 0)}, False),
        ("3", {(0, 3)}, False),
        ("4", {(1, 0)}, False),
        ("6", {(1, 2)}, False),
        ("128", {(128, 0)}, False),
        ("254", set(), True),
        ("255", set(), False),
        ("none", set(), False),
        (None, set(), False),
    ],
)
def test_active_tray(
    tray_now: Any,
    active: set[tuple[int, int]],
    external_spool_active: bool,  # noqa: FBT001
) -> None:
    """The printer tells which tray it prints from."""
    trays = [{"id": str(tray), "tray_type": "PLA"} for tray in range(4)]
    state = PrinterState.from_report(
        {
            "ams": {
                "ams": [
                    {"id": "0", "tray": trays},
                    {"id": "1", "tray": trays},
                    {"id": "128", "tray": trays[:1]},
                ],
                "tray_now": tray_now,
            },
            "vt_tray": {"id": "254", "tray_type": "PLA"},
        }
    )

    assert {
        (unit.id, tray.id) for unit in state.ams for tray in unit.trays if tray.active
    } == active
    assert [spool.active for spool in state.external_spools] == [external_spool_active]


@pytest.mark.parametrize(
    "report",
    [{}, {"ams": None}, {"ams": {}}, {"ams": {"ams": "none"}}, {"vt_tray": "none"}],
)
def test_no_ams(report: dict[str, Any]) -> None:
    """A printer without an AMS has none."""
    state = PrinterState.from_report(report)

    assert state.ams == ()  # pylint: disable=use-implicit-booleaness-not-comparison
    assert state.external_spools == ()  # pylint: disable=use-implicit-booleaness-not-comparison


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (
            {"ipcam": {"timelapse": "enable", "ipcam_record": "disable"}},
            PrinterState(timelapse_enabled=True, recording_enabled=False),
        ),
        ({"ipcam": {"timelapse": "sometimes", "ipcam_record": ""}}, PrinterState()),
        ({"ipcam": "none"}, PrinterState()),
        ({"sdcard": True}, PrinterState(sd_card_present=True)),
        ({"sdcard": False}, PrinterState(sd_card_present=False)),
        ({"sdcard": "yes"}, PrinterState()),
        ({"spd_mag": 124}, PrinterState(speed_percentage=124)),
        ({"nozzle_diameter": "0"}, PrinterState()),
        (
            {"upgrade_state": {"ota_new_version_number": "01.09.00.00"}},
            PrinterState(available_firmware_version="01.09.00.00"),
        ),
        (
            {
                "upgrade_state": {
                    "ota_new_version_number": "",
                    "new_ver_list": [
                        "broken",
                        {"name": "ams/0", "new_ver": "00.00.06.49"},
                        {
                            "name": "ota",
                            "cur_ver": "01.06.01.02",
                            "new_ver": "01.07.00.00",
                        },
                    ],
                }
            },
            PrinterState(available_firmware_version="01.07.00.00"),
        ),
        (
            {"upgrade_state": {"new_ver_list": [{"name": "ams/0", "new_ver": "1"}]}},
            PrinterState(),
        ),
        ({"upgrade_state": {"new_ver_list": "none"}}, PrinterState()),
        ({"upgrade_state": "idle"}, PrinterState()),
    ],
)
def test_other_values(report: dict[str, Any], expected: PrinterState) -> None:
    """The printer tells about its camera, its storage, its nozzle, and updates."""
    assert PrinterState.from_report(report) == expected


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ("f95959ff", "F95959FF"),
        ("nothexxx", None),
        ("FFF", None),
        (12345678, None),
        (None, None),
    ],
)
def test_filament_color(color: Any, expected: str | None) -> None:
    """The color of a filament is one, or it is not known."""
    state = PrinterState.from_report(
        {"vt_tray": {"tray_type": "PLA", "tray_color": color}}
    )

    assert state.external_spools[0].filament == Filament(type="PLA", color=expected)


H2C_NOZZLE = Nozzle(
    diameter=0.4,
    type="HS01",
    serial="20D00A000000001",
    print_time=timedelta(seconds=257323),
)


def _rack_nozzle(number: int, seconds: int) -> Nozzle:
    return Nozzle(
        diameter=0.4,
        type="HS01",
        serial=f"20D00A00000000{number}",
        print_time=timedelta(seconds=seconds),
    )


def test_extruders_of_a_printer_with_a_nozzle_rack() -> None:
    """An H2C has two extruders, and a rack with the nozzles of the right one."""
    state = PrinterState.from_report(_report("h2c_status.json"), PrinterModel.H2C)

    assert state.extruders == (
        Extruder(
            position=ExtruderPosition.RIGHT,
            temperature=27,
            target_temperature=0,
            active=True,
            nozzle=H2C_NOZZLE,
        ),
        Extruder(
            position=ExtruderPosition.LEFT,
            temperature=23,
            target_temperature=0,
            # The nozzle of the left extruder stays where it is.
            nozzle=Nozzle(diameter=0.4, type="HS01"),
        ),
    )
    assert state.nozzle_rack == (
        RackSlot(number=1, state=RackSlotState.DOCKED, nozzle=_rack_nozzle(3, 499837)),
        RackSlot(number=2, state=RackSlotState.DOCKED, nozzle=_rack_nozzle(6, 77918)),
        RackSlot(number=3, state=RackSlotState.DOCKED, nozzle=_rack_nozzle(2, 249280)),
        RackSlot(number=4, state=RackSlotState.DOCKED, nozzle=_rack_nozzle(5, 149157)),
        RackSlot(number=5, state=RackSlotState.DOCKED, nozzle=_rack_nozzle(4, 40696)),
        RackSlot(number=6, state=RackSlotState.MOUNTED, nozzle=H2C_NOZZLE),
    )
    assert state.external_spools == (
        ExternalSpool(extruder=ExtruderPosition.RIGHT),
        ExternalSpool(extruder=ExtruderPosition.LEFT),
    )
    # Each unit can feed both extruders, through the filament switch.
    assert [
        (unit.id, unit.model, unit.extruder, len(unit.trays)) for unit in state.ams
    ] == [
        (0, AmsModel.AMS_2_PRO, None, 4),
        (1, AmsModel.AMS_2_PRO, None, 4),
        (128, AmsModel.AMS_HT, None, 1),
    ]


def test_extruder_of_a_printer_without_a_nozzle_rack() -> None:
    """A P2S reports its one extruder the way a printer with two does."""
    state = PrinterState.from_report(_report("p2s_status.json"), PrinterModel.P2S)
    filament = Filament(
        type="PLA",
        color="FFFFFFFF",
        nozzle_temperature_min=190,
        nozzle_temperature_max=240,
    )

    assert state.extruders == (
        Extruder(
            position=ExtruderPosition.RIGHT,
            temperature=15,
            target_temperature=0,
            active=True,
            nozzle=Nozzle(diameter=0.4, type="HS01"),
        ),
    )
    assert state.nozzle_rack == ()  # pylint: disable=use-implicit-booleaness-not-comparison
    assert state.external_spools == (
        ExternalSpool(extruder=ExtruderPosition.RIGHT, filament=filament),
    )
    assert [(unit.model, unit.extruder) for unit in state.ams] == [
        (AmsModel.AMS_2_PRO, ExtruderPosition.RIGHT)
    ]


def test_extruders_that_only_report_their_temperature() -> None:
    """The temperature of an extruder and its target come as one number."""
    state = PrinterState.from_report(_report("h2d_status.json"), PrinterModel.H2D)

    assert state.extruders == (
        Extruder(
            position=ExtruderPosition.RIGHT,
            temperature=245,
            target_temperature=245,
            active=True,
        ),
        Extruder(position=ExtruderPosition.LEFT, temperature=47, target_temperature=0),
    )
    assert state.nozzle_rack == ()  # pylint: disable=use-implicit-booleaness-not-comparison


@pytest.mark.parametrize(
    ("report", "extruders"),
    [
        (
            {"nozzle_temper": 219.9, "nozzle_target_temper": 220},
            (
                Extruder(
                    position=ExtruderPosition.RIGHT,
                    temperature=220,
                    target_temperature=220,
                    active=True,
                ),
            ),
        ),
        (
            {"nozzle_diameter": "0.6", "nozzle_type": "hardened_steel"},
            (
                Extruder(
                    position=ExtruderPosition.RIGHT,
                    active=True,
                    nozzle=Nozzle(diameter=0.6, type="hardened_steel"),
                ),
            ),
        ),
        (
            {"nozzle_temper": 30, "ams": {"tray_now": "6"}},
            (
                Extruder(
                    position=ExtruderPosition.RIGHT,
                    temperature=30,
                    active=True,
                    filament_source=FilamentSource(ams_id=1, tray_id=2),
                ),
            ),
        ),
        (
            {"nozzle_temper": 30, "ams": {"tray_now": "254"}},
            (
                Extruder(
                    position=ExtruderPosition.RIGHT,
                    temperature=30,
                    active=True,
                    filament_source=FilamentSource(
                        external_spool=ExtruderPosition.RIGHT
                    ),
                ),
            ),
        ),
        ({"nozzle_temper": "hot", "device": {"extruder": {"info": "none"}}}, ()),
        ({"device": {"extruder": {"info": [{"id": 7, "temp": 20}, "broken"]}}}, ()),
        (
            {"device": {"extruder": {"info": [{"id": 0, "temp": -1}], "state": "?"}}},
            (Extruder(position=ExtruderPosition.RIGHT, active=True),),
        ),
    ],
)
def test_extruder_of_a_printer_that_only_reports_its_nozzle(
    report: dict[str, Any], extruders: tuple[Extruder, ...]
) -> None:
    """A printer that does not report its extruders has one."""
    assert PrinterState.from_report(report).extruders == extruders


@pytest.mark.parametrize(
    ("state", "active"),
    [
        (0x02, [True, False]),
        (0x12, [False, True]),
        # The printer switches from one extruder to the other.
        (0xF2, [False, False]),
    ],
)
def test_active_extruder(state: int, active: list[bool]) -> None:
    """The printer tells which extruder prints."""
    report = {"device": {"extruder": {"info": [{"id": 1}, {"id": 0}], "state": state}}}

    extruders = PrinterState.from_report(report).extruders

    assert [extruder.position for extruder in extruders] == list(ExtruderPosition)
    assert [extruder.active for extruder in extruders] == active


@pytest.mark.parametrize(
    ("snow", "source"),
    [
        (0x0103, FilamentSource(ams_id=1, tray_id=3)),
        (0x8000, FilamentSource(ams_id=128, tray_id=0)),
        (0xFF00, FilamentSource(external_spool=ExtruderPosition.RIGHT)),
        (0xFE00, FilamentSource(external_spool=ExtruderPosition.LEFT)),
        (0xFFFF, None),
        (0xFEFF, None),
        (-1, None),
        ("loaded", None),
    ],
)
def test_filament_source(snow: Any, source: FilamentSource | None) -> None:
    """An extruder tells where its filament comes from."""
    state = PrinterState.from_report(
        {"device": {"extruder": {"info": [{"id": 0, "snow": snow}], "state": 1}}}
    )

    assert state.extruders[0].filament_source == source


def test_active_tray_of_a_printer_with_two_extruders() -> None:
    """The active tray is the one of the extruder that prints."""
    trays = [{"id": str(tray), "tray_type": "PLA"} for tray in range(4)]
    state = PrinterState.from_report(
        {
            "ams": {
                "ams": [{"id": "0", "tray": trays}, {"id": "1", "tray": trays}],
                # Not what a printer that reports its extruders prints from.
                "tray_now": "0",
            },
            "device": {
                "extruder": {
                    "info": [{"id": 0, "snow": 0x0002}, {"id": 1, "snow": 0x0103}],
                    "state": 0x12,
                }
            },
        }
    )

    assert {
        (unit.id, tray.id) for unit in state.ams for tray in unit.trays if tray.active
    } == {(1, 3)}


def test_active_external_spool() -> None:
    """An external spool is active when its extruder prints from it."""
    state = PrinterState.from_report(
        {
            "vir_slot": [
                {"id": "254", "tray_type": "PETG"},
                {"id": "255", "tray_type": "PLA"},
                {"id": "7", "tray_type": "ABS"},
                "broken",
            ],
            "device": {
                "extruder": {
                    "info": [{"id": 0, "snow": 0x0002}, {"id": 1, "snow": 0xFE00}],
                    "state": 0x12,
                }
            },
        }
    )

    assert state.external_spools == (
        ExternalSpool(extruder=ExtruderPosition.RIGHT, filament=Filament(type="PLA")),
        ExternalSpool(
            extruder=ExtruderPosition.LEFT, filament=Filament(type="PETG"), active=True
        ),
    )


def _rack_report(nozzle: Any, holder: Any = None) -> dict[str, Any]:
    return {"device": {"holder": holder, "nozzle": nozzle}}


@pytest.mark.parametrize(
    ("report", "states"),
    [
        (
            # The nozzle of slot 2 is on the extruder, slot 3 lost its nozzle.
            _rack_report(
                {
                    "exist": 0b1_0001_0000_0000_0000_0001,
                    "info": [
                        {"id": 0, "sn": "A"},
                        {"id": 16, "sn": "B"},
                        {"id": 18, "sn": "C"},
                        {"id": 20, "sn": "D"},
                        {"id": -1},
                        {"id": "x"},
                        "broken",
                    ],
                    "tar_id": 17,
                }
            ),
            ["docked", "mounted", "empty", "empty", "docked", "empty"],
        ),
        (
            # The slot the nozzle goes back to is only known with that nozzle.
            _rack_report({"exist": 0, "info": [], "tar_id": 17}, {"pos": 3}),
            ["empty"] * 6,
        ),
        (
            # A fixed nozzle does not come from the rack.
            _rack_report({"info": [{"id": 0, "sn": "N/A"}], "tar_id": 16}, {}),
            ["empty"] * 6,
        ),
        (
            _rack_report({"info": [{"id": 24, "sn": "B"}]}),
            ["empty"] * 8 + ["docked"],
        ),
        (
            # A printer with nine tools tells where each one belongs. That is
            # not read: the slot of the tool on the toolhead shows as empty.
            _rack_report(
                {
                    "exist": 0b1_1111_0111_0000_0000_0000_0001,
                    "info": [
                        {"id": 0, "addr_id": 3, "sn": "D"},
                        *(
                            {"id": 16 + slot, "addr_id": slot, "sn": "T"}
                            for slot in (0, 1, 2, 4, 5, 6, 7, 8)
                        ),
                    ],
                }
            ),
            ["docked"] * 3 + ["empty"] + ["docked"] * 5,
        ),
        (_rack_report({"exist": 1, "info": [{"id": 0}], "tar_id": 0}), []),
        (_rack_report("none"), []),
        ({"device": {"nozzle": {"info": "none"}}}, []),
    ],
)
def test_nozzle_rack(report: dict[str, Any], states: list[str]) -> None:
    """A slot of the rack holds its nozzle, lent it to the extruder, or is empty."""
    rack = PrinterState.from_report(report).nozzle_rack

    assert [slot.number for slot in rack] == list(range(1, len(states) + 1))
    assert [slot.state for slot in rack] == states
    assert all((slot.nozzle is None) == (slot.state == "empty") for slot in rack)


@pytest.mark.parametrize(
    ("entry", "nozzle"),
    [
        (
            {"diameter": 0.6, "type": "HH01", "sn": "20D00A000000009", "p_t": 90},
            Nozzle(
                diameter=0.6,
                type="HH01",
                serial="20D00A000000009",
                print_time=timedelta(seconds=90),
            ),
        ),
        (
            {"sn": "20D00A000000009", "p_t": 0},
            Nozzle(serial="20D00A000000009", print_time=timedelta()),
        ),
        ({"sn": "20D00A000000009", "p_t": -1}, Nozzle(serial="20D00A000000009")),
        ({"diameter": 0, "type": "", "sn": "N/A", "p_t": 0}, Nozzle()),
        ({"sn": "N/A", "p_t": 500}, Nozzle()),
    ],
)
def test_nozzle(entry: dict[str, Any], nozzle: Nozzle) -> None:
    """Only a nozzle with a serial number has a time that it printed for."""
    state = PrinterState.from_report(
        {
            "device": {
                "extruder": {"info": [{"id": 0, "hnow": 0}], "state": 1},
                "nozzle": {"exist": 1, "info": [{"id": 0, **entry}]},
            }
        }
    )

    assert state.extruders[0].nozzle == nozzle


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ({"info": "10001E03"}, Ams(id=0, model=AmsModel.AMS_2_PRO)),
        ({"info": "11002E04"}, Ams(id=0, model=AmsModel.AMS_HT)),
        (
            {"info": "1001"},
            Ams(id=0, model=AmsModel.AMS, extruder=ExtruderPosition.RIGHT),
        ),
        (
            {"info": "2102"},
            Ams(id=0, model=AmsModel.AMS_LITE, extruder=ExtruderPosition.LEFT),
        ),
        ({"info": "1E09"}, Ams(id=0)),
        ({"info": "none"}, Ams(id=0)),
        ({"info": 3}, Ams(id=0)),
        ({"dry_time": 90}, Ams(id=0, drying_remaining_minutes=90)),
        ({"dry_time": 0}, Ams(id=0, drying_remaining_minutes=0)),
        ({"dry_time": -1}, Ams(id=0)),
    ],
)
def test_ams_kind_and_drying(unit: dict[str, Any], expected: Ams) -> None:
    """An AMS tells its kind, its extruder, and how long it still dries filament."""
    state = PrinterState.from_report({"ams": {"ams": [{"id": "0", **unit}]}})

    assert state.ams == (expected,)


def test_info_of_the_ams_units() -> None:
    """The printer reports each AMS as a module, with a name that tells its kind."""
    info = PrinterInfo.from_modules(
        SERIAL,
        [
            {"name": "n3s/128", "sw_ver": "03.00.00.10", "hw_ver": "N3S05", "sn": "B"},
            {"name": "ams_f1/1", "sw_ver": "", "hw_ver": "AMS_F102", "sn": ""},
            {"name": "ams/0", "sw_ver": "00.00.06.49", "hw_ver": "AMS08", "sn": "A"},
            {"name": "ams/first"},
            {"name": "mc", "sn": "C"},
            {"sn": "D"},
        ],
    )

    assert info.ams == (
        AmsInfo(
            id=0,
            model=AmsModel.AMS,
            serial="A",
            firmware_version="00.00.06.49",
            hardware_version="AMS08",
        ),
        AmsInfo(id=1, model=AmsModel.AMS_LITE, hardware_version="AMS_F102"),
        AmsInfo(
            id=128,
            model=AmsModel.AMS_HT,
            serial="B",
            firmware_version="03.00.00.10",
            hardware_version="N3S05",
        ),
    )


@pytest.mark.parametrize(
    ("tray", "remaining"),
    [
        ({"remain": 0}, None),
        ({"remain": 0, "tag_uid": "0000000000000000", "tray_uuid": "00"}, None),
        ({"remain": 40, "tag_uid": "A1B2C3D400000100"}, 40),
        ({"remain": 40, "tray_uuid": "00000000000000000000000000000001"}, 40),
    ],
)
@pytest.mark.parametrize("key", ["vt_tray", "vir_slot"])
def test_remaining_of_an_external_spool(
    key: str, tray: dict[str, Any], remaining: int | None
) -> None:
    """Only a tag tells what remains of an external spool."""
    spool = {"id": "255", "tray_type": "PLA", **tray}
    state = PrinterState.from_report({key: spool if key == "vt_tray" else [spool]})

    assert state.external_spools[0].filament == Filament(
        type="PLA", remaining=remaining
    )
