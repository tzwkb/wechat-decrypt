import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "windows" / "extract_raw_key.py"
HARNESS = ROOT / "tests" / "js" / "windows_extractor_harness.cjs"
SPEC = importlib.util.spec_from_file_location("windows_extractor", SCRIPT)
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)
KEY = bytes(range(32))
PAD = bytes(byte ^ 0x36 for byte in KEY) + b"\x36" * 96


def module_memory(tables, entries):
    memory = bytearray(b"\x90" * 0x4000)
    for offset in tables:
        memory[offset:offset + 8] = bytes.fromhex("22 ae 28 d7 98 2f 8a 42")
    for entry, references in entries:
        memory[entry - 8:entry] = b"\xcc" * 8
        for position, target, register in references:
            memory[position:position + 7] = bytes([
                0x48 | ((register >> 3) << 2), 0x8D, 0x05 | ((register & 7) << 3),
            ]) + struct.pack("<i", target - position - 7)
    return memory


def run_js(memory, **options):
    node = shutil.which("node")
    assert node, "Node.js is required for the embedded Frida JavaScript regression tests"
    result = subprocess.run(
        [node, str(HARNESS)],
        input=json.dumps({"script": extractor.JS, "memory": memory.hex(), **options}),
        capture_output=True, text=True, check=True, timeout=15,
    )
    report = json.loads(result.stdout)
    assert report["error"] is None, report["error"]
    return report


def test_all_tables_and_xrefs_are_hooked_once_and_second_entry_captures_key():
    memory = module_memory([0x3000, 0x3010, 0x3800], [
        (0x100, [(0x120, 0x3000, 0), (0x140, 0x3010, 11), (0x160, 0x3000, 2)]),
        (0x500, [(0x520, 0x3800, 15)]),
    ])
    report = run_js(memory, calls=[{"entry": 0x500, "block": PAD.hex()}])
    assert sorted(report["entries"]) == [0x100, 0x500]
    assert len(report["attempts"]) == 2
    assert "SHA-512 K-tables found: 3" in report["messages"]
    assert report["messages"].count("KEY:" + KEY.hex()) == 1


def test_all_rip_relative_lea_registers_and_negative_displacements():
    entries = [0x100 * (register + 1) for register in range(16)]
    memory = module_memory([0x40], [
        (entry, [(entry + 16, 0x40, register)]) for register, entry in enumerate(entries)
    ])
    report = run_js(memory, calls=[{"entry": entry, "block": PAD.hex()} for entry in entries])
    assert sorted(report["entries"]) == entries
    assert report["messages"].count("KEY:" + KEY.hex()) == 1


def test_legacy_single_entry_and_late_module_are_supported():
    memory = module_memory([0x3000], [(0x100, [(0x120, 0x3000, 0)])])
    report = run_js(memory, late_module=True, repeat_module=True)
    assert report["beforeLateEntries"] == 0
    assert report["entries"] == report["attempts"] == [0x100]


def test_data_references_are_not_hooked_and_each_range_is_scanned_once():
    memory = module_memory([0x3000], [
        (0x100, [(0x120, 0x3000, 0)]), (0x3200, [(0x3220, 0x3000, 0)]),
    ])
    report = run_js(memory, ranges=[
        {"offset": 0, "size": 0x1000, "protection": "r-x"},
        {"offset": 0x3000, "size": 0x1000, "protection": "r--"},
    ])
    assert report["entries"] == [0x100]
    assert len(report["scans"]) == 3


def test_failed_hook_does_not_prevent_another_entry_capturing_key():
    memory = module_memory([0x3000], [
        (0x100, [(0x120, 0x3000, 0)]), (0x500, [(0x520, 0x3000, 8)]),
    ])
    report = run_js(memory, fail_hooks=[0x100], calls=[{"entry": 0x500, "block": PAD.hex()}])
    assert report["entries"] == [0x500]
    assert "KEY:" + KEY.hex() in report["messages"]
    assert any(message.startswith("WARN: hook failed") for message in report["messages"])


def test_truncated_lea_at_executable_range_boundary_is_ignored():
    memory = module_memory([0x3000], [
        (0x100, [(0x120, 0x3000, 0)]), (0xFC0, [(0xFFD, 0x3000, 0)]),
    ])
    report = run_js(memory, ranges=[
        {"offset": 0, "size": 0x1000, "protection": "r-x"},
        {"offset": 0x1000, "size": 0x3000, "protection": "r--"},
    ])
    assert report["entries"] == [0x100]


def test_failed_scan_does_not_hide_other_ranges():
    memory = module_memory([0x3000], [(0x1100, [(0x1120, 0x3000, 0)])])
    report = run_js(memory, fail_scans=[0], ranges=[
        {"offset": 0, "size": 0x1000, "protection": "r-x"},
        {"offset": 0x1000, "size": 0x1000, "protection": "r-x"},
        {"offset": 0x3000, "size": 0x1000, "protection": "r--"},
    ])
    assert report["entries"] == [0x1100]
    assert any(message.startswith("WARN: scan skipped") for message in report["messages"])


@pytest.mark.parametrize("tables,entries,options,error", [
    ([], [], {}, "K-table not found"),
    ([0x3000], [], {}, "entries not found"),
    ([0x3000], [(0x100, [(0x120, 0x3000, 0)])], {"fail_hooks": [0x100]}, "could be hooked"),
])
def test_discovery_failures_report_errors(tables, entries, options, error):
    report = run_js(module_memory(tables, entries), **options)
    assert not report["entries"]
    assert any(message.startswith("ERR:") and error in message for message in report["messages"])


@pytest.mark.parametrize("memory,pid", [("30,000 K", 42), ("30.000 K", 42), ("30\u00a0000 K", 42), ("20,480 K", None)])
def test_tasklist_memory_formats_and_threshold(memory, pid):
    output = f'"Weixin.exe","42","Console","1","{memory}"\n'
    assert extractor.parse_main_pid(output) == pid


def test_tasklist_selects_largest_weixin_process_and_ignores_noise():
    output = '\n'.join([
        'INFO: No tasks are running which match the specified criteria.',
        '"Weixin.exe","3","Console","1","5,000 K"',
        '"Other.exe","4","Console","1","500,000 K"',
        '"WEIXIN.EXE","5","Console","1","90,000 K"',
        '"Weixin.exe","6","Console","1","30,000 K"',
        '"Weixin.exe","bad","Console","1","999,999 K"',
        '"Weixin.exe","7","Console","1","N/A"',
    ])
    assert extractor.parse_main_pid(output) == 5
    assert extractor.parse_main_pid("信息: 没有运行的任务匹配指定标准。") is None


def test_main_pid_uses_filtered_csv_tasklist(monkeypatch):
    def run(command, **options):
        assert command == ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"]
        assert options["timeout"] == 0.5
        assert options["check"] is True
        return SimpleNamespace(stdout='"Weixin.exe","42","Console","1","90,000 K"')

    monkeypatch.setattr(extractor.subprocess, "run", run)
    assert extractor.main_pid(timeout=0.5) == 42


def test_process_query_time_is_included_in_deadline(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    timeouts = []

    def query(timeout):
        timeouts.append(timeout)
        clock.now += min(0.8, timeout)
        if timeout < 0.8:
            raise subprocess.TimeoutExpired("tasklist", timeout)
        return None

    monkeypatch.setattr(extractor.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(extractor.time, "sleep", lambda delay: setattr(clock, "now", clock.now + delay))
    monkeypatch.setattr(extractor, "main_pid", query)
    with pytest.raises(TimeoutError, match="did not start"):
        extractor.wait_for_process(1)
    assert clock.now == pytest.approx(1.0)
    assert timeouts == pytest.approx([1.0, 0.16])


def test_process_exit_wait_and_new_process_detection(monkeypatch):
    pids = iter([42, None, None, 43])
    monkeypatch.setattr(extractor, "main_pid", lambda timeout: next(pids))
    monkeypatch.setattr(extractor.time, "sleep", lambda delay: None)
    assert extractor.wait_for_process(1, stopped=True) is None
    assert extractor.wait_for_process(1) == 43


def encrypted_page(key, *, derived=False):
    from Crypto.Cipher import AES

    page = bytearray(4096)
    page[:16] = bytes(range(16))
    page[4016:4032] = bytes(reversed(range(16)))
    if not derived:
        key = extractor.hashlib.pbkdf2_hmac("sha512", key, page[:16], 256000, 32)
    header = bytes.fromhex("10 00 01 01 50 40 20 20 00 00 00 00 00 00 00 00")
    page[16:32] = AES.new(key, AES.MODE_CBC, page[4016:4032]).encrypt(header)
    return bytes(page)


def test_capture_validates_raw_key_and_never_logs_key(capsys):
    capture = extractor.KeyCapture(encrypted_page(KEY))
    for key in ["malformed", "ff" * 32, KEY.hex(), KEY.hex()]:
        capture.on_message({"type": "send", "payload": "KEY:" + key}, None)
    assert capture.raw_key == KEY.hex()
    output = capsys.readouterr().out
    assert KEY.hex() not in output and "ff" * 32 not in output
    assert output.count("RAW KEY captured and verified") == 1


def test_derived_key_is_not_saved_as_raw_key(capsys):
    capture = extractor.KeyCapture(encrypted_page(KEY, derived=True))
    capture.on_message({"type": "send", "payload": "KEY:" + KEY.hex()}, None)
    assert capture.raw_key is None
    output = capsys.readouterr().out
    assert "K1 candidate verified" in output and KEY.hex() not in output


@pytest.mark.parametrize("message", [
    {"type": "error", "description": "script initialization failed"},
    {"type": "send", "payload": "ERR: SHA512 K-table not found"},
])
def test_frida_errors_stop_capture_immediately_and_detach(monkeypatch, message):
    class Session:
        detached = False

        def create_script(self, script):
            assert script == extractor.JS
            return self

        def on(self, event, handler):
            self.handler = handler

        def load(self):
            self.handler(message, None)

        def detach(self):
            self.detached = True

    session = Session()
    monkeypatch.setattr(extractor.time, "sleep", lambda delay: pytest.fail("error must not wait for timeout"))
    assert extractor.capture_key(SimpleNamespace(attach=lambda pid: session), 42, bytes(4096), 90) is None
    assert session.detached


def test_import_does_not_load_frida_or_crypto_or_touch_database():
    subprocess.run([
        sys.executable, "-c",
        "import runpy, sys; sys.modules['frida'] = None; sys.modules['Crypto'] = None; "
        "runpy.run_path(sys.argv[1], run_name='import_test')",
        str(SCRIPT),
    ], check=True, capture_output=True, text=True, timeout=10)


@pytest.mark.skipif(sys.platform != "win32", reason="real Frida interception requires Windows x64")
def test_real_frida_scans_and_intercepts_synthetic_windows_functions():
    import frida

    memory = module_memory([0x3000, 0x3010, 0x3800], [
        (0x100, [(0x120, 0x3000, 0), (0x140, 0x3010, 11)]),
        (0x500, [(0x520, 0x3800, 0)]),
    ])
    memory[0x127] = memory[0x527] = 0xC3
    fixture_js = """
var fixture = Memory.alloc(16384);
fixture.writeByteArray(%s);
Memory.protect(fixture, 16384, "rwx");
installHooks({base: fixture, enumerateRanges: function() {
  return [{base: fixture, size: 16384, protection: "rwx"}];
}});
var block = Memory.alloc(128);
block.writeByteArray(%s);
var secondEntry = new NativeFunction(fixture.add(0x500), "void", ["pointer", "pointer"]);
secondEntry(ptr(0), block);
secondEntry(ptr(0), block);
""" % (json.dumps(list(memory)), json.dumps(list(PAD)))
    messages, completed = [], threading.Event()

    def on_message(message, data):
        messages.append(message)
        if message.get("type") == "error" or str(message.get("payload", "")).startswith("KEY:"):
            completed.set()

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = None
    try:
        session = frida.get_local_device().attach(child.pid)
        script = session.create_script(extractor.JS + fixture_js)
        script.on("message", on_message)
        script.load()
        assert completed.wait(10), "Frida did not capture the synthetic key"
        assert not [message for message in messages if message.get("type") == "error"], json.dumps(messages, indent=2)
        payloads = [message.get("payload", "") for message in messages]
        assert payloads.count("KEY:" + KEY.hex()) == 1
        assert sum(str(payload).startswith("sha512 entry @") for payload in payloads) == 2
    finally:
        try:
            if session:
                session.detach()
        finally:
            child.terminate()
            child.wait(timeout=5)
