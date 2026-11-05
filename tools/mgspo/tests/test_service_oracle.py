import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import oracle
import service_oracle as service


def events(scratch, stop=4):
    rows = [{
        "event": "kjfs_probe_start",
        "scratch": scratch,
        "start_stage": 0,
        "stop_stage": stop,
    }]
    calls = [
        [scratch, 1, 0, scratch + 0x2000],
        [3],
        [3, scratch + 0x1000, 8],
        [3],
    ]
    results = [3, 59, 0xFFFFFFFF, 0]
    for stage in range(stop):
        call = {
            "event": "kjfs_probe_case",
            "phase": "call",
            "stage": stage,
            "case": service.CASES[stage],
            "args": calls[stage],
        }
        if stage == 0:
            call["path_hex"] = service.PATH_FIXTURES[0].encode("ascii").hex()
        rows.append(call)
        result = {
            "event": "kjfs_probe_case",
            "phase": "return",
            "stage": stage,
            "case": service.CASES[stage],
            "result": results[stage],
            "result_hi": 99,
        }
        if stage == 2:
            result["buffer_hex"] = "ab" * 59 + "cc" * 5
            result["guard_before_hex"] = "cc" * 16
            result["guard_after_hex"] = "cc" * 16
        rows.append(result)
    rows.append({"event": "kjfs_probe_done"})
    return rows


def canonical_file_events(scratch):
    payload = service.CANONICAL_FILE_PAYLOAD
    rows = [{
        "event": "kjfs_probe_start",
        "scratch": scratch,
        "start_stage": 54,
        "stop_stage": 58,
    }]
    calls = [
        [scratch, 1, 0, scratch + 0x2000],
        [3],
        [3, scratch + 0x1000, len(payload)],
        [3],
    ]
    results = [3, len(payload), 0xFFFFFFFF, 0]
    for offset, stage in enumerate(range(54, 58)):
        call = {
            "event": "kjfs_probe_case",
            "phase": "call",
            "stage": stage,
            "case": service.CASES[stage],
            "args": calls[offset],
        }
        if stage == 54:
            call["path_hex"] = service.PATH_FIXTURES[0].encode("ascii").hex()
        rows.append(call)
        result = {
            "event": "kjfs_probe_case",
            "phase": "return",
            "stage": stage,
            "case": service.CASES[stage],
            "result": results[offset],
            "result_hi": 99,
        }
        if stage == 56:
            result["buffer_hex"] = payload.hex() + "cc" * (64 - len(payload))
            result["guard_before_hex"] = "cc" * 16
            result["guard_after_hex"] = "cc" * 16
        rows.append(result)
    rows.append({"event": "kjfs_probe_done"})
    return rows


def blocked_events(scratch, retries=service.DEFAULT_BLOCKED_RETRIES):
    rows = [{
        "event": "kjfs_probe_start",
        "scratch": scratch,
        "start_stage": 42,
        "stop_stage": 44,
    }, {
        "event": "kjfs_probe_case",
        "phase": "call",
        "stage": 42,
        "case": service.CASES[42],
        "args": [scratch + 0x700, 1, 0, scratch + 0x2000],
        "path_hex": service.PATH_FIXTURES[7].encode("ascii").hex(),
    }, {
        "event": "kjfs_probe_case",
        "phase": "return",
        "stage": 42,
        "case": service.CASES[42],
        "result": 3,
        "result_hi": 0,
    }, {
        "event": "kjfs_probe_case",
        "phase": "call",
        "stage": 43,
        "case": service.CASES[43],
        "args": [3, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0],
    }]
    rows.append(service._expected_blocked_event(43, retries))
    return rows


def write_events(path, rows):
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def zar_resource(entries):
    archive = bytearray(struct.pack("<I", len(entries)))
    for name, payload in entries.items():
        archive.extend(name.encode("ascii") + b"\0")
        archive.extend(b"\0" * (-len(archive) % 4))
        archive.extend(struct.pack("<I", len(payload)))
        archive.extend(b"\0" * (-len(archive) % 16))
        archive.extend(payload)
        archive.append(0)
    return struct.pack("<I", len(archive)) + zlib.compress(bytes(archive))


def capture(output, producer, rows):
    output.mkdir()
    write_events(output / "events.jsonl", rows)
    identity = {
        "producer": producer,
        "disc": {"id": "TEST", "version": "1.00", "size": 1, "sha1": "a" * 40},
        "module": {
            "name": "KCEJ_FS",
            "path": "disc0:/kjfs.prx",
            "sha1": "b" * 40,
            "base": 0x08B75500,
            "size": 0x11A00,
        },
        "probe": "kjfs-v4",
        "archive_entry": {
            "container_path": service.ARCHIVE_RESOURCE_PATH,
            "container_size": 100,
            "container_sha256": "2" * 64,
            "entry_path": service.CANONICAL_FILE_PATH,
            "entry_name": "data.cnf",
            "entry_size": len(service.CANONICAL_FILE_PAYLOAD),
            "entry_sha256": service.CANONICAL_FILE_SHA256,
            "physical_file": False,
        },
        "start_stage": rows[0]["start_stage"],
        "stop_stage": rows[0]["stop_stage"],
    }
    if producer == "ppsspp":
        (output / "boot_state.json").write_text("{}", encoding="utf-8")
        (output / "oracle.log").write_text("", encoding="utf-8")
        (output / "service.done").write_text(
            json.dumps({
                "schema": service.SCHEMA,
                "steps": 500,
                "start_stage": identity["start_stage"],
                "stop_stage": identity["stop_stage"],
                "case_count": identity["stop_stage"] - identity["start_stage"],
            }),
            encoding="utf-8",
        )
        identity["build"] = {
            "schema": 1,
            "ppsspp_version": "1.20.4",
            "ppsspp_commit": "a" * 40,
            "patch_sha256": "b" * 64,
            "executable_sha256": "c" * 64,
            "configuration": "Release",
            "architecture": "x64",
            "compiler": "test",
            "vc_tools_version": "test",
            "visual_studio": "test",
            "windows_sdk": "test",
            "cmake": "test",
            "ninja": "test",
        }
        identity["settings"] = dict(oracle.EXPECTED_SETTINGS)
        identity["max_steps"] = service.MAX_STEPS
        files = service.REFERENCE_FILES
    else:
        (output / "structured.jsonl").write_text("", encoding="utf-8")
        (output / "runtime.log").write_text("", encoding="utf-8")
        identity["executable_sha256"] = "d" * 64
        identity["probe_source_sha256"] = "e" * 64
        identity["runtime_source_sha256"] = "f" * 64
        identity["iso_source_sha256"] = "1" * 64
        identity["disc_source"] = "iso"
        identity["native_zlib"] = True
        files = service.CANDIDATE_FILES
    service._write_manifest(output, identity, files)


def blocked_capture(output, producer, rows, retries=service.DEFAULT_BLOCKED_RETRIES):
    output.mkdir()
    write_events(output / "events.jsonl", rows)
    (output / "service.blocked").write_text(
        json.dumps({
            "schema": service.SCHEMA,
            "stage": 43,
            "case": service.CASES[43],
            "retry_count": retries,
        }),
        encoding="utf-8",
    )
    identity = {
        "producer": producer,
        "disc": {
            "id": "TEST", "version": "1.00", "size": 1, "sha1": "a" * 40,
        },
        "module": {
            "name": "KCEJ_FS",
            "path": "disc0:/kjfs.prx",
            "sha1": "b" * 40,
            "base": 0x08B75500,
            "size": 0x11A00,
        },
        "probe": "kjfs-v5-blocked",
        "archive_entry": {
            "container_path": service.ARCHIVE_RESOURCE_PATH,
            "container_size": 100,
            "container_sha256": "2" * 64,
            "entry_path": service.CANONICAL_FILE_PATH,
            "entry_name": "data.cnf",
            "entry_size": len(service.CANONICAL_FILE_PAYLOAD),
            "entry_sha256": service.CANONICAL_FILE_SHA256,
            "physical_file": False,
        },
        "start_stage": 42,
        "stop_stage": 44,
        "blocked_stage": 43,
        "retry_count": retries,
    }
    if producer == "ppsspp":
        (output / "boot_state.json").write_text("{}", encoding="utf-8")
        (output / "oracle.log").write_text("", encoding="utf-8")
        identity["build"] = {
            "schema": 1,
            "ppsspp_version": "1.20.4",
            "ppsspp_commit": "a" * 40,
            "patch_sha256": "b" * 64,
            "executable_sha256": "c" * 64,
            "configuration": "Release",
            "architecture": "x64",
            "compiler": "test",
            "vc_tools_version": "test",
            "visual_studio": "test",
            "windows_sdk": "test",
            "cmake": "test",
            "ninja": "test",
        }
        identity["settings"] = dict(oracle.EXPECTED_SETTINGS)
        identity["max_steps"] = service.MAX_STEPS
        files = service.BLOCKED_REFERENCE_FILES
    else:
        (output / "structured.jsonl").write_text("", encoding="utf-8")
        (output / "runtime.log").write_text("", encoding="utf-8")
        identity["executable_sha256"] = "d" * 64
        identity["probe_source_sha256"] = "e" * 64
        identity["runtime_source_sha256"] = "f" * 64
        identity["iso_source_sha256"] = "1" * 64
        identity["disc_source"] = "iso"
        identity["native_zlib"] = True
        files = service.BLOCKED_CANDIDATE_FILES
    service._write_manifest(output, identity, files)


class ServiceEventTests(unittest.TestCase):
    def test_parses_canonical_entry_from_zar_resource(self):
        entries = service._zar_entries(zar_resource({
            "data.cnf": service.CANONICAL_FILE_PAYLOAD,
            "cache.qar": b"archive",
        }))
        self.assertEqual(entries["data.cnf"], service.CANONICAL_FILE_PAYLOAD)

    def test_rejects_duplicate_zar_entry(self):
        resource = bytearray(zar_resource({"data.cnf": b"first"}))
        archive = zlib.decompress(resource[4:])
        duplicate = bytearray(archive)
        struct.pack_into("<I", duplicate, 0, 2)
        duplicate.extend(b"data.cnf\0\0\0\0")
        duplicate.extend(struct.pack("<I", 1))
        duplicate.extend(b"\0" * (-len(duplicate) % 16))
        duplicate.extend(b"x\0")
        resource = struct.pack("<I", len(duplicate)) + zlib.compress(bytes(duplicate))
        with self.assertRaisesRegex(oracle.OracleError, "duplicate"):
            service._zar_entries(resource)

    def test_reads_all_cases_and_normalizes_guest_scratch(self):
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "left.jsonl"
            right = Path(directory) / "right.jsonl"
            write_events(left, events(0x09000000))
            write_events(right, events(0x09100000))
            self.assertEqual(
                service.read_cases(left, 0, 4),
                service.read_cases(right, 0, 4),
            )

    def test_accepts_size_driven_full_canonical_file_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            write_events(path, canonical_file_events(0x09000000))
            records = service.read_cases(path, 54, 58)
            self.assertEqual(records[1]["result"], 59)
            self.assertEqual(records[2]["result"], 0xFFFFFFFF)

    def test_rejects_canonical_file_count_not_matching_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = canonical_file_events(0x09000000)
            rows[5]["args"][2] -= 1
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "unexpected call arguments"):
                service.read_cases(path, 54, 58)

    def test_rejects_canonical_file_transfer_with_sentinel_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = canonical_file_events(0x09000000)
            rows[6]["buffer_hex"] = "cc" * 64
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "left sentinel bytes"):
                service.read_cases(path, 54, 58)

    def test_rejects_canonical_file_write_past_reported_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = canonical_file_events(0x09000000)
            rows[6]["buffer_hex"] = rows[6]["buffer_hex"][:-2] + "00"
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "beyond transfer size"):
                service.read_cases(path, 54, 58)

    def test_rejects_missing_completion_even_when_all_cases_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            write_events(path, events(0x09000000)[:-1])
            with self.assertRaisesRegex(oracle.OracleError, "did not complete"):
                service.read_cases(path, 0, 4)

    def test_rejects_reordered_and_duplicated_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = events(0x09000000)
            rows.insert(3, rows[1])
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "reordered"):
                service.read_cases(path, 0, 4)

    def test_rejects_missing_guard_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = events(0x09000000)
            rows[6]["buffer_hex"] = "ab" * 59
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "64-byte buffer"):
                service.read_cases(path, 0, 4)

    def test_rejects_missing_external_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = events(0x09000000)
            del rows[6]["guard_after_hex"]
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "guard_after_hex"):
                service.read_cases(path, 0, 4)

    def test_rejects_out_of_range_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = events(0x09000000)
            rows[1]["args"][0] += 0x10000
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "outside scratch"):
                service.read_cases(path, 0, 4)

    def test_rejects_matching_but_wrong_case_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = events(0x09000000)
            rows[5]["args"][2] = 7
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "unexpected call arguments"):
                service.read_cases(path, 0, 4)

    def test_rejects_matching_but_wrong_path_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = events(0x09000000)
            rows[1]["path_hex"] = "64697363303a2f77726f6e67"
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "unexpected path bytes"):
                service.read_cases(path, 0, 4)

    def test_rejects_modified_guard_even_if_both_captures_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = events(0x09000000)
            rows[6]["guard_after_hex"] = "cc" * 15 + "00"
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "guard_after_hex was modified"):
                service.read_cases(path, 0, 4)

    def test_rejects_return_without_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = events(0x09000000)
            del rows[1]
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "return without call"):
                service.read_cases(path, 0, 4)

    def test_clears_inherited_runtime_and_probe_controls(self):
        with mock.patch.dict(
            "os.environ",
            {
                "SR_MEMSTICK": "old",
                "MGSPO_DISC_ROOT": "old",
                "PSPRECOMP_ORACLE_KJFS_PROBE": "1",
                "PSP_ISO": "old",
                "PATH": "required",
            },
            clear=True,
        ):
            self.assertEqual(service._environment(), {"PATH": "required"})

    def test_accepts_exact_bounded_blocked_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            expected = blocked_events(0x09000000)
            write_events(path, expected)
            self.assertEqual(
                service.read_blocked(path, 43, 8),
                expected[-1],
            )

    def test_rejects_blocked_export_return(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = blocked_events(0x09000000)
            rows.insert(4, {
                "event": "kjfs_probe_case",
                "phase": "return",
                "stage": 43,
                "case": service.CASES[43],
                "result": 0,
                "result_hi": 0,
            })
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "unexpectedly returned"):
                service.read_blocked(path, 43, 8)

    def test_rejects_wrong_blocked_operation_signature(self):
        mutations = (
            ("nid", 1),
            ("pc", 1),
            ("result", 1),
        )
        for field, delta in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "events.jsonl"
                rows = blocked_events(0x09000000)
                rows[-1]["operation"][field] += delta
                write_events(path, rows)
                with self.assertRaisesRegex(oracle.OracleError, "signature mismatch"):
                    service.read_blocked(path, 43, 8)

    def test_rejects_wrong_blocked_delay_signature(self):
        mutations = (
            ("microseconds", 1),
            ("result", 1),
        )
        for field, delta in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "events.jsonl"
                rows = blocked_events(0x09000000)
                rows[-1]["delay"][field] += delta
                write_events(path, rows)
                with self.assertRaisesRegex(oracle.OracleError, "signature mismatch"):
                    service.read_blocked(path, 43, 8)

    def test_rejects_inconsistent_blocked_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = blocked_events(0x09000000)
            rows[-1]["thread_consistent"] = False
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "signature mismatch"):
                service.read_blocked(path, 43, 8)

    def test_rejects_missing_or_wrong_async_seek_result(self):
        mutations = (
            lambda wait: wait.pop("async_result_high"),
            lambda wait: wait.__setitem__("async_result_low", 0),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "events.jsonl"
                rows = blocked_events(0x09000000)
                mutate(rows[-1]["wait"])
                write_events(path, rows)
                with self.assertRaisesRegex(oracle.OracleError, "signature mismatch"):
                    service.read_blocked(path, 43, 8)

    def test_rejects_insufficient_retry_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = blocked_events(0x09000000, retries=7)
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "signature mismatch"):
                service.read_blocked(path, 43, 8)

    def test_rejects_invalid_blocked_stage_and_range(self):
        with self.assertRaisesRegex(oracle.OracleError, "not a blocked case"):
            service._blocked_range(44)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = blocked_events(0x09000000)
            rows[0]["start_stage"] = 43
            write_events(path, rows)
            with self.assertRaisesRegex(oracle.OracleError, "range mismatch"):
                service.read_blocked(path, 43, 8)


class ServiceCaptureTests(unittest.TestCase):
    def test_candidate_requires_disc_source_and_iso_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate"
            capture(output, "standalone", events(0x09000000))
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            del manifest["identity"]["iso_source_sha256"]
            service._write_manifest(output, manifest["identity"], service.CANDIDATE_FILES)
            with self.assertRaisesRegex(oracle.OracleError, "ISO source"):
                service.verify_capture(output)

    def test_candidate_rejects_unknown_disc_source(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate"
            capture(output, "standalone", events(0x09000000))
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            manifest["identity"]["disc_source"] = "unknown"
            service._write_manifest(output, manifest["identity"], service.CANDIDATE_FILES)
            with self.assertRaisesRegex(oracle.OracleError, "disc source"):
                service.verify_capture(output)

    def test_rejects_stale_candidate_iso_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            candidate = root / "candidate"
            capture(reference, "ppsspp", events(0x09000000))
            capture(candidate, "standalone", events(0x09100000))
            identity = json.loads(
                (reference / "manifest.json").read_text(encoding="utf-8")
            )["identity"]
            expected = {
                key: identity[key]
                for key in (
                    "disc", "module", "probe", "archive_entry",
                    "start_stage", "stop_stage",
                )
            }
            config = SimpleNamespace(
                disc={"iso_sha1": "a" * 40},
                version="1.20.4",
                commit="a" * 40,
                patch=root / "patch",
            )
            digests = {
                config.patch: "b" * 64,
                oracle.ROOT / "src" / "mgspo_kjfs_probe.c": "e" * 64,
                oracle.ROOT / "src" / "mgspo_hle.c": "f" * 64,
                oracle.ROOT / "src" / "mgspo_iso.c": "2" * 64,
            }
            hash_file = oracle.hash_file

            def source_hash(path):
                return digests[path] if path in digests else hash_file(path)

            with mock.patch.object(service, "_identity", return_value=expected), \
                 mock.patch.object(oracle, "hash_file", side_effect=source_hash):
                with self.assertRaisesRegex(oracle.OracleError, "ISO source is stale"):
                    service.compare_captures(reference, candidate, config)

    def test_disc_root_is_an_explicit_candidate_option(self):
        args = service.parse_args([
            "capture-candidate", "runtime.exe", "game.iso", "capture",
            "--disc-root", "disc",
        ])
        self.assertEqual(args.disc_root, Path("disc"))

    def test_blocked_capture_requires_completion_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate"
            blocked_capture(
                output, "standalone", blocked_events(0x09000000)
            )
            (output / "service.blocked").unlink()
            with self.assertRaisesRegex(
                oracle.OracleError, "missing service.blocked"
            ):
                service.verify_capture(output)

    def test_matching_blocked_captures_compare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            candidate = root / "candidate"
            blocked_capture(
                reference, "ppsspp", blocked_events(0x09000000)
            )
            blocked_capture(
                candidate, "standalone", blocked_events(0x09100000)
            )
            service.compare_captures(reference, candidate)

    def test_blocked_cli_restricts_stage_and_retry_count(self):
        args = service.parse_args([
            "capture-blocked-candidate",
            "runtime.exe",
            "game.iso",
            "capture",
            "--stage",
            "31",
        ])
        self.assertEqual(args.stage, 31)
        self.assertEqual(args.retries, service.DEFAULT_BLOCKED_RETRIES)

    def test_matching_captures_allow_different_undefined_high_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            candidate = root / "candidate"
            candidate_rows = events(0x09100000)
            candidate_rows[2]["result_hi"] = 101
            capture(reference, "ppsspp", events(0x09000000))
            capture(candidate, "standalone", candidate_rows)
            service.compare_captures(reference, candidate)

    def test_rejects_a_changed_result_or_buffer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            candidate = root / "candidate"
            rows = events(0x09100000)
            rows[6]["buffer_hex"] = "ab" * 58 + "ff" + "cc" * 5
            capture(reference, "ppsspp", events(0x09000000))
            capture(candidate, "standalone", rows)
            with self.assertRaisesRegex(oracle.OracleError, "buffer_hex differs"):
                service.compare_captures(reference, candidate)

    def test_rejects_tampered_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reference"
            capture(output, "ppsspp", events(0x09000000))
            with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write("{}\n")
            with self.assertRaisesRegex(oracle.OracleError, "payload"):
                service.verify_capture(output)

    def test_rejects_wrong_completion_count(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reference"
            capture(output, "ppsspp", events(0x09000000))
            done = json.loads((output / "service.done").read_text(encoding="utf-8"))
            done["case_count"] = 3
            (output / "service.done").write_text(json.dumps(done), encoding="utf-8")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            service._write_manifest(output, manifest["identity"], service.REFERENCE_FILES)
            with self.assertRaisesRegex(oracle.OracleError, "case_count"):
                service.verify_capture(output)

    def test_rejects_identically_truncated_captures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            candidate = root / "candidate"
            capture(reference, "ppsspp", events(0x09000000)[:-1])
            capture(candidate, "standalone", events(0x09100000)[:-1])
            with self.assertRaisesRegex(oracle.OracleError, "did not complete"):
                service.compare_captures(reference, candidate)

    def test_seek_compares_both_halves_of_the_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            candidate = root / "candidate"
            rows = [
                {"event": "kjfs_probe_start", "scratch": 0x09000000,
                 "start_stage": 6, "stop_stage": 7},
                {"event": "kjfs_probe_case", "phase": "call", "stage": 6,
                 "case": service.CASES[6], "args": [0, 0, 0, 0, 0]},
                {"event": "kjfs_probe_case", "phase": "return", "stage": 6,
                 "case": service.CASES[6], "result": 0, "result_hi": 0},
                {"event": "kjfs_probe_done"},
            ]
            capture(reference, "ppsspp", rows)
            rows[2]["result_hi"] = 1
            capture(candidate, "standalone", rows)
            with self.assertRaisesRegex(oracle.OracleError, "result_hi differs"):
                service.compare_captures(reference, candidate)


if __name__ == "__main__":
    unittest.main()
