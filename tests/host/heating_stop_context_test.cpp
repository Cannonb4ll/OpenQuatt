#include "components/openquatt_decision_log/OpenQuattHeatingStop.h"

#include <cassert>
#include <cmath>

using namespace esphome::openquatt_decision_log;
using namespace esphome::openquatt_decision_log::heating_stop;

int main() {
  assert(encode(NAN) == UNKNOWN_VALUE && encode(INFINITY) == UNKNOWN_VALUE);
  assert(encode(0.0f) == 0 && encode(20.5f, 100.0f) == 2050);
  assert(encode(50000.0f) == 32767 && encode(-50000.0f) == -32767);
  Snapshot first;
  first.reason = REASON_PH_COMFORT_STOP;
  first.captured_ms = 1000;
  first.room_c = 2050;
  first.room_stop_c = 2050;
  first.room_restart_c = 2030;
  auto later = first;
  later.captured_ms = 61000;
  later.room_c = 2040;
  later.room_stop_c = 2100;
  const auto held = retain_first(first, later, true);
  assert(held.held && held.captured_ms == 1000 && held.room_c == 2050 && held.room_stop_c == 2050);
  assert(held.room_restart_c == 2030 && age_seconds(61000, held.captured_ms) == 60);
  assert(retain_first(held, later, false).reason == 0);
  assert(comfort_reason(false) == REASON_PH_COMFORT_STOP && comfort_reason(true) == REASON_PH_COMFORT_HOLD);
  assert(age_seconds(1000, UINT32_MAX - 999) == 2);
  assert(age_seconds(100000000, 0) == UINT16_MAX);
  later.reason = REASON_HEATING_INPUT_INVALID;
  assert(retain_first(first, later, true).reason == REASON_HEATING_INPUT_INVALID);

  CauseInput input;
  input.captured_reason = REASON_CURVE_LOW_LOAD;
  input.curve = true;
  assert(reason_for_stop(input) == REASON_CURVE_LOW_LOAD);
  input.source_unavailable = input.flow_trip = input.water_trip = input.disabled = true;
  assert(reason_for_stop(input) == REASON_HEATING_SOURCE_UNAVAILABLE);
  input.source_unavailable = false;
  assert(reason_for_stop(input) == REASON_HEATING_FLOW_LIMIT);
  input.flow_trip = false;
  assert(reason_for_stop(input) == REASON_HEATING_WATER_LIMIT);
  input.water_trip = false;
  assert(reason_for_stop(input) == REASON_HEATING_DISABLED);
  input.disabled = false;
  input.request_active = true;
  input.other_source_requested = true;
  assert(reason_for_stop(input) == REASON_HEATING_NO_CANDIDATE);
  input.dispatch_reason = REASON_HEATING_SINGLE_SUFFICIENT;
  assert(reason_for_stop(input) == REASON_HEATING_SINGLE_SUFFICIENT);
  input.other_source_requested = false;
  assert(reason_for_stop(input) == REASON_HEATING_NO_CANDIDATE);
  input.curve = false;
  input.low_load_blocked = true;
  assert(reason_for_stop(input) == REASON_PH_LOW_LOAD);
  input.low_load_blocked = false;
  input.electrical_blocked = true;
  assert(reason_for_stop(input) == REASON_HEATING_ELECTRICAL_LIMIT);
  input.electrical_blocked = false;
  input.central_reason = REASON_HEATING_FLOW_LIMIT;
  assert(reason_for_stop(input) == REASON_HEATING_FLOW_LIMIT);
  input.central_reason = 69;
  assert(reason_for_stop(input) == 69);
  input.central_reason = 37;
  assert(reason_for_stop(input) == 37);
  input.central_reason = 0;
  assert(!low_load_resumed(false, false) && !low_load_resumed(false, true));
  assert(!low_load_resumed(true, false) && low_load_resumed(true, true));
  assert(curve_single_reason(true, true) == REASON_HEATING_SINGLE_SUFFICIENT);
  assert(curve_single_reason(true, false) == REASON_HEATING_NO_CANDIDATE);
  assert(curve_single_reason(false, true) == REASON_HEATING_NO_CANDIDATE);
  assert(curve_demand_reason(true, 0) == 0);
  assert(curve_demand_reason(true, 1) == REASON_CURVE_WATER_STOP);
  assert(curve_demand_reason(true, 2) == REASON_CURVE_LOW_LOAD);
  assert(curve_demand_reason(false, 0) == REASON_HEATING_INPUT_INVALID);
  for (uint8_t reason : {8, 9, 10, 11}) {
    input.dispatch_reason = reason;
    assert(reason_for_stop(input) == (reason == 9    ? REASON_HEATING_ELECTRICAL_LIMIT
                                      : reason == 11 ? REASON_HEATING_NO_CANDIDATE
                                                     : REASON_HEATING_OPTIMIZER));
  }
}
