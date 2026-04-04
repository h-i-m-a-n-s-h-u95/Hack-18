import axios from 'axios';

// ─── API Base ────────────────────────────────────────────────
const api = axios.create({
  baseURL: '/api/v2/orchestrator',
  headers: { 'Content-Type': 'application/json' },
});

// ─── Build natural-language query from form fields ──────────
export function buildQueryFromForm(formData) {
  const {
    origin,
    destination,
    travel_dates,
    travelers_count,
    budget_range,
    preferences,
    include_travel_options,
  } = formData;

  const dateCount = travel_dates?.length ?? 0;
  const dateRange =
    dateCount > 0
      ? `from ${travel_dates[0]} to ${travel_dates[dateCount - 1]}`
      : '';

  const budgetLabel =
    budget_range === 'low'
      ? 'a budget-friendly'
      : budget_range === 'high'
        ? 'a luxury'
        : 'a moderate';

  let query = `Plan a ${dateCount}-day trip to ${destination}`;
  if (origin) query += ` from ${origin}`;
  if (dateRange) query += ` ${dateRange}`;
  query += ` for ${travelers_count} ${travelers_count === 1 ? 'person' : 'people'}`;
  query += ` with ${budgetLabel} budget.`;

  if (preferences) query += ` Preferences: ${preferences}.`;
  if (include_travel_options) query += ' Include flight, train, and hotel options.';

  return query;
}

// ─── Start a travel plan ────────────────────────────────────
export async function startPlan(query, sessionId = null) {
  const { data } = await api.post('/plan', {
    query,
    session_id: sessionId,
  });
  return data; // { session_id, status, message, websocket_url, query }
}

// ─── Poll session status (fallback) ─────────────────────────
export async function getPlanStatus(sessionId) {
  const { data } = await api.get(`/plan/${sessionId}/status`);
  return data;
}

// ─── Fetch completed result ─────────────────────────────────
export async function getSessionResult(sessionId) {
  const { data } = await api.get(`/session/${sessionId}/result`);
  return data;
}

// ─── WebSocket helper ───────────────────────────────────────
/**
 * Opens a WebSocket to the orchestrator streaming endpoint.
 * Returns an object with { ws, close } so the caller can clean up.
 *
 * @param {string} sessionId
 * @param {(msg: object) => void} onMessage
 * @param {(err: Event) => void} [onError]
 * @param {() => void} [onClose]
 */
export function connectWebSocket(sessionId, onMessage, onError, onClose) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${protocol}://${window.location.host}/ws/${sessionId}`;

  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log(`[WS] Connected for session ${sessionId}`);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      onMessage(msg);
    } catch {
      console.warn('[WS] Non-JSON message:', event.data);
    }
  };

  ws.onerror = (err) => {
    console.error('[WS] Error:', err);
    onError?.(err);
  };

  ws.onclose = () => {
    console.log('[WS] Disconnected');
    onClose?.();
  };

  return {
    ws,
    close: () => ws.close(),
  };
}
