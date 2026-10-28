// Smoke de carga del backend (APP_ENV=test, sqlite). 0 EUR: runner gratis.
// No gatea merges: corre de noche y a mano; umbrales conservadores sobre
// /health y un endpoint real. Numeros de CI son indicativos (runner compartido).
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 10,
  duration: '30s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<800'],
  },
};

const BASE = __ENV.E2E_API_URL || 'http://127.0.0.1:8100';

export default function () {
  const health = http.get(`${BASE}/health`);
  check(health, { 'health 200': (r) => r.status === 200 });
  sleep(0.2);
}
