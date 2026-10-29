import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const sw = readFileSync('public/sw.js', 'utf8');

test('service worker shows pushes and only opens internal routes', () => {
  assert.match(sw, /addEventListener\('push'/);
  assert.match(sw, /showNotification\(/);
  assert.match(sw, /startsWith\('\/'\) && !data\.url\.startsWith\('\/\/'\)/);
  assert.match(sw, /addEventListener\('notificationclick'/);
});

test('push handler never touches caches or the network', () => {
  const push = sw.slice(sw.indexOf("addEventListener('push'"));
  assert.doesNotMatch(push, /caches\.|fetch\(/);
});
