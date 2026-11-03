import sharp from 'sharp';
import fs from 'fs';
import path from 'path';

const sourceImgPath = '/Users/nick/.gemini/antigravity-ide/brain/864b77c4-bb96-486d-b389-ad501875d808/.user_uploaded/media_1792527894248.png';
if (!fs.existsSync(sourceImgPath)) {
  console.error('Source logo file not found:', sourceImgPath);
  process.exit(1);
}

// 1. Load source image and blend background seamlessly into #090d16
const img = sharp(sourceImgPath);
const { data, info } = await img.raw().toBuffer({ resolveWithObject: true });
const targetR = 9, targetG = 13, targetB = 22; // #090d16

for (let i = 0; i < data.length; i += info.channels) {
  const r = data[i], g = data[i + 1], b = data[i + 2];
  const brightness = Math.max(r, g, b);
  if (brightness < 35) {
    data[i] = targetR;
    data[i + 1] = targetG;
    data[i + 2] = targetB;
  } else if (brightness < 80) {
    const t = (brightness - 35) / (80 - 35);
    data[i] = Math.round(targetR * (1 - t) + r * t);
    data[i + 1] = Math.round(targetG * (1 - t) + g * t);
    data[i + 2] = Math.round(targetB * (1 - t) + b * t);
  }
}

// 2. Extract bounding region with balanced margins so iOS squircle mask never clips the mark
// Bounding box of content: X: 201 to 876 (width 675), Y: 132 to 835 (height 703)
const master512 = await sharp(data, {
  raw: { width: info.width, height: info.height, channels: info.channels }
})
  .extract({ left: 180, top: 110, width: 720, height: 740 })
  .resize(410, 420, { fit: 'contain', background: '#090d16' })
  .extend({
    top: 46,
    bottom: 46,
    left: 51,
    right: 51,
    background: '#090d16'
  })
  .resize(512, 512)
  .png()
  .toBuffer();

const targetDirs = ['viewer', 'public'];

for (const dir of targetDirs) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  // Standard iOS Apple Touch Icons (180x180, 152x152, 167x167, 120x120)
  await sharp(master512).resize(180, 180).png().toFile(path.join(dir, 'apple-touch-icon.png'));
  await sharp(master512).resize(180, 180).png().toFile(path.join(dir, 'apple-touch-icon-precomposed.png'));
  await sharp(master512).resize(180, 180).png().toFile(path.join(dir, 'apple-touch-icon-180x180.png'));
  await sharp(master512).resize(180, 180).png().toFile(path.join(dir, 'apple-touch-icon-180x180-precomposed.png'));
  await sharp(master512).resize(152, 152).png().toFile(path.join(dir, 'apple-touch-icon-152x152.png'));
  await sharp(master512).resize(167, 167).png().toFile(path.join(dir, 'apple-touch-icon-167x167.png'));
  await sharp(master512).resize(120, 120).png().toFile(path.join(dir, 'apple-touch-icon-120x120.png'));

  // PWA & Android Icons
  await sharp(master512).resize(192, 192).png().toFile(path.join(dir, 'icon-192.png'));
  await sharp(master512).resize(512, 512).png().toFile(path.join(dir, 'icon-512.png'));

  // Desktop Favicons
  await sharp(master512).resize(32, 32).png().toFile(path.join(dir, 'favicon-32x32.png'));
  await sharp(master512).resize(16, 16).png().toFile(path.join(dir, 'favicon-16x16.png'));
  await sharp(master512).resize(32, 32).png().toFile(path.join(dir, 'favicon.png'));
}

console.log('✔ Successfully generated all authentic iOS, PWA, and desktop favicons from user mark');
