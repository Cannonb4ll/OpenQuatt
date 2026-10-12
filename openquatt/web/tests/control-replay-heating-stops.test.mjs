import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { attachHeatingStopSnapshots, getHeatingStopCopy, getHeatingStopReasonMeta } from "../js/src/features/control-replay-heating-stops.js";
import { setLocale } from "../js/src/i18n/index.js";
import { loadReplayHarness } from "./helpers/replay-render-harness.mjs";

globalThis.__OQ_PREVIEW__ = false;
globalThis.window = { location: { pathname: "/" }, localStorage: { getItem: () => null } };
function records(reason = "ph_comfort_stop", subject = "HP1") {
  const common = { subject, reason, cm: 1, uptime_s: 100, epoch_s: 1700000000, duration_s: 60 };
  return [
    { ...common, seq: 10, event_type: "heating_stop_context", flags: 1, value_a: 900, value_b: 0, threshold_a: 2500 },
    { ...common, seq: 11, event_type: "heating_stop_context", flags: 2, value_a: 2050, value_b: 2030, threshold_a: 2050 },
    { ...common, seq: 12, event_type: "heating_stop_context", flags: 3, value_a: -32768, value_b: -32768, threshold_a: -32768 },
    { ...common, seq: 13, event_type: "source_stop", flags: 32, value_a: 3, value_b: 0, threshold_a: 0 },
  ];
}
function copy(reason) {
  return getHeatingStopCopy(attachHeatingStopSnapshots(records(reason)).at(-1), "HP1");
}

test("original decision, zero demand and actual restart threshold survive in NL and EN", () => {
  for (const locale of ["nl", "en"]) {
    setLocale(locale);
    const result = copy("ph_comfort_stop");
    assert.ok(result.title.includes("HP1"));
    assert.match(result.snapshotSummary, /900 W.*0 W.*2[.,]500 W/);
    assert.match(result.next, locale === "nl" ? /20,30 °C/ : /20\.30 °C/);
    assert.match(result.detail, /60 s/);
    assert.doesNotMatch(result.detail, /NaN|-32768/);
    assert.match(copy("ph_comfort_hold").title, locale === "nl" ? /vastgehouden/ : /retained/);
  }
});

test("missing, mixed, nonadjacent, reordered, boot and legacy records cannot borrow a snapshot", () => {
  const malformed = [];
  malformed.push(records().slice(1), records().slice(2));
  for (const [field, value] of [["subject", "HP2"], ["reason", "ph_low_load"], ["seq", 9], ["cm", 2], ["flags", 3], ["duration_s", 61]]) {
    const list = records(); list[1][field] = value; malformed.push(list);
  }
  const reboot = records(); reboot[1] = { ...reboot[1], event_type: "boot_marker" }; malformed.push(reboot);
  const legacy = records(); legacy[3].flags = 0; malformed.push(legacy);
  for (const list of malformed) assert.equal(attachHeatingStopSnapshots(list).at(-1)._oq_heating_stop_snapshot, undefined);
  const acrossSecond = records(); acrossSecond[1].uptime_s++; acrossSecond[2].uptime_s++;
  assert.ok(attachHeatingStopSnapshots(acrossSecond).at(-1)._oq_heating_stop_snapshot);
});

test("low-load thresholds are watts and do not become temperatures", () => {
  setLocale("nl");
  const list = records("ph_low_load");
  list[2].threshold_a = 1600; list[2].value_b = 2200;
  const result = getHeatingStopCopy(attachHeatingStopSnapshots(list).at(-1), "HP1");
  assert.match(result.snapshotSummary, /1\.600 W.*2\.200 W/);
  assert.match(result.next, /2\.200 W/);
  assert.doesNotMatch(result.snapshotSummary, /16,00|22,00/);
});

test("unknown is not zero, saturated values are explicit and every new reason has both languages", () => {
  const codes = ["ph_demand_zero", "ph_low_load", "ph_comfort_stop", "ph_comfort_hold", "curve_water_stop", "curve_low_load", "heating_input_invalid", "heating_single_sufficient", "heating_electrical_limit", "heating_no_candidate", "heating_disabled", "heating_water_limit", "heating_flow_limit", "heating_source_unavailable", "heating_optimizer", "heating_central_pause", "supervisory_override", "frost_protection", "heating_request_cleared"];
  for (const locale of ["nl", "en"]) {
    setLocale(locale);
    for (const reason of codes) {
      assert.ok(getHeatingStopReasonMeta(reason));
      const result = getHeatingStopCopy({ event_type: "source_stop", reason, flags: 32 }, "HP1");
      assert.doesNotMatch(result.title + result.detail + result.next, /heatingStops\./);
      assert.match(result.detail, locale === "nl" ? /niet volledig bewaard/ : /not fully retained/);
    }
    const list = records(); list[0].value_a = null; list[0].value_b = 32767;
    const result = getHeatingStopCopy(attachHeatingStopSnapshots(list).at(-1), "HP1");
    assert.match(result.snapshotSummary, /— W.*≥ 32[.,]767 W/);
  }
});

test("context records are hidden, cooling keeps its original meaning, timeline and details show snapshots", async () => {
  setLocale("nl");
  const source = await readFile(new URL("../js/src/features/control-replay-view.js", import.meta.url), "utf8");
  const replay = await loadReplayHarness(source + "\nexport { enrichControlWorkingDecisionLogEvents, mapDecisionEventToControlWorkingItem, renderControlWorkingTimelineItem };\n");
  const list = replay.enrichControlWorkingDecisionLogEvents(records());
  const window = { startEpochMs: 1699999900 * 1000, endEpochMs: 1700086300 * 1000, dayStartEpochMs: 1699999900 * 1000 };
  for (const event of list.slice(0, 3)) assert.equal(replay.mapDecisionEventToControlWorkingItem(event, window, 1700000100000), null);
  assert.match(replay.getDecisionEventCopy(list.at(-1)).detail, /900 W/);
  const html = replay.renderControlWorkingTimelineItem({ id: "stop", kind: "event", severity: "normal", time: "07:10", title: "Stop", summary: "Reden", snapshotSummary: "<script>" }, null);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(replay.getDecisionEventCopy({ event_type: "source_stop", reason: "dew_stop", subject: "HP1", cm: 5 }).title, /kamer|stooklijn/);
});
