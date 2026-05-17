// Visualizer page — polls /api/sim/frame.png at 1Hz, paints onto the canvas.

const canvas = document.getElementById('wall-canvas');
const ctx = canvas.getContext('2d');
const status = document.getElementById('viz-status');
const wall = document.getElementById('wall');
const bezelGrid = document.getElementById('bezel-grid');
const zoomSel = document.getElementById('viz-zoom');

// Populate bezel grid (24 cells)
for (let i = 0; i < 24; i++) bezelGrid.appendChild(document.createElement('div'));

function applyZoom() {
  const z = parseInt(zoomSel.value, 10);
  wall.style.transform = `scale(${z})`;
  // Reserve space proportionally so the wrapper centers it correctly.
  wall.style.width = '384px';
  wall.style.height = '256px';
  wall.style.marginRight = `${(z - 1) * 384}px`;
  wall.style.marginBottom = `${(z - 1) * 256}px`;
}
zoomSel.addEventListener('change', applyZoom);
applyZoom();

let lastFrameNo = -1;
let pendingImg = null;

async function poll() {
  try {
    const res = await fetch('/api/sim/frame.png?_=' + Date.now(), { cache: 'no-store' });
    if (!res.ok) {
      status.textContent = `error: HTTP ${res.status}`;
      return;
    }
    const frameNo = parseInt(res.headers.get('X-Frame-Number') || '0', 10);
    const ageMs = parseInt(res.headers.get('X-Frame-Age-Ms') || '-1', 10);
    if (frameNo === lastFrameNo && lastFrameNo > 0) {
      status.textContent = `frame #${frameNo} (${(ageMs / 1000).toFixed(1)}s old)`;
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      if (frameNo > 0) {
        status.textContent = `frame #${frameNo} (live)`;
        lastFrameNo = frameNo;
      } else {
        status.textContent = 'waiting for first frame…';
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      status.textContent = 'frame decode error';
    };
    img.src = url;
  } catch (e) {
    status.textContent = `poll error: ${e.message || e}`;
  }
}

poll();
setInterval(poll, 1000);
