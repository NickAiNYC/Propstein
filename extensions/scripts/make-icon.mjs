/**
 * Minimal neutral PNG icon generator (fallback when the repo's existing
 * extension icons are unavailable). Produces a solid obsidian tile with a
 * baby-blue marker pixel pattern — explicitly a placeholder, to be replaced
 * by branded icons before any store submission.
 */

function crc32(buf) {
  let c;
  const table = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const typeBuf = Buffer.from(type, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])));
  return Buffer.concat([len, typeBuf, data, crc]);
}

export function neutralIconPng(size) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  const rows = [];
  const bg = [7, 7, 8, 255];
  const accent = [125, 211, 252, 255];
  for (let y = 0; y < size; y++) {
    const row = Buffer.alloc(1 + size * 4);
    row[0] = 0; // filter none
    for (let x = 0; x < size; x++) {
      const border = x === 0 || y === 0 || x === size - 1 || y === size - 1;
      const mark = x > size * 0.3 && x < size * 0.7 && y > size * 0.3 && y < size * 0.7;
      const px = mark ? accent : bg;
      const off = 1 + (x * 4);
      row[off] = border ? 125 : px[0];
      row[off + 1] = border ? 211 : px[1];
      row[off + 2] = border ? 252 : px[2];
      row[off + 3] = 255;
    }
    rows.push(row);
  }
  const idat = chunk("IDAT", zlibDeflate(Buffer.concat(rows)));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    idat,
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

import { deflateSync as zlibDeflate } from "node:zlib";
