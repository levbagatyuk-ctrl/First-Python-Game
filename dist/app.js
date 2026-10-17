'use strict';
const frame = document.getElementById('game');
const gameWrap = document.getElementById('game-wrap');
const fullscreen = document.getElementById('fullscreen');
document.getElementById('focus').addEventListener('click', () => {
  frame.scrollIntoView({ block: 'center' });
  try { frame.contentWindow.focus(); } catch {}
});
gameWrap.addEventListener('click', () => {
  try { frame.contentWindow.focus(); } catch {}
});
frame.addEventListener('load', () => {
  try { frame.contentWindow.focus(); } catch {}
});
fullscreen.addEventListener('click', async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if (gameWrap.requestFullscreen) await gameWrap.requestFullscreen();
    else { window.open('game/index.html', '_blank', 'noopener'); return; }
    frame.contentWindow.focus();
  } catch {
    fullscreen.textContent = 'Повний екран недоступний';
  }
});
document.addEventListener('fullscreenchange', () => {
  fullscreen.textContent = document.fullscreenElement ? 'Вийти з повного екрана ⛶' : 'На весь екран ⛶';
});
document.getElementById('reload').addEventListener('click', () => {
  frame.src = 'game/index.html';
  gameWrap.scrollIntoView({ block: 'center' });
});
