import { describe, expect, it } from "vitest";
import type { MonumentSummary } from "../../types/monument";
import {
  appendHistoricalContext,
  buildExplorerVisibleMonuments,
  dedupeById,
  markerCategory,
  positionsSignature,
  resolveByIds,
  resolveByNames,
} from "./mapVisibility";

function monument(id: number, name = `M${id}`): MonumentSummary {
  return {
    id,
    name_fr: name,
    name_en: null,
    name_ar: null,
    latitude: 36.85 + id / 1000,
    longitude: 10.33 + id / 1000,
    visit_duration_min: 30,
    dominant_period: "Romaine",
    function: "culturel",
    popularity: 1,
    image_url: null,
  };
}

describe("dedupeById", () => {
  it("keeps first occurrence and preserves fractional ids", () => {
    const result = dedupeById([monument(3.9), monument(3.9), monument(4)]);
    expect(result.map((m) => m.id)).toEqual([3.9, 4]);
  });
});

describe("appendHistoricalContext (LRU)", () => {
  it("appends new ids as most recent", () => {
    expect(appendHistoricalContext([1, 2], [3])).toEqual([1, 2, 3]);
  });

  it("moves an existing id to most-recent instead of duplicating", () => {
    expect(appendHistoricalContext([1, 2, 3], [2])).toEqual([1, 3, 2]);
  });

  it("drops the oldest when exceeding the limit", () => {
    expect(appendHistoricalContext([1, 2, 3, 4, 5], [6], 5)).toEqual([2, 3, 4, 5, 6]);
  });

  it("dedupes incoming ids", () => {
    expect(appendHistoricalContext([], [7, 7, 8], 5)).toEqual([7, 8]);
  });
});

describe("markerCategory priority", () => {
  const input = {
    selectedId: 2,
    desiredIds: new Set([1]),
    historicalIds: new Set([3]),
  };
  it("desired beats selected", () => {
    expect(markerCategory(1, { ...input, selectedId: 1 })).toBe("desired");
  });
  it("selected beats historical", () => {
    expect(markerCategory(2, { ...input, historicalIds: new Set([2]) })).toBe("selected");
  });
  it("historical then suggestion", () => {
    expect(markerCategory(3, input)).toBe("historical");
    expect(markerCategory(9, input)).toBe("suggestion");
  });
});

describe("buildExplorerVisibleMonuments", () => {
  it("dedupes across groups and caps suggestions", () => {
    const selected = monument(1);
    const desired = [monument(2)];
    const historical = [monument(3)];
    const suggestions = [monument(1), monument(4), monument(5), monument(6)];
    const result = buildExplorerVisibleMonuments(
      { selected, desired, historical, suggestions },
      2,
    );
    // selected(1), desired(2), historical(3), then 2 suggestions (1 is dedup'd => 4,5)
    expect(result.map((m) => m.id)).toEqual([1, 2, 3, 4, 5]);
  });
});

describe("resolveByNames / resolveByIds", () => {
  const catalog = [monument(1, "A"), monument(2, "B"), monument(3, "C")];
  it("resolves by name_fr", () => {
    expect(resolveByNames(catalog, ["B", "C"]).map((m) => m.id)).toEqual([2, 3]);
  });
  it("resolves by id order, skipping unknowns", () => {
    const byId = new Map(catalog.map((m) => [m.id, m]));
    expect(resolveByIds(byId, [3, 99, 1]).map((m) => m.id)).toEqual([3, 1]);
  });
});

describe("positionsSignature", () => {
  it("is identical for identical geometry regardless of array identity", () => {
    expect(positionsSignature([[1, 2], [3, 4]])).toBe(
      positionsSignature([[1, 2], [3, 4]]),
    );
  });
  it("differs for different geometry", () => {
    expect(positionsSignature([[1, 2]])).not.toBe(positionsSignature([[1, 3]]));
  });
});
