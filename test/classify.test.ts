import { expect, test } from "bun:test";
import { classifyUrl, countTypes, prioritize } from "../src/classify";

const u = (path: string) => `https://example.com${path}`;

test("classifies tour-operator paths", () => {
  expect(classifyUrl(u("/tours/7-day-machame"))).toBe("tours");
  expect(classifyUrl(u("/tours/tag/budget"))).toBe("other");
  expect(classifyUrl(u("/destinations/serengeti"))).toBe("destinations");
  expect(classifyUrl(u("/guides/packing-list"))).toBe("guides");
  expect(classifyUrl(u("/guides/articles/best-time"))).toBe("articles");
  expect(classifyUrl(u("/booking/groups/jan"))).toBe("groups");
  expect(classifyUrl(u("/about/"))).toBe("static");
  expect(classifyUrl(u("/"))).toBe("static");
  expect(classifyUrl(u("/privacy/"))).toBe("other");
});

test("prioritize puts commercial pages first without mutating the input", () => {
  const input = [u("/privacy/"), u("/guides/a"), u("/tours/b"), u("/destinations/c")];
  expect(prioritize(input).map(classifyUrl)).toEqual(["tours", "destinations", "guides", "other"]);
  expect(input[0]).toBe(u("/privacy/"));
});

test("countTypes tallies by bucket", () => {
  expect(countTypes([u("/tours/a"), u("/tours/b"), u("/about")])).toEqual({ tours: 2, static: 1 });
});
