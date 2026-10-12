#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace esphome {
namespace openquatt_decision_log {

// Append-only wire codes; legacy stop records keep their original meaning.
enum HeatingStopReason : uint8_t {
  REASON_PH_DEMAND_ZERO = 75,
  REASON_PH_LOW_LOAD = 76,
  REASON_PH_COMFORT_STOP = 77,
  REASON_PH_COMFORT_HOLD = 78,
  REASON_CURVE_WATER_STOP = 79,
  REASON_CURVE_LOW_LOAD = 80,
  REASON_HEATING_INPUT_INVALID = 81,
  REASON_HEATING_SINGLE_SUFFICIENT = 82,
  REASON_HEATING_ELECTRICAL_LIMIT = 83,
  REASON_HEATING_NO_CANDIDATE = 84,
  REASON_HEATING_DISABLED = 85,
  REASON_HEATING_WATER_LIMIT = 86,
  REASON_HEATING_FLOW_LIMIT = 87,
  REASON_HEATING_SOURCE_UNAVAILABLE = 88,
  REASON_HEATING_OPTIMIZER = 89,
  REASON_HEATING_CENTRAL_PAUSE = 90,
};

namespace heating_stop {
constexpr int16_t UNKNOWN_VALUE = std::numeric_limits<int16_t>::min();
enum ContextKind : uint8_t { POWER = 1, ROOM = 2, WATER = 3 };

inline int16_t encode(float value, float scale = 1.0f) {
  if (!std::isfinite(value)) return UNKNOWN_VALUE;
  return static_cast<int16_t>(std::lround(std::clamp(value * scale, -32767.0f, 32767.0f)));
}

struct Snapshot {
  uint32_t captured_ms{0};
  int16_t base_w{UNKNOWN_VALUE}, effective_w{UNKNOWN_VALUE};
  int16_t room_c{UNKNOWN_VALUE}, room_stop_c{UNKNOWN_VALUE}, room_restart_c{UNKNOWN_VALUE};
  int16_t supply_c{UNKNOWN_VALUE}, supply_stop_c{UNKNOWN_VALUE}, supply_restart_c{UNKNOWN_VALUE};
  uint8_t reason{0};
  bool held{false};
};
static_assert(sizeof(Snapshot) <= 24, "Heating stop snapshots must remain bounded");

// A pending stop can wait for minimum runtime/defrost. Retain the first decision,
// including its thresholds, until the strategy requests heat again.
inline Snapshot retain_first(Snapshot previous, Snapshot current, bool stopping) {
  if (!stopping) return {};
  if (current.reason == REASON_HEATING_INPUT_INVALID) return current;
  if (previous.reason == 0) return current;
  if (previous.reason == REASON_PH_COMFORT_STOP || previous.reason == REASON_PH_COMFORT_HOLD) previous.held = true;
  return previous;
}

inline uint8_t comfort_reason(bool already_stopping) {
  return already_stopping ? REASON_PH_COMFORT_HOLD : REASON_PH_COMFORT_STOP;
}

struct CauseInput {
  bool source_unavailable{false}, flow_trip{false}, water_trip{false}, disabled{false};
  bool request_active{false}, curve{false}, low_load_blocked{false}, electrical_blocked{false};
  bool other_source_requested{false};
  uint8_t captured_reason{0}, dispatch_reason{0};
  uint8_t central_reason{0};
};

inline uint8_t reason_for_stop(const CauseInput& in) {
  if (in.source_unavailable) return REASON_HEATING_SOURCE_UNAVAILABLE;
  if (in.flow_trip) return REASON_HEATING_FLOW_LIMIT;
  if (in.water_trip) return REASON_HEATING_WATER_LIMIT;
  if (in.disabled) return REASON_HEATING_DISABLED;
  if (in.central_reason != 0) return in.central_reason;
  if (!in.request_active && in.captured_reason != 0) return in.captured_reason;
  if (in.low_load_blocked) return REASON_PH_LOW_LOAD;
  if (in.electrical_blocked) return REASON_HEATING_ELECTRICAL_LIMIT;
  if (!in.request_active) return in.curve ? 45 : REASON_PH_DEMAND_ZERO;
  if (in.curve)
    return in.other_source_requested && in.dispatch_reason == REASON_HEATING_SINGLE_SUFFICIENT
               ? REASON_HEATING_SINGLE_SUFFICIENT
               : REASON_HEATING_NO_CANDIDATE;
  if (in.dispatch_reason == 11) return REASON_HEATING_NO_CANDIDATE;
  if (in.dispatch_reason == 9) return REASON_HEATING_ELECTRICAL_LIMIT;
  if (in.dispatch_reason == 10 || in.dispatch_reason == 8) return REASON_HEATING_OPTIMIZER;
  return in.request_active ? REASON_HEATING_NO_CANDIDATE : REASON_PH_DEMAND_ZERO;
}

inline bool low_load_resumed(bool raw_request, bool latched) { return raw_request && latched; }

inline uint8_t curve_demand_reason(bool valid, uint8_t stop_reason) {
  if (!valid) return REASON_HEATING_INPUT_INVALID;
  // oq_curve::STOP_NORMAL = 1; STOP_LOW_LOAD = 2. STOP_NONE proves no stop cause.
  return stop_reason == 1 ? REASON_CURVE_WATER_STOP : stop_reason == 2 ? REASON_CURVE_LOW_LOAD : 0;
}

inline uint8_t curve_single_reason(bool confirmed_regular_stop, bool duo_available) {
  return confirmed_regular_stop && duo_available ? REASON_HEATING_SINGLE_SUFFICIENT : REASON_HEATING_NO_CANDIDATE;
}

inline uint16_t age_seconds(uint32_t now_ms, uint32_t captured_ms) {
  return static_cast<uint16_t>(std::min<uint32_t>((now_ms - captured_ms) / 1000U, UINT16_MAX));
}
}  // namespace heating_stop
}  // namespace openquatt_decision_log
}  // namespace esphome
