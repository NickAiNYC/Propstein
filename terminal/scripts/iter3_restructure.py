#!/usr/bin/env python3
"""Iteration 3 — restructure PlayerResearchPage to the mockup's bottom grid.

Moves the Recent Trends panel and the Model Details / Context panels out of
the primary column into a full-width three-column bottom research grid
(mockup: Trends | Model Details | Context), placed after the main
distribution+rail grid.

Text surgery with explicit markers + assertions — fails loudly if the file
drifts.
"""
import re
import sys

PATH = "src/components/propstein/PlayerResearchPage.tsx"

src = open(PATH, encoding="utf-8").read()

# ---------- 1. extract the trends panel block (primary column) ----------
trends_start = src.index("          {/* recent trends — market-peekable tabs + bar log */}")
trends_end_marker = "          </Panel>\n\n          {/* bottom research grid — model details + context */}"
trends_end = src.index(trends_end_marker)
trends_block = src[trends_start:trends_end + len("          </Panel>\n")]
assert "RecentTrendsChart" in trends_block, "trends block extraction failed"

# ---------- 2. extract the details/context grid block ----------
grid_start_marker = "          {/* bottom research grid — model details + context */}\n          <div className=\"order-6 grid grid-cols-1 gap-3 lg:order-none lg:grid-cols-2\">\n"
grid_start = src.index(grid_start_marker)
aside_marker = "        {/* ——— research rail ——— */}"
grid_end = src.index(aside_marker)
grid_block = src[grid_start:grid_end]
assert "Implied mean" in grid_block and "Context metrics are deterministic" in grid_block, "grid block extraction failed"

# unwrap: strip the old wrapper div + trailing closers up to the aside
# grid_block currently: <div order-6 ...> ...panels... </div>\n      </div>\n\n
inner = grid_block[len(grid_start_marker):]
# remove the wrapper's closing </div> and the primary column's closing </div>
tail = "          </div>\n        </div>\n\n"
assert inner.endswith(tail), f"unexpected tail: {inner[-80:]!r}"
inner_panels = inner[: -len(tail)]  # the two Panel blocks with their indentation

# ---------- 3. remove both blocks from the primary column ----------
src = src[:trends_start] + "        </div>\n\n" + src[grid_end:]
# NOTE: the primary column now closes right after the distribution panel;
# the old "        </div>\n" closer that preceded the aside is preserved by
# the inserted text above (we replaced the whole span with just the closer).

# sanity: primary column contains only the distribution panel now
seg = src[src.index('className="contents lg:flex lg:min-w-0 lg:flex-col lg:gap-5"'):src.index("{/* ——— research rail ——— */}")]
assert "RecentTrendsChart" not in seg and "Model details" not in seg, "primary column still carries moved panels"

# ---------- 4. re-indent panels for the bottom grid ----------
# trends block: dedent one level (10 spaces -> 8)
trends_block_new = "\n".join(
    (line[2:] if line.startswith("          ") else line) for line in trends_block.splitlines()
)
trends_block_new = trends_block_new.replace(
    '<Panel className="order-4 p-4 lg:order-none lg:p-5">',
    '<Panel className="p-4 lg:p-5">',
)
# inner panels (details/context): dedent one level (10 -> 8)
inner_new = "\n".join(
    (line[2:] if line.startswith("          ") else line) for line in inner_panels.splitlines()
)
inner_new = inner_new.rstrip() + "\n"

# ---------- 5. insert the bottom research grid before <ShareLinkButton /> ----------
bottom_grid = (
    "      {/* ——— bottom research grid (mockup: three balanced columns) ———\n"
    "          Recent Trends · Model Details · Context, full width under the\n"
    "          distribution + rail section. */}\n"
    "      <div className=\"grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3\">\n"
    + trends_block_new.rstrip() + "\n\n"
    + inner_new
    + "      </div>\n\n"
)
anchor = "      {/* floating deep-link share (desktop) */}\n      <ShareLinkButton />"
assert anchor in src, "share button anchor missing"
src = src.replace(anchor, bottom_grid + anchor)

open(PATH, "w", encoding="utf-8").write(src)
print("restructured OK")
print("trends block lines:", trends_block_new.count("\n"))
print("details/context lines:", inner_new.count("\n"))
