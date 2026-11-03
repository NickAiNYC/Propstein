/**
 * PropStein Live Sniper — Visibility Filtering (pure logic)
 * =======================================================
 * Decides whether a market element is ACTUALLY visible to the user.
 * Pure functions over geometry + CSS flags — no DOM dependency, so every
 * rule is unit-testable and identical across Chrome and Safari.
 *
 * An element is visible only when ALL hold:
 *  - its bounding rectangle intersects the viewport by at least
 *    `minIntersectionRatio` of its own area,
 *  - CSS does not hide it (display/visibility/opacity/content-visibility),
 *  - it has non-zero size,
 *  - (optional) the occlusion check did not report it covered.
 *
 * Existence in the DOM is NEVER treated as visibility (spec §4.1).
 */

export interface RectLike {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface ViewportLike {
  width: number;
  height: number;
  /** Scroll offsets when the caller wants window-absolute geometry. */
  scrollX?: number;
  scrollY?: number;
}

export interface StyleFlags {
  display?: string;
  visibility?: string;
  opacity?: number;
  contentVisibility?: string;
  /** Element hidden behind a modal/overlay per a caller-side hit test. */
  occluded?: boolean;
}

export interface VisibilityDecision {
  visible: boolean;
  intersectionRatio: number;
  reasons: string[];
}

/** Fraction of the element's own area that overlaps the viewport. */
export function intersectionRatio(rect: RectLike, viewport: ViewportLike): number {
  const area = rectArea(rect);
  if (area <= 0) return 0;
  const overlapWidth = Math.max(0, Math.min(rect.right, viewport.width) - Math.max(rect.left, 0));
  const overlapHeight = Math.max(0, Math.min(rect.bottom, viewport.height) - Math.max(rect.top, 0));
  return clamp01((overlapWidth * overlapHeight) / area);
}

function rectArea(r: RectLike): number {
  return Math.max(0, r.right - r.left) * Math.max(0, r.bottom - r.top);
}

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

/** CSS-level visibility. */
export function isStyleVisible(style: StyleFlags): boolean {
  if (style.display === "none") return false;
  if (style.visibility === "hidden" || style.visibility === "collapse") return false;
  if (style.opacity !== undefined && style.opacity <= 0.01) return false;
  if (style.contentVisibility === "hidden") return false;
  return true;
}

/**
 * Full visibility decision for a candidate market element.
 * `minIntersectionRatio` is typically 0.5 for market cards — a card half
 * scrolled off-screen is still being read by the user.
 */
export function decideVisibility(
  rect: RectLike,
  viewport: ViewportLike,
  style: StyleFlags,
  minIntersectionRatio = 0.5,
): VisibilityDecision {
  const reasons: string[] = [];
  if (!isStyleVisible(style)) {
    reasons.push(`hidden by CSS (display=${style.display ?? "?"}, visibility=${style.visibility ?? "?"}, opacity=${style.opacity ?? "?"})`);
    return { visible: false, intersectionRatio: 0, reasons };
  }
  if (rectArea(rect) <= 0) {
    reasons.push("zero-area bounding rectangle");
    return { visible: false, intersectionRatio: 0, reasons };
  }
  const ratio = intersectionRatio(rect, viewport);
  if (ratio < minIntersectionRatio) {
    reasons.push(`viewport intersection ${(ratio * 100).toFixed(1)}% below required ${(minIntersectionRatio * 100).toFixed(0)}%`);
    return { visible: false, intersectionRatio: ratio, reasons };
  }
  if (style.occluded) {
    reasons.push("element is occluded by an overlay/modal hit-test");
    return { visible: false, intersectionRatio: ratio, reasons };
  }
  return { visible: true, intersectionRatio: ratio, reasons: [] };
}

/**
 * Re-observation policy for virtualized lists: when a list virtualizes
 * (elements destroyed/recreated on scroll), the pipeline must re-run
 * detection rather than trust stale element references.
 */
export function shouldRedetectAfterMutation(
  mutationAffectsMarketContainer: boolean,
  previousElementsStillConnected: boolean,
): boolean {
  return mutationAffectsMarketContainer || !previousElementsStillConnected;
}
