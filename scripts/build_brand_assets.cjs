// Developer-only vector rendering. Runtime loads bundled PNG/ICO files.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');

const root = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
function option(name, fallback) {
  const index = args.indexOf(name);
  return index < 0 ? fallback : args[index + 1];
}
const source = path.resolve(option('--source', path.join(root, 'assets/brand/replay-mark.svg')));
const output = path.resolve(option('--output-dir', path.join(root, 'assets/brand')));
const modulePath = path.resolve(option('--playwright', path.join(root, '../dotabased/node_modules/playwright')));
const { chromium } = createRequire(__filename)(modulePath);

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const svg = fs.readFileSync(source, 'utf8');
    const images = [];
    for (const size of [16, 24, 32, 48, 64, 128, 256, 512]) {
      const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
      await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:100vw;height:100vh}</style>${svg}`);
      const png = await page.screenshot({ omitBackground: true });
      fs.writeFileSync(path.join(output, `replay-mark-${size}.png`), png);
      if (size <= 256) images.push({ size, png });
      await page.close();
    }
    // Modern Windows ICO supports PNG frames, preserving the SVG's alpha edges.
    const header = Buffer.alloc(6 + images.length * 16);
    header.writeUInt16LE(1, 2);
    header.writeUInt16LE(images.length, 4);
    let offset = header.length;
    images.forEach(({ size, png }, index) => {
      const base = 6 + index * 16;
      header[base] = header[base + 1] = size === 256 ? 0 : size;
      header.writeUInt16LE(1, base + 4);
      header.writeUInt16LE(32, base + 6);
      header.writeUInt32LE(png.length, base + 8);
      header.writeUInt32LE(offset, base + 12);
      offset += png.length;
    });
    fs.writeFileSync(path.join(output, 'replay.ico'), Buffer.concat([header, ...images.map(image => image.png)]));
    console.log(`Rendered ${images.length} ICO frames and eight PNG sizes from ${source}`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
