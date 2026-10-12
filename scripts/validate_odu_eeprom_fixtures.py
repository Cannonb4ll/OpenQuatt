#!/usr/bin/env python3
"""Check existing EEPROM fixtures and retained runtime CRC differences."""
import argparse
import json
from pathlib import Path
import re


FIXTURES = (
    ("v1_eeprom.h", True),
    ("v1_5_eeprom.h", True),
    ("v2_old_amh6_eeprom.h", False),
    ("v2_new_amh6_eeprom.h", False),
)


class IntegrityError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise IntegrityError(message)


def modbus(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def cpp_integer(literal):
    base = 16 if literal.lower().startswith("0x") else 8 if literal.startswith("0") else 10
    return int(literal, base)


def clean_cpp(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def fixture_array(text, name, count):
    declarations = re.findall(r"\b" + name + r"\s*=\s*\{([^{}]*)\}\s*;", clean_cpp(text), re.S)
    require(len(declarations) == 1, f"{name}: missing or ambiguous declaration")
    tokens = declarations[0].strip().rstrip(",").split(",")
    require(len(tokens) == count, f"{name}: expected {count} elements")
    values = []
    for token in tokens:
        match = re.fullmatch(r"\s*(0[xX][0-9a-fA-F]+|[0-9]+)[uU]?\s*", token)
        require(match is not None, f"{name}: unsupported literal")
        values.append(cpp_integer(match[1]))
    require(all(0 <= value <= 65535 for value in values), f"{name}: outside uint16 range")
    return values


def fixture_scalar(text, name):
    values = re.findall(r"\b" + name + r"\s*=\s*(0[xX][0-9a-fA-F]+|[0-9]+)[uU]?\s*;", clean_cpp(text))
    require(len(values) == 1, f"{name}: missing or ambiguous scalar")
    return cpp_integer(values[0])


def validate_fixture(path, has_capture):
    text = path.read_text()
    words = fixture_array(text, "EEPROM_WORDS", 512)
    require(all(value <= 255 for value in words), "EEPROM high byte is nonzero")
    payload = bytes(words)
    stored = words[510] | words[511] << 8
    require(modbus(payload[:510]) == stored and modbus(payload) == 0, "baseline EEPROM CRC mismatch")
    require(stored == fixture_scalar(text, "EEPROM_CRC"), "baseline CRC constant differs")
    if has_capture:
        runtime = words.copy()
        runtime[1:12] = fixture_array(text, "CAPTURED_COOLING_WORDS", 11)
        require(all(value <= 255 for value in runtime), "runtime EEPROM high byte is nonzero")
        calculated = modbus(bytes(runtime[:510]))
        require(calculated != stored and modbus(bytes(runtime)) != 0, "retained runtime CRC mismatch disappeared")
        require(calculated == fixture_scalar(text, "CAPTURED_CALCULATED_CRC"), "captured runtime CRC differs")
    return {"file": path.name, "baseline": "PASS", "runtime_capture": "CRC_MISMATCH_CONFIRMED" if has_capture else "NOT_PRESENT"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()
    report = {"fixtures": [], "errors": []}
    for name, has_capture in FIXTURES:
        try:
            report["fixtures"].append(validate_fixture(args.repo_root / "tests/fixtures" / name, has_capture))
        except (OSError, ValueError) as error:
            report["errors"].append(f"{name}: {error}")
    report["result"] = "FAIL" if report["errors"] else "PASS"
    if args.json_report:
        args.json_report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['result']}: {len(report['fixtures'])}/{len(FIXTURES)} EEPROM fixtures; {len(report['errors'])} errors")
    for error in report["errors"]:
        print(f"  {error}")
    raise SystemExit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
