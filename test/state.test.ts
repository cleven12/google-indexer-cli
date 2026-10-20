import { expect, test } from "bun:test";
import { State, parseStamp } from "../src/state";

test("pending skips done URLs; a cooldown re-admits old ones", () => {
  const state = new State(":memory:");
  state.markSubmitted(["https://a.com/1"]);
  expect(state.pending(["https://a.com/1", "https://a.com/2"])).toEqual(["https://a.com/2"]);
  expect(state.pending(["https://a.com/1", "https://a.com/2"], 24)).toEqual(["https://a.com/2"]);
  // 0 < hours < age: URL is no longer cooling, so it is eligible again
  expect(state.pending(["https://a.com/1"], 0.0000001)).toEqual(["https://a.com/1"]);
});

test("errors are retrievable and re-submitting clears them", () => {
  const state = new State(":memory:");
  state.markError([["https://a.com/1", "ERROR_500"]]);
  expect(state.failed()).toEqual(["https://a.com/1"]);
  state.markSubmitted(["https://a.com/1"]);
  expect(state.failed()).toEqual([]);
});

test("naive UTC stamps from the legacy tool parse as UTC", () => {
  expect(parseStamp("2026-01-01T00:00:00.123456")).toBe(Date.parse("2026-01-01T00:00:00.123Z"));
});
