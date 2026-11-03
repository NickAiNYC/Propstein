/**
 * @propstein/detection — active-screen market detection.
 * Depends on the DOM for browser wiring; every decision rule is a pure
 * function in visibility-filter.ts / dom-extractor.ts and is unit-tested.
 */
export * from "./visibility-filter.ts";
export * from "./dom-extractor.ts";
export * from "./viewport-observer.ts";
export * from "./adapters/index.ts";
