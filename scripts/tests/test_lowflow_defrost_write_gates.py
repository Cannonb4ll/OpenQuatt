"""Execute the final Modbus YAML gates and real defrost permission method."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]


class LowflowDefrostWriteGatesTest(unittest.TestCase):
    def test_pending_stop_survives_global_clear_at_every_final_gate(self) -> None:
        source = (ROOT / "openquatt/oq_HP_io.yaml").read_text()
        lambdas = []
        for suffix in ("set_working_mode", "compressor_level"):
            section = source[source.index("id: ${hp_id}_" + suffix):]
            match = re.search(r"    write_lambda: \|-\n((?:      [^\n]*\n|\n)+)", section)
            self.assertIsNotNone(match, suffix)
            body = textwrap.dedent(match.group(1))
            lambdas.append(body.replace("${hp_id}", "hp1").replace("${hp_index}", "1"))
            lambdas.append(body.replace("${hp_id}", "hp2").replace("${hp_index}", "2"))
        service = (ROOT / "components/openquatt_odu_defrost/OpenQuattOduDefrost.cpp").read_text()
        permission = re.search(r"bool OpenQuattOduDefrost::normal_write_allowed\(.*?\n}", service, re.S)
        self.assertIsNotNone(permission)
        permission = permission.group().replace("OpenQuattOduDefrost::", "")
        runtime = (ROOT / "openquatt/includes/control/oq_thermal_actuator_runtime.h").read_text()
        safety = re.search(r"  bool defrost_safety_stop_\(.*?\n  }", runtime, re.S)
        self.assertIsNotNone(safety)
        gates = "\n".join("std::optional<int> gate%d(int value) {\n%s\n}" % (i, body)
                          for i, body in enumerate(lambdas))
        unit = r'''
#include <cassert>
#include <optional>
#include "openquatt/includes/control/oq_defrost_logic.h"
#include "openquatt/includes/incidents/oq_hp_incident_engine.h"
#define id(x) x
#define OQ_ACTUATOR_SECONDARY_ID(x) hp2_##x
uint32_t clock_ms=110000;
uint32_t millis() { return clock_ms; }
bool oq_water_temp_hard_trip_active=false, oq_lowflow_fault_active=false;
struct Manager {
  oq_incidents::HpIncidentEngine engines[2];
  auto get_outputs(int index) const { return engines[index-1].outputs(); }
} oq_incident_manager;
struct Service {
  oq_defrost::Cycle cycle;
  bool loading_=false, trigger_ready_=false, save_after_load_=false, save_ready_=false;
  bool save_writing_=false, save_verifying_=false;
  int cleared=0;
  Service* operator->() { return this; }
  bool holding() const { return cycle.owns(); }
  void clear_tx_queue_for_device() { ++cleared; }
  void finish_profile_(bool) {}
  void release() {}
  // PERMISSION
} hp1_odu_defrost, hp2_odu_defrost;
struct Runtime {
  // SAFETY
} runtime;
// GATES
int main() {
  using Gate=std::optional<int> (*)(int);
  Gate gates[2][2]={{gate0,gate2},{gate1,gate3}};
  for (int hp=0;hp<2;++hp) {
    auto& engine=oq_incident_manager.engines[hp];
    auto& service=hp==0?hp1_odu_defrost:hp2_odu_defrost;
    engine.observe_run({100000,true,true,false,true,90.0F});
    service.cycle.observe_mode(2,clock_ms);
    service.cycle.observe_bit(true,clock_ms);
    service.cycle.step(clock_ms);
    assert(!runtime.defrost_safety_stop_(hp==0));
    for (auto gate:gates[hp]) { assert(!gate(0)); assert(!gate(17)); }
    // Initial global stop interrupts ownership but does not clear the ODU bit.
    oq_lowflow_fault_active=true;
    assert(runtime.defrost_safety_stop_(hp==0));
    for (auto gate:gates[hp]) { assert(gate(0)==0); assert(!gate(17)); }
    assert(service.cycle.observed_active() && service.cycle.interrupted);
    oq_lowflow_fault_active=false;
    oq_water_temp_hard_trip_active=true;
    assert(runtime.defrost_safety_stop_(hp==0));
    for (auto gate:gates[hp]) { assert(gate(0)==0); assert(!gate(17)); }
    assert(engine.request_stop(clock_ms));
    oq_water_temp_hard_trip_active=false;
    assert(engine.outputs().run_state==oq_incidents::RunState::STOPPING);
    assert(!engine.outputs().must_stop && !engine.outputs().stop_confirmation_pending);
    // Acknowledgements are lost; ordinary STOPPING remains authoritative.
    assert(runtime.defrost_safety_stop_(hp==0));
    assert(service.normal_write_allowed(0,runtime.defrost_safety_stop_(hp==0)));
    for (auto gate:gates[hp]) { assert(gate(0)==0); assert(!gate(17)); }
    clock_ms+=10000;
    service.cycle.observe_mode(2,clock_ms); service.cycle.observe_bit(true,clock_ms);
    assert(!engine.request_stop(clock_ms));
    for (auto gate:gates[hp]) assert(gate(0)==0);
    // Stop watchdog release still protects STOP_UNCONFIRMED.
    clock_ms+=50000;
    assert(!engine.request_stop(clock_ms));
    assert(engine.outputs().run_state==oq_incidents::RunState::STOP_UNCONFIRMED);
    service.cycle.observe_mode(2,clock_ms); service.cycle.observe_bit(true,clock_ms);
    for (auto gate:gates[hp]) { assert(gate(0)==0); assert(!gate(17)); }
    // With no pending stop/global fault, normal defrost hold remains intact.
    engine=oq_incidents::HpIncidentEngine{};
    service.cycle=oq_defrost::Cycle{};
    service.cycle.observe_mode(2,clock_ms); service.cycle.observe_bit(true,clock_ms);
    service.cycle.step(clock_ms);
    assert(!runtime.defrost_safety_stop_(hp==0));
    for (auto gate:gates[hp]) { assert(!gate(0)); assert(!gate(17)); }
    service.cycle.observe_bit(false,clock_ms); service.cycle.phase=oq_defrost::Phase::IDLE;
    for (auto gate:gates[hp]) { assert(gate(0)==0); assert(gate(8)==8); }
  }
}
'''.replace("// PERMISSION", permission).replace("// SAFETY", safety.group()).replace("// GATES", gates)
        compiler = shutil.which("clang++") or shutil.which("g++")
        self.assertIsNotNone(compiler)
        args = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT)]
        if os.uname().sysname == "Darwin":
            sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
            args += ["-isystem", str(Path(sdk) / "usr/include/c++/v1")]
        with tempfile.TemporaryDirectory(prefix="openquatt-defrost-write-gates-") as directory:
            source, binary = Path(directory) / "test.cpp", Path(directory) / "test"
            source.write_text(unit)
            built = subprocess.run(args + [str(source), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
