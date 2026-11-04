#!/usr/bin/env python3
"""Merge cover + body into the final specification PDF, normalized to A4."""

from pypdf import PdfReader, PdfWriter

A4_W, A4_H = 595.28, 841.89

def normalize_page_to_a4(page):
    box = page.mediabox
    w, h = float(box.width), float(box.height)
    if abs(w - A4_W) > 0.1 or abs(h - A4_H) > 0.1:
        page.scale_to(A4_W, A4_H)
    return page


writer = PdfWriter()
cover_page = PdfReader('/home/z/my-project/scripts/pdf-export/cover.pdf').pages[0]
writer.add_page(normalize_page_to_a4(cover_page))
for page in PdfReader('/home/z/my-project/scripts/pdf-export/spec-body.pdf').pages:
    writer.add_page(normalize_page_to_a4(page))
writer.add_metadata({
    '/Title': 'PropStein Evidence-First Research Terminal Specification',
    '/Author': 'Z.ai',
    '/Creator': 'Z.ai',
    '/Subject': 'Evidence-first sports-prop research and record-keeping product specification',
})
out = '/home/z/my-project/download/PropStein-Specification.pdf'
with open(out, 'wb') as f:
    writer.write(f)
print('merged ->', out, 'pages:', len(writer.pages))
