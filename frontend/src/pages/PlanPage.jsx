import { useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useState, useRef, useCallback } from 'react';
import {
  Loader2,
  MapPin,
  CalendarDays,
  Users,
  Map as MapIcon,
  CloudRain,
  Banknote,
  Navigation,
  Sparkles,
  CheckCircle2,
  XCircle,
  Clock,
  ArrowLeft,
  Ticket,
  AlertTriangle,
} from 'lucide-react';

import {
  buildQueryFromForm,
  startPlan,
  getSessionResult,
  getPlanStatus,
  connectWebSocket,
} from '../services/api';

// ─── Agent metadata for UI ──────────────────────────────────
const AGENT_META = {
  weather: { icon: CloudRain, label: 'Sky Gazer — Weather', color: 'text-blue-500', bg: 'bg-blue-50', border: 'border-blue-200' },
  events:  { icon: Ticket,    label: 'Buzzfinder — Events', color: 'text-purple-500', bg: 'bg-purple-50', border: 'border-purple-200' },
  maps:    { icon: MapIcon,   label: 'Trailblazer — Maps',  color: 'text-emerald-500', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  budget:  { icon: Banknote,  label: 'Quartermaster — Budget', color: 'text-orange-500', bg: 'bg-orange-50', border: 'border-orange-200' },
  itinerary: { icon: Sparkles, label: 'Chronomancer — Itinerary', color: 'text-pink-500', bg: 'bg-pink-50', border: 'border-pink-200' },
};

// ═══════════════════════════════════════════════════════════════
export default function PlanPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const wsRef = useRef(null);

  // Phases: 'streaming' → 'done' | 'error'
  const [phase, setPhase] = useState('streaming');
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('Initializing…');
  const [agentStatuses, setAgentStatuses] = useState({});
  const [streamMessages, setStreamMessages] = useState([]);
  const [result, setResult] = useState(null);
  const [sessionId, setSessionId] = useState(null);

  const requestData = location.state?.requestData;

  // ─── Finalize: fetch full result from REST endpoint ───────
  const finalize = useCallback(async (sid) => {
    try {
      const data = await getSessionResult(sid);
      setResult(data);
      setPhase('done');
    } catch (err) {
      console.error('Failed to fetch result:', err);
      // If the result fetch fails, try polling status
      try {
        const status = await getPlanStatus(sid);
        if (status && status.workflow_status === 'completed') {
          // Status says complete, try result one more time
          const data = await getSessionResult(sid);
          setResult(data);
          setPhase('done');
        } else {
          setResult(status);
          setPhase('done');
        }
      } catch {
        setError('Plan completed but could not fetch results. Please try again.');
        setPhase('error');
      }
    }
  }, []);

  // ─── WS message handler ───────────────────────────────────
  const handleWSMessage = useCallback(
    (msg) => {
      // Append to live log
      if (msg.message) {
        setStreamMessages((prev) => [
          ...prev.slice(-49), // keep last 50 messages
          { text: msg.message, agent: msg.agent, ts: msg.timestamp, type: msg.type },
        ]);
      }

      // Update agent statuses
      if (msg.type === 'agent_start') {
        setAgentStatuses((prev) => ({ ...prev, [msg.agent]: 'processing' }));
      } else if (msg.type === 'agent_update') {
        setAgentStatuses((prev) => ({ ...prev, [msg.agent]: 'completed' }));
      } else if (msg.type === 'error' && msg.agent !== 'orchestrator') {
        setAgentStatuses((prev) => ({ ...prev, [msg.agent]: 'failed' }));
      }

      // Update overall progress
      if (msg.progress_percent != null) {
        setProgress(msg.progress_percent);
      }

      // Update status message
      if (msg.message) {
        setStatusMessage(msg.message);
      }

      // Workflow completed → fetch full result
      if (msg.type === 'completed') {
        setProgress(100);
        setStatusMessage('Plan completed! Loading results…');
        // small delay so the user sees 100 %
        setTimeout(() => finalize(msg.session_id || sessionId), 600);
      }

      // Fatal error from orchestrator
      if (msg.type === 'error' && msg.agent === 'orchestrator') {
        setError(msg.message || 'An unexpected error occurred.');
        setPhase('error');
      }
    },
    [finalize, sessionId],
  );

  // ─── Kick off the plan ────────────────────────────────────
  useEffect(() => {
    if (!requestData) {
      navigate('/');
      return;
    }

    let cancelled = false;
    let pollTimer = null;

    const run = async () => {
      try {
        // 1. Build NL query
        const query = buildQueryFromForm(requestData);

        // 2. Start the plan (POST)
        const { session_id } = await startPlan(query);
        if (cancelled) return;
        setSessionId(session_id);

        // 3. Connect WebSocket for streaming
        const { close } = connectWebSocket(
          session_id,
          (msg) => handleWSMessage(msg),
          () => {}, // onError – we handle via polling fallback
          () => {},   // onClose
        );
        wsRef.current = close;

        // 4. Polling fallback – if WS doesn't send 'completed' within 5 min, poll REST
        pollTimer = setTimeout(async () => {
          if (cancelled) return;
          try {
            const status = await getPlanStatus(session_id);
            if (status?.workflow_status === 'completed') {
              finalize(session_id);
            }
          } catch {
            // ignore
          }
        }, 300_000);
      } catch (err) {
        if (!cancelled) {
          setError(err?.response?.data?.detail || err.message || 'Failed to start plan');
          setPhase('error');
        }
      }
    };

    run();

    return () => {
      cancelled = true;
      wsRef.current?.();
      if (pollTimer) clearTimeout(pollTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // only run once on mount

  // ═══════════════════════════════════════════════════════════
  //  RENDER: Streaming / Progress
  // ═══════════════════════════════════════════════════════════
  if (phase === 'streaming') {
    return (
      <div className="flex-1 flex flex-col items-center justify-start bg-slate-50 pt-12 px-4 min-h-[80vh]">
        <div className="w-full max-w-2xl space-y-8">
          {/* Progress header */}
          <div className="bg-white rounded-3xl p-8 border border-slate-200 shadow-sm text-center space-y-4">
            <div className="relative inline-flex items-center justify-center mb-2">
              <div className="absolute inset-0 bg-brand-200 blur-2xl rounded-full animate-pulse" />
              <Loader2 className="w-14 h-14 text-brand-600 animate-spin relative z-10" />
            </div>
            <h2 className="text-2xl font-bold text-slate-900">{statusMessage}</h2>

            {/* Progress bar */}
            <div className="relative w-full h-3 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="absolute inset-y-0 left-0 bg-gradient-to-r from-brand-500 to-indigo-500 rounded-full transition-all duration-700 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-sm text-slate-400 font-medium">{progress}% complete</p>
          </div>

          {/* Agent cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {Object.entries(AGENT_META).map(([key, meta]) => {
              const status = agentStatuses[key];
              const Icon = meta.icon;
              return (
                <div
                  key={key}
                  className={`flex items-center gap-4 p-4 rounded-2xl border transition-all duration-500 ${
                    status === 'completed'
                      ? `${meta.bg} ${meta.border} border-2`
                      : status === 'processing'
                        ? 'bg-white border-brand-300 border-2 shadow-md animate-pulse'
                        : status === 'failed'
                          ? 'bg-red-50 border-red-200'
                          : 'bg-white border-slate-200'
                  }`}
                >
                  <div className={`p-2 rounded-xl ${status === 'completed' ? meta.bg : 'bg-slate-100'}`}>
                    <Icon className={`w-5 h-5 ${status === 'completed' ? meta.color : status === 'processing' ? 'text-brand-500' : 'text-slate-400'}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-semibold truncate ${status === 'completed' ? 'text-slate-800' : 'text-slate-600'}`}>
                      {meta.label}
                    </p>
                    <p className="text-xs text-slate-400 capitalize">{status || 'waiting'}</p>
                  </div>
                  {status === 'completed' && <CheckCircle2 className="w-5 h-5 text-green-500 flex-shrink-0" />}
                  {status === 'processing' && <Loader2 className="w-5 h-5 text-brand-500 animate-spin flex-shrink-0" />}
                  {status === 'failed' && <XCircle className="w-5 h-5 text-red-400 flex-shrink-0" />}
                  {!status && <Clock className="w-4 h-4 text-slate-300 flex-shrink-0" />}
                </div>
              );
            })}
          </div>

          {/* Live log */}
          {streamMessages.length > 0 && (
            <div className="bg-slate-900 rounded-2xl p-5 text-sm font-mono text-slate-300 max-h-48 overflow-y-auto space-y-1">
              {streamMessages.map((m, i) => (
                <p key={i} className="leading-relaxed">
                  <span className="text-slate-500 mr-2">[{m.agent}]</span>
                  <span className={m.type === 'error' ? 'text-red-400' : m.type === 'completed' ? 'text-green-400' : ''}>{m.text}</span>
                </p>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════
  //  RENDER: Error
  // ═══════════════════════════════════════════════════════════
  if (phase === 'error') {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <div className="bg-red-50 border border-red-200 p-8 rounded-3xl max-w-lg text-center space-y-4">
          <AlertTriangle className="w-12 h-12 text-red-500 mx-auto" />
          <h3 className="text-red-800 font-bold text-xl">Trip Planning Failed</h3>
          <p className="text-red-600">{error}</p>
          <button
            onClick={() => navigate('/')}
            className="px-6 py-3 bg-red-600 text-white rounded-xl hover:bg-red-700 font-semibold transition-colors inline-flex items-center gap-2"
          >
            <ArrowLeft className="w-4 h-4" /> Try Again
          </button>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════
  //  RENDER: Results
  // ═══════════════════════════════════════════════════════════
  if (!result) return null;

  // ─── Data extraction helpers ──────────────────────────────
  const weatherData = extractWeather(result);
  const routeData = extractRoute(result);
  const budgetData = extractBudget(result);
  const itineraryDays = extractItinerary(result);
  const eventsData = extractEvents(result);

  return (
    <div className="flex-1 bg-slate-50 py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-6xl mx-auto space-y-8">
        {/* Header */}
        <div className="bg-white rounded-3xl p-8 border border-slate-200 shadow-sm flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
          <div>
            <h1 className="text-3xl font-black tracking-tight text-slate-900 mb-2 flex items-center gap-3">
              <MapPin className="text-brand-600 w-8 h-8" />
              {requestData?.origin && <>{requestData.origin} <Navigation className="text-slate-300 w-5 h-5 inline rotate-90" /></>}{' '}
              {result.destination || requestData?.destination || 'Your Trip'}
            </h1>
            <div className="flex flex-wrap items-center gap-4 text-sm text-slate-600 font-medium">
              {result.travel_dates?.length > 0 && (
                <div className="flex items-center gap-1.5 bg-slate-100 px-3 py-1.5 rounded-lg">
                  <CalendarDays className="w-4 h-4 text-brand-500" />
                  {result.travel_dates[0]} — {result.travel_dates[result.travel_dates.length - 1]}
                </div>
              )}
              {requestData?.travelers_count && (
                <div className="flex items-center gap-1.5 bg-slate-100 px-3 py-1.5 rounded-lg">
                  <Users className="w-4 h-4 text-brand-500" />
                  {requestData.travelers_count} Traveler{requestData.travelers_count > 1 ? 's' : ''}
                </div>
              )}
              {requestData?.budget_range && (
                <div className="flex items-center gap-1.5 bg-slate-100 px-3 py-1.5 rounded-lg capitalize">
                  <Banknote className="w-4 h-4 text-brand-500" />
                  {requestData.budget_range} Budget
                </div>
              )}
            </div>
          </div>
          <button
            onClick={() => navigate('/')}
            className="px-5 py-2.5 bg-white border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 rounded-xl font-medium transition-colors text-sm inline-flex items-center gap-2"
          >
            <ArrowLeft className="w-4 h-4" /> Edit Trip
          </button>
        </div>

        {/* Errors / warnings */}
        {result.errors?.length > 0 && (
          <div className="bg-yellow-50 border border-yellow-200 p-4 rounded-2xl text-sm text-yellow-800 space-y-1">
            <p className="font-semibold flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> Some agents encountered issues:</p>
            {result.errors.map((e, i) => <p key={i} className="ml-6">• {e}</p>)}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* ─── Main Column ─── */}
          <div className="lg:col-span-2 space-y-6">
            {/* Itinerary */}
            <h2 className="text-2xl font-bold text-slate-900 mb-6 border-b border-slate-200 pb-4">
              Daily Itinerary
            </h2>
            {itineraryDays.length === 0 ? (
              <p className="text-slate-500 bg-white p-6 rounded-2xl border border-slate-200 text-center">
                No detailed itinerary was generated. The request may not have included enough details, or the itinerary agent may have timed out.
              </p>
            ) : (
              <div className="space-y-8">
                {itineraryDays.map((day, i) => (
                  <div key={i} className="relative pl-8 md:pl-0">
                    <div className="hidden md:block absolute left-[31px] top-10 bottom-[-32px] w-0.5 bg-slate-200" />
                    <div className="flex flex-col md:flex-row gap-6">
                      <div className="md:w-16 flex-shrink-0 pt-1 relative z-10 hidden md:block">
                        <div className="w-16 h-16 bg-brand-50 text-brand-700 rounded-2xl flex flex-col items-center justify-center font-bold border border-brand-100 shadow-sm">
                          <span className="text-xs uppercase tracking-wider text-brand-500/80 mb-0.5">Day</span>
                          <span className="text-xl leading-none">{day.day}</span>
                        </div>
                      </div>
                      <div className="flex-1 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
                        <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center md:hidden">
                          <span className="bg-brand-100 text-brand-700 px-2 py-1 rounded-md text-sm mr-3">Day {day.day}</span>
                          {day.date}
                        </h3>
                        <h3 className="font-semibold text-slate-800 mb-4 hidden md:block">{day.date || `Day ${day.day}`}</h3>
                        <div className="space-y-4">
                          {day.activities.map((activity, j) => (
                            <div key={j} className="flex gap-4 p-4 rounded-xl bg-slate-50 border border-slate-100 hover:border-brand-200 hover:bg-brand-50/30 transition-colors">
                              <div className="w-1.5 h-1.5 rounded-full bg-brand-400 mt-2 flex-shrink-0" />
                              <p className="text-slate-700">{activity}</p>
                            </div>
                          ))}
                        </div>
                        {day.estimated_cost && (
                          <div className="mt-4 pt-4 border-t border-slate-100 flex items-center justify-between text-sm">
                            <span className="text-slate-500">
                              Estimated Daily Cost: <span className="font-semibold text-slate-800">{day.estimated_cost}</span>
                            </span>
                          </div>
                        )}
                        {day.notes && (
                          <div className="mt-3 text-sm text-slate-500 bg-yellow-50 p-3 rounded-lg border border-yellow-100 italic">
                            {day.notes}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Events */}
            {eventsData && (
              <div className="mt-12">
                <h2 className="text-2xl font-bold text-slate-900 mb-6 border-b border-slate-200 pb-4">
                  Local Events & Activities
                </h2>
                {typeof eventsData === 'string' ? (
                  <div className="bg-gradient-to-br from-indigo-50 to-purple-50 p-6 rounded-2xl border border-indigo-100">
                    <h3 className="font-bold tracking-tight text-indigo-900 text-lg mb-3">TBuddy Event Recommendations</h3>
                    <p className="text-indigo-800 leading-relaxed font-medium">{eventsData}</p>
                  </div>
                ) : Array.isArray(eventsData) ? (
                  <div className="space-y-4">
                    {eventsData.slice(0, 6).map((evt, i) => (
                      <div key={i} className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex gap-4">
                        <div className="flex-shrink-0 w-12 h-12 bg-purple-50 rounded-xl flex items-center justify-center">
                          <Ticket className="w-5 h-5 text-purple-500" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="font-semibold text-slate-800 truncate">{evt.name || evt.title}</p>
                          <p className="text-sm text-slate-500">{evt.date} {evt.time && `• ${evt.time}`}</p>
                          {evt.venue && <p className="text-sm text-slate-400">{evt.venue}</p>}
                          {evt.description && <p className="text-sm text-slate-600 mt-1 line-clamp-2">{evt.description}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="bg-gradient-to-br from-indigo-50 to-purple-50 p-6 rounded-2xl border border-indigo-100">
                    <h3 className="font-bold tracking-tight text-indigo-900 text-lg mb-3">TBuddy Event Recommendations</h3>
                    <p className="text-indigo-800 leading-relaxed font-medium whitespace-pre-wrap">
                      {eventsData.summary || eventsData.analysis || JSON.stringify(eventsData, null, 2)}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ─── Sidebar ─── */}
          <div className="space-y-6">
            {/* Weather */}
            {weatherData.length > 0 && (
              <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm relative overflow-hidden">
                <div className="absolute top-0 right-0 w-32 h-32 bg-blue-50 rounded-bl-full -z-0 opacity-50" />
                <h3 className="font-bold text-slate-800 mb-4 flex items-center gap-2 relative z-10">
                  <CloudRain className="w-5 h-5 text-blue-500" /> Weather Forecast
                </h3>
                <div className="space-y-3 relative z-10">
                  {weatherData.slice(0, 5).map((w, i) => (
                    <div key={i} className="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-100">
                      <div>
                        <span className="text-sm font-semibold text-slate-700 block">{w.date}</span>
                        <span className="text-xs text-slate-500 capitalize">{w.condition || w.description}</span>
                      </div>
                      <div className="text-right">
                        {w.temperature_max != null && (
                          <>
                            <span className="text-sm font-bold text-slate-800">{w.temperature_max}°</span>
                            {w.temperature_min != null && <span className="text-xs text-slate-400 ml-1">/ {w.temperature_min}°</span>}
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {weatherData.length > 5 && (
                  <p className="text-xs text-slate-400 text-center mt-3 pt-3 border-t border-slate-100">
                    + {weatherData.length - 5} more days
                  </p>
                )}
              </div>
            )}

            {/* Route */}
            {routeData && (
              <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
                <h3 className="font-bold text-slate-800 mb-4 flex items-center gap-2">
                  <MapIcon className="w-5 h-5 text-emerald-500" /> Route Details
                </h3>
                <div className="space-y-4">
                  {routeData.transport_mode && (
                    <div className="flex justify-between items-center text-sm border-b border-slate-100 pb-2">
                      <span className="text-slate-500">Mode</span>
                      <span className="font-semibold text-slate-800 capitalize bg-emerald-50 text-emerald-700 px-2.5 py-1 rounded-md">
                        {routeData.transport_mode}
                      </span>
                    </div>
                  )}
                  {routeData.distance && (
                    <div className="flex justify-between items-center text-sm border-b border-slate-100 pb-2">
                      <span className="text-slate-500">Distance</span>
                      <span className="font-semibold text-slate-800">{routeData.distance}</span>
                    </div>
                  )}
                  {routeData.duration && (
                    <div className="flex justify-between items-center text-sm">
                      <span className="text-slate-500">Est. Duration</span>
                      <span className="font-semibold text-slate-800">{routeData.duration}</span>
                    </div>
                  )}
                  {routeData.route_analysis && (
                    <div className="mt-3 text-sm text-slate-600 bg-emerald-50 p-3 rounded-lg border border-emerald-100">
                      {routeData.route_analysis}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Budget */}
            {budgetData && (
              <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
                <h3 className="font-bold text-slate-800 mb-4 flex items-center gap-2">
                  <Banknote className="w-5 h-5 text-orange-500" /> Budget Breakdown
                </h3>
                {budgetData.total != null && (
                  <div className="text-center mb-6 py-4 bg-orange-50 rounded-xl border border-orange-100">
                    <p className="text-xs text-orange-600 font-semibold uppercase tracking-wider mb-1">Total Estimate</p>
                    <p className="text-3xl font-black text-orange-600">
                      {budgetData.currency || 'INR'} {Number(budgetData.total).toLocaleString()}
                    </p>
                  </div>
                )}
                <div className="space-y-3">
                  {budgetData.transportation != null && <BudgetRow label="Transportation" amount={budgetData.transportation} currency={budgetData.currency} />}
                  {budgetData.accommodation != null && <BudgetRow label="Accommodation" amount={budgetData.accommodation} currency={budgetData.currency} />}
                  {budgetData.food != null && <BudgetRow label="Food & Dining" amount={budgetData.food} currency={budgetData.currency} />}
                  {budgetData.activities != null && <BudgetRow label="Activities" amount={budgetData.activities} currency={budgetData.currency} />}
                  {budgetData.miscellaneous != null && <BudgetRow label="Miscellaneous" amount={budgetData.miscellaneous} currency={budgetData.currency} />}
                </div>
                {/* If budget is a text summary instead of structured */}
                {budgetData._raw && typeof budgetData._raw === 'string' && (
                  <div className="mt-4 text-sm text-slate-600 whitespace-pre-wrap">{budgetData._raw}</div>
                )}
              </div>
            )}

            {/* Agent statuses summary */}
            {result.agent_statuses && (
              <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
                <h3 className="font-bold text-slate-800 mb-4 flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-brand-500" /> Agent Status
                </h3>
                <div className="space-y-2">
                  {Object.entries(result.agent_statuses).map(([agent, status]) => (
                    <div key={agent} className="flex items-center justify-between text-sm">
                      <span className="text-slate-600 capitalize">{agent}</span>
                      <span className={`font-medium px-2 py-0.5 rounded ${
                        status === 'completed' ? 'bg-green-50 text-green-700'
                        : status === 'timeout' ? 'bg-yellow-50 text-yellow-700'
                        : 'bg-red-50 text-red-700'
                      }`}>
                        {status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Budget row component ───────────────────────────────────
function BudgetRow({ label, amount, currency = 'INR' }) {
  if (amount == null) return null;
  return (
    <div className="flex justify-between items-center text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="font-semibold text-slate-800">{currency} {Number(amount).toLocaleString()}</span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  Data extraction helpers — adapt to whatever shape the backend returns
// ═══════════════════════════════════════════════════════════════

function extractWeather(result) {
  const w = result?.weather || result?.weather_data;
  if (!w) return [];
  // Could be { forecasts: [...] } or directly an array
  if (Array.isArray(w)) return w;
  if (w.forecasts && Array.isArray(w.forecasts)) return w.forecasts;
  if (w.forecast && Array.isArray(w.forecast)) return w.forecast;
  if (w.daily && Array.isArray(w.daily)) return w.daily;
  // Wrap single object
  return [w];
}

function extractRoute(result) {
  const m = result?.maps || result?.maps_data || result?.route || result?.route_data;
  if (!m) return null;
  // Could be { primary_route: {...}, ... } or flat { distance, duration, ... }
  if (m.primary_route) {
    return { ...m.primary_route, route_analysis: m.route_analysis, recommended_mode: m.recommended_mode };
  }
  if (m.distance || m.duration) return m;
  // Could be { route_analysis: "..." } text-only
  if (m.route_analysis) return m;
  return m;
}

function extractBudget(result) {
  const b = result?.budget || result?.budget_data;
  if (!b) return null;
  if (typeof b === 'string') return { _raw: b };
  // Might be nested: { budget_breakdown: { ... } }
  if (b.budget_breakdown) return b.budget_breakdown;
  if (b.breakdown) return b.breakdown;
  return b;
}

function extractItinerary(result) {
  const it = result?.itinerary || result?.itinerary_data;
  if (!it) return [];
  // Could be { days: [...] } or directly an array
  let days = [];
  if (Array.isArray(it)) days = it;
  else if (it.days && Array.isArray(it.days)) days = it.days;
  else if (it.itinerary && Array.isArray(it.itinerary)) days = it.itinerary;
  else return [];

  // Normalize each day
  return days.map((d, i) => ({
    day: d.day || i + 1,
    date: d.date || '',
    activities: Array.isArray(d.activities) ? d.activities : (d.activities ? [d.activities] : []),
    estimated_cost: d.estimated_cost || d.cost || null,
    notes: d.notes || d.note || '',
  }));
}

function extractEvents(result) {
  const e = result?.events || result?.events_data || result?.event_recommendations;
  if (!e) return null;
  // Could be { events: [...], summary: "..." } or just an array or a string
  if (typeof e === 'string') return e;
  if (Array.isArray(e)) return e;
  if (e.events && Array.isArray(e.events)) return e.events;
  if (e.summary) return e;
  if (e.analysis) return e;
  return e;
}
