/**
 * Unit tests — odds mathematics (spec §7, §15).
 * Verifies the exact worked example from the specification:
 *   Displayed odds +160, model probability 44%:
 *     break-even 38.46%, EV +14.4% per unit staked.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  americanToDecimal,
  decimalToAmerican,
  impliedProbability,
  breakEvenProbability,
  expectedValue,
  probabilityEdge,
  fairDecimalOdds,
  devigTwoWay,
  applyProbabilityHaircut,
  formatAmerican,
  parseAmericanOddsText,
  parseDecimalOddsText,
  formatPercent,
  formatEvPerUnit,
  americanImpliedProbability,
  InvalidOddsError,
} from "@propstein/core";

// ---------------------------------------------------------------------------
// American ↔ decimal conversion
// ---------------------------------------------------------------------------

test("americanToDecimal converts positive odds: +160 → 2.60", () => {
  assert.equal(americanToDecimal(160), 2.6);
});

test("americanToDecimal converts negative odds: -110 → 1.9090909...", () => {
  assert.ok(Math.abs(americanToDecimal(-110) - 1.9090909090909092) < 1e-12);
});

test("americanToDecimal: +100 and -100 both → 2.0 (even money)", () => {
  assert.equal(americanToDecimal(100), 2);
  assert.equal(americanToDecimal(-100), 2);
});

test("americanToDecimal: -400 → 1.25", () => {
  assert.equal(americanToDecimal(-400), 1.25);
});

test("americanToDecimal rejects |odds| < 100 (repo contract)", () => {
  assert.throws(() => americanToDecimal(-50), InvalidOddsError);
  assert.throws(() => americanToDecimal(99), InvalidOddsError);
});

test("americanToDecimal rejects zero, NaN, Infinity", () => {
  assert.throws(() => americanToDecimal(0), InvalidOddsError);
  assert.throws(() => americanToDecimal(Number.NaN), InvalidOddsError);
  assert.throws(() => americanToDecimal(Number.POSITIVE_INFINITY), InvalidOddsError);
});

test("decimalToAmerican roundtrips", () => {
  assert.equal(decimalToAmerican(2.6), 160);
  assert.equal(decimalToAmerican(1.9090909090909092), -110);
  assert.equal(decimalToAmerican(2.0), 100);
  assert.equal(decimalToAmerican(1.25), -400);
});

// ---------------------------------------------------------------------------
// Break-even probability and implied probability
// ---------------------------------------------------------------------------

test("impliedProbability: 1/d", () => {
  assert.ok(Math.abs(impliedProbability(2.6) - 0.38461538461538464) < 1e-12);
});

test("breakEvenProbability: +160 → 38.46% (spec example)", () => {
  const p = breakEvenProbability(americanToDecimal(160));
  assert.ok(Math.abs(p - 0.384615) < 1e-5);
});

test("americanImpliedProbability matches repo OddsQuote convention for -110", () => {
  // src/contracts/odds.py: 110/(110+100) = 0.523809...
  assert.ok(Math.abs(americanImpliedProbability(-110) - 110 / 210) < 1e-12);
});

test("americanImpliedProbability matches repo convention for +160", () => {
  // 100/(160+100) = 0.384615...
  assert.ok(Math.abs(americanImpliedProbability(160) - 100 / 260) < 1e-12);
});

// ---------------------------------------------------------------------------
// Expected value
// ---------------------------------------------------------------------------

test("EV spec example: p=0.44 at +160 → +14.4% per unit", () => {
  const d = americanToDecimal(160);
  const ev = expectedValue(0.44, d);
  assert.ok(Math.abs(ev - 0.144) < 1e-12, `expected 0.144, got ${ev}`);
});

test("EV formula components: p(d-1) - (1-p)", () => {
  const ev = expectedValue(0.5, 2.1);
  assert.ok(Math.abs(ev - (0.5 * 1.1 - 0.5)) < 1e-12);
});

test("EV is negative when p < break-even", () => {
  assert.ok(expectedValue(0.3, 2.6) < 0);
});

test("EV at break-even is exactly 0", () => {
  const d = 2.5;
  assert.ok(Math.abs(expectedValue(1 / d, d)) < 1e-12);
});

test("probabilityEdge: p - 1/d", () => {
  assert.ok(Math.abs(probabilityEdge(0.44, 2.6) - (0.44 - 1 / 2.6)) < 1e-12);
});

test("fairDecimalOdds: p=0.44 → 2.2727...", () => {
  assert.ok(Math.abs(fairDecimalOdds(0.44) - 1 / 0.44) < 1e-12);
});

// ---------------------------------------------------------------------------
// Devig
// ---------------------------------------------------------------------------

test("devigTwoWay: -110/-110 → 50/50 with 4.762% vig", () => {
  const { pA, pB, vig } = devigTwoWay(1.9090909090909092, 1.9090909090909092);
  assert.ok(Math.abs(pA - 0.5) < 1e-12);
  assert.ok(Math.abs(pB - 0.5) < 1e-12);
  // 2*(110/210) - 1 = 10/210 = 0.047619...
  assert.ok(Math.abs(vig - 10 / 210) < 1e-12);
});

test("devigTwoWay rejects impossible vig ranges (repo [0.98,1.45] validator)", () => {
  assert.throws(() => devigTwoWay(10, 10), InvalidOddsError); // implied sum 0.2
  assert.throws(() => devigTwoWay(1.05, 1.05), InvalidOddsError); // implied sum 1.904
});

// ---------------------------------------------------------------------------
// Haircut (uncertainty margin — alerting basis only)
// ---------------------------------------------------------------------------

test("applyProbabilityHaircut shrinks the edge toward break-even by the margin", () => {
  const p = 0.44;
  const b = 1 / 2.6;
  const h = applyProbabilityHaircut(p, b, 0.5);
  assert.ok(Math.abs(h - (b + (p - b) * 0.5)) < 1e-12);
});

test("applyProbabilityHaircut with margin 0 is identity", () => {
  assert.equal(applyProbabilityHaircut(0.44, 0.3846, 0), 0.44);
});

// ---------------------------------------------------------------------------
// Text parsing (fail-safe)
// ---------------------------------------------------------------------------

test("parseAmericanOddsText handles common display formats", () => {
  assert.equal(parseAmericanOddsText("+160"), 160);
  assert.equal(parseAmericanOddsText("-110"), -110);
  assert.equal(parseAmericanOddsText("160"), 160);
  assert.equal(parseAmericanOddsText("−110"), -110); // typographic minus
  assert.equal(parseAmericanOddsText("EVEN"), 100);
  assert.equal(parseAmericanOddsText("+1,000"), 1000);
});

test("parseAmericanOddsText rejects garbage and sub-100 values", () => {
  assert.equal(parseAmericanOddsText(""), undefined);
  assert.equal(parseAmericanOddsText("Odds"), undefined);
  assert.equal(parseAmericanOddsText("N/A"), undefined);
  assert.equal(parseAmericanOddsText("+50"), undefined);
  assert.equal(parseAmericanOddsText("TBD"), undefined);
});

test("parseDecimalOddsText accepts valid decimals only", () => {
  assert.equal(parseDecimalOddsText("2.60"), 2.6);
  assert.equal(parseDecimalOddsText("1.5"), 1.5);
  assert.equal(parseDecimalOddsText("1.0"), undefined); // must be > 1
  assert.equal(parseDecimalOddsText("abc"), undefined);
});

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

test("formatAmerican produces +160 / -110 display forms", () => {
  assert.equal(formatAmerican(160), "+160");
  assert.equal(formatAmerican(-110), "-110");
  assert.equal(formatAmerican(100), "+100");
});

test("formatPercent: 0.384615 → 38.46%", () => {
  assert.equal(formatPercent(0.384615), "38.46%");
});

test("formatEvPerUnit: 0.144 → +14.4%, -0.021 → -2.1%", () => {
  assert.equal(formatEvPerUnit(0.144), "+14.4%");
  assert.equal(formatEvPerUnit(-0.021), "-2.1%");
});
