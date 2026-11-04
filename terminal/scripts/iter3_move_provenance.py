#!/usr/bin/env python3
"""Iteration 3 — move Quote provenance from the rail into the primary column.

Balances the main grid: distribution + provenance (primary) vs factors +
links (rail), eliminating the ~390px empty gap under the distribution panel.
"""
PATH = "src/components/propstein/PlayerResearchPage.tsx"

src = open(PATH, encoding="utf-8").read()

# ---------- extract the provenance panel from the rail ----------
start_marker = "          {/* quote provenance & status */}\n"
start = src.index(start_marker)
end_marker = "          {/* links */}\n"
end = src.index(end_marker)
block = src[start:end]
assert "Quote provenance" in block and "STALE" in block, "provenance block extraction failed"

# remove from the rail
src = src[:start] + src[end:]

# ---------- insert into the primary column, after the distribution panel ----------
anchor = "        </div>\n\n        {/* ——— research rail ——— */}"
assert anchor in src, "primary column close anchor not found"
# dedent the block one level (10 -> 8 spaces) and widen padding on desktop
block_new = "\n".join(
    (line[2:] if line.startswith("          ") else line) for line in block.splitlines()
).rstrip() + "\n"
block_new = block_new.replace(
    '<Panel className="order-2 p-4 lg:order-none">',
    '<Panel className="order-2 p-4 lg:order-none lg:p-5">',
)
insertion = "        " + block_new.lstrip().rstrip() + "\n\n"
src = src.replace(anchor, insertion + anchor, 1)

open(PATH, "w", encoding="utf-8").write(src)
print("provenance moved OK")
