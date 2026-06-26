"use client";
import { useState, useEffect, useCallback, memo, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MessageCircle, ChevronUp, ChevronDown, Clock } from "lucide-react";
import dynamic from "next/dynamic";
import PreferencePoll from "@/components/PreferencePoll";
import Hyperspeed from "@/components/Hyperspeed/Hyperspeed";

// Leaflet needs `window`, so load TripMap only on the client
const TripMap = dynamic(() => import("@/components/TripMap"), { ssr: false });

const HyperspeedBackground = memo(function HyperspeedBackground() {
  return (
    <div className="fixed scale-60 -left-75 -top-50 bottom-0 right-0 h-screen w-screen pointer-events-none">
      <Hyperspeed effectOptions={{ colors: { roadColor: 0x080808, islandColor: 0x0a0a0a, background: 0x000000, shoulderLines: 0x131318, brokenLines: 0x131318, leftCars: [0x7d0d1b, 0xa90519, 0xff102a], rightCars: [0xf1eece, 0xe6e2b1, 0xdfd98a], sticks: 0xf1eece } }} />
      <div className="w-full h-full bg-gradient-to-b from-zinc-900/20 to-black/40" />
    </div>
  );
});

const LightRaysBackground = memo(function LightRaysBackground() {
  return (
    <div className="fixed inset-0 h-screen w-screen pointer-events-none">
      <div className="w-full h-full opacity-30">
        <div className="absolute inset-0 bg-gradient-to-br from-red-900/10 via-transparent to-amber-900/10" />
      </div>
    </div>
  );
});

const placeholderTexts = ["Plan your dream vacation to Paris...","Discover hidden gems in Tokyo...","Create an adventure in Iceland...","Explore the streets of New York...","Find paradise in Bali...","Journey through the Swiss Alps...","Experience the magic of Rome...","Uncover treasures in Morocco..."];
const titles = ["Where planning is Spontaneous","Less Google, More Goggles","Plan less, Chill more"];

// ─── Types ────────────────────────────────────────────────────────────────────
interface DayWeather { date?: string; description?: string; temperature_max?: number; temperature_min?: number; humidity?: number; wind_speed?: number; precipitation_chance?: number; }
interface ItineraryDay { day: number; date: string; activities: string[]; notes?: string; estimated_cost?: number; }
interface Budget { total: number; transportation: number; accommodation: number; food: number; activities: number; currency?: string; }
interface RouteInfo { distance?: string; duration?: string; transport_mode?: string; }
interface FlightInfo { airline?: string; price?: number; currency?: string; departure_time?: string; arrival_time?: string; duration_minutes?: number; stops?: number; origin_code?: string; dest_code?: string; }
interface TrainInfo { train_number?: string; train_name?: string; departure_time?: string; arrival_time?: string; duration?: string; classes?: string[]; from_station?: string; to_station?: string; days_of_run?: string; }
interface BusInfo { operator_name?: string; bus_type?: string; departure_time?: string; arrival_time?: string; duration_minutes?: number; price?: number; currency?: string; service_number?: string; }
interface TravelOptions { flights?: { flights?: FlightInfo[]; count?: number; origin_code?: string; dest_code?: string; note?: string }; trains?: { trains?: TrainInfo[]; count?: number; from_station?: string; to_station?: string; note?: string }; buses?: { buses?: BusInfo[]; count?: number; note?: string }; }
interface MapsData { origin?: string; destination?: string; primary_route?: RouteInfo; alternative_routes?: Record<string, RouteInfo>; route_analysis?: string; travel_options?: TravelOptions; }
interface EventInfo { name?: string; date?: string; time?: string; venue?: string; category?: string; description?: string; price_min?: number; price_max?: number; currency?: string; }
interface HotelInfo {
  id: string;
  name: string;
  area: string;
  price_per_night: number | null;
  currency: string;
  rating: number;
  review_count: number;
  tier: "budget" | "mid-range" | "luxury";
  amenities: string[];
  description: string;
  booking_tip: string;
  photo_url?: string;
  booking_url?: string;
  lat?: number;
  lng?: number;
  proximity?: {
    attraction_name: string;
    distance_km: number;
  };
}
interface HotelData {
  destination: string;
  currency: string;
  generated_at: string;
  source: string;
  hotels: HotelInfo[];
}
interface RouteStop {
  lat: number;
  lng: number;
  name?: string;
  visit_minutes?: number;
  category?: string;
}
interface PlanData {
  itinerary: ItineraryDay[];
  budget: Budget;
  weather: DayWeather[];
  maps: MapsData | null;
  events: EventInfo[];
  processing_time_ms: number;
  hotels?: HotelData | null;
  route_optimization?: {
    applied: boolean;
    km_saved: number;
    day_routes?: RouteStop[][];
  };
}

// ─── Normalizers — handle field name variants from backend ───────────────────
function normalizeWeatherDay(w: Record<string, unknown>): DayWeather {
  return {
    date: w.date as string | undefined,
    description: w.description as string | undefined,
    temperature_max: (w.temperature_max as number) ?? (w.temp_max as number) ?? undefined,
    temperature_min: (w.temperature_min as number) ?? (w.temp_min as number) ?? undefined,
    humidity: (w.humidity as number) ?? undefined,
    wind_speed: (w.wind_speed as number) ?? undefined,
    precipitation_chance: (w.precipitation_chance as number) ?? undefined,
  };
}

function normalizeRoute(r: Record<string, unknown>): RouteInfo {
  const summary = r.summary as Record<string, number> | undefined;
  let distance = r.distance as string | undefined;
  let duration = r.duration as string | undefined;
  if (!distance && summary?.distance) {
    const m = summary.distance;
    distance = m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
  }
  if (!duration && summary?.duration) {
    const s = summary.duration;
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    duration = h > 0 ? `${h}h ${m}m` : `${m}m`;
  }
  return { distance, duration, transport_mode: (r.transport_mode as string) ?? (r.mode as string) ?? undefined };
}

function normalizeMaps(raw: Record<string, unknown>): MapsData {
  return {
    origin: raw.origin as string | undefined,
    destination: raw.destination as string | undefined,
    route_analysis: raw.route_analysis as string | undefined,
    primary_route: raw.primary_route ? normalizeRoute(raw.primary_route as Record<string, unknown>) : undefined,
    alternative_routes: raw.alternative_routes
      ? Object.fromEntries(Object.entries(raw.alternative_routes as Record<string, unknown>).map(([k, v]) => [k, normalizeRoute(v as Record<string, unknown>)]))
      : undefined,
    travel_options: raw.travel_options as TravelOptions | undefined,
  };
}

// ─── Pure helpers ─────────────────────────────────────────────────────────────
function expandTravelDates(rawDates: string[]): string[] {
  const out: string[] = [];
  for (const d of rawDates) {
    const m = d.match(/(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})/);
    if (m) { const c = new Date(m[1]), e = new Date(m[2]); while (c <= e) { out.push(c.toISOString().split("T")[0]); c.setDate(c.getDate() + 1); } }
    else out.push(d);
  }
  if (out.length === 2) {
    const start = new Date(out[0]);
    const end = new Date(out[1]);
    if (!isNaN(start.getTime()) && !isNaN(end.getTime()) && start <= end) {
      const full: string[] = [];
      const cur = new Date(start);
      while (cur <= end) {
        full.push(cur.toISOString().split("T")[0]);
        cur.setDate(cur.getDate() + 1);
      }
      return full;
    }
  }
  return out.length > 0 ? out : rawDates;
}

function reconstructItineraryDays(existing: ItineraryDay[], dates: string[], budget: Budget): ItineraryDay[] {
  if (existing.length === dates.length) return existing;
  const daily = dates.length > 0 ? Math.round(budget.total / dates.length) : 0;
  return dates.map((date, i) => {
    const e = existing[i];
    return e ? { ...e, date, estimated_cost: daily } : { day: i+1, date, activities: [`Day ${i+1} — refresh to regenerate`], notes: "", estimated_cost: daily };
  });
}

function weatherEmoji(desc?: string, rain?: number): string {
  if (rain && rain > 70) return "🌧️"; if (rain && rain > 40) return "🌦️";
  const d = (desc || "").toLowerCase();
  if (d.includes("thunder")) return "⛈️"; if (d.includes("rain") || d.includes("drizzle")) return "🌧️";
  if (d.includes("cloud") || d.includes("overcast")) return "☁️"; if (d.includes("sun") || d.includes("clear")) return "☀️";
  if (d.includes("mist") || d.includes("fog") || d.includes("haze")) return "🌫️";
  return "🌤️";
}

function modeEmoji(mode?: string): string {
  const m = (mode || "").toLowerCase();
  if (m.includes("train") || m.includes("rail")) return "🚂"; if (m.includes("flight") || m.includes("air")) return "✈️";
  if (m.includes("bus")) return "🚌"; if (m.includes("walk")) return "🚶"; if (m.includes("cycl") || m.includes("bike")) return "🚲";
  return "🚗";
}

function fmtDate(dateStr: string): string {
  try { return new Date(dateStr + "T00:00:00").toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" }); }
  catch { return dateStr; }
}

// ─── TypewriterPrompt ─────────────────────────────────────────────────────────
const TypewriterPrompt = ({ onSubmit, disabled = false }: { onSubmit: (q: string) => void; disabled?: boolean }) => {
  const [display, setDisplay] = useState(""); const [idx, setIdx] = useState(0); const [del, setDel] = useState(false); const [input, setInput] = useState("");
  useEffect(() => {
    const phrase = placeholderTexts[idx];
    const t = setTimeout(() => {
      if (!del && display === phrase) { setTimeout(() => setDel(true), 2000); }
      else if (del && display === "") { setDel(false); setIdx(p => (p+1) % placeholderTexts.length); }
      else setDisplay(del ? phrase.substring(0, display.length-1) : phrase.substring(0, display.length+1));
    }, del ? 30 : 80);
    return () => clearTimeout(t);
  }, [display, del, idx]);
  const submit = () => { if (input.trim() && !disabled) { onSubmit(input.trim()); setInput(""); } };
  return (
    <motion.div className="relative w-full max-w-3xl" initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ duration:0.6 }}>
      <div className="relative">
        <textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key==="Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          disabled={disabled} placeholder={display} rows={4}
          className="w-full min-h-[120px] bg-black/40 backdrop-blur-md border border-zinc-600/50 rounded-2xl p-5 pr-14 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 resize-none transition-all shadow-2xl disabled:opacity-50" />
        <button onClick={submit} disabled={!input.trim() || disabled}
          className="absolute bottom-4 right-4 bg-gradient-to-r from-red-700 to-red-900 hover:from-red-600 hover:to-red-700 text-white p-3 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
          </svg>
        </button>
      </div>
      <div className="mt-4 flex gap-3 flex-wrap justify-center">
        {["Weekend Getaway","Family Trip","Solo Adventure","Budget Travel"].map(tag => (
          <button key={tag} onClick={() => setInput(p => p ? `${p} ${tag}` : tag)}
            className="px-4 py-2 bg-zinc-800/50 backdrop-blur-sm border border-zinc-700/50 rounded-full text-sm text-zinc-300 hover:bg-zinc-700/50 hover:border-amber-400 transition-all">{tag}</button>
        ))}
      </div>
      <div className="mt-8 flex gap-6 text-sm text-zinc-400 mb-8 justify-center">
        {[["bg-red-900","Instant Planning"],["bg-zinc-800","Smart Recommendations"],["bg-yellow-800","Budget Friendly"]].map(([c,l]) => (
          <div key={l} className="flex items-center gap-2"><div className={`w-2 h-2 ${c} rounded-full animate-pulse`} /><span>{l}</span></div>
        ))}
      </div>
    </motion.div>
  );
};

// ─── LoadingState ─────────────────────────────────────────────────────────────
const LoadingState = () => {
  const stages = [{ text:"Ringmaster is thinking",icon:"🎪"},{ text:"Analysing your preferences",icon:"🔍"},{ text:"Checking weather conditions",icon:"🌤️"},{ text:"Finding the best routes",icon:"🗺️"},{ text:"Calculating your budget",icon:"💰"},{ text:"Crafting your perfect itinerary",icon:"✨"}];
  const [s, setS] = useState(0);
  useEffect(() => { const t = setInterval(() => setS(p => (p+1) % stages.length), 2000); return () => clearInterval(t); }, []);
  return (
    <div className="flex flex-col items-center justify-center space-y-8">
      <motion.div animate={{ rotate:360 }} transition={{ duration:2, repeat:Infinity, ease:"linear" }}>
        <div className="w-20 h-20 border-4 border-red-900/30 border-t-red-500 rounded-full" />
      </motion.div>
      <AnimatePresence mode="wait">
        <motion.div key={s} initial={{ opacity:0, y:10 }} animate={{ opacity:1, y:0 }} exit={{ opacity:0, y:-10 }} className="text-center">
          <div className="text-4xl mb-3">{stages[s].icon}</div>
          <div className="text-xl text-zinc-300 font-light">{stages[s].text}</div>
        </motion.div>
      </AnimatePresence>
      <div className="flex gap-2">
        {stages.map((_,i) => <motion.div key={i} className={`h-1.5 rounded-full transition-all duration-300 ${i===s?"w-8 bg-red-500":"w-1.5 bg-zinc-700"}`} />)}
      </div>
    </div>
  );
};

// ─── WeatherStrip ─────────────────────────────────────────────────────────────
const WeatherStrip = ({ weather }: { weather: DayWeather[] }) => {
  const valid = weather.filter(w => w.temperature_max != null || w.description);
  if (!valid.length) return null;
  return (
    <motion.div initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.25 }}
      className="mb-8 p-6 bg-gradient-to-br from-blue-900/20 to-cyan-900/20 backdrop-blur-md border border-blue-800/30 rounded-2xl">
      <h3 className="text-xl font-light text-zinc-100 mb-4 flex items-center gap-2"><span>🌤️</span> Weather Forecast</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {valid.map((w, i) => (
          <div key={i} className="p-4 bg-blue-900/20 border border-blue-700/20 rounded-xl text-center">
            <div className="text-2xl mb-1">{weatherEmoji(w.description, w.precipitation_chance)}</div>
            <div className="text-xs text-blue-300 mb-2">{w.date ? fmtDate(w.date).split(",")[0] + "," + fmtDate(w.date).split(",").slice(1).join(",") : `Day ${i+1}`}</div>
            <div className="text-white font-semibold">
              {w.temperature_max != null ? `${Math.round(w.temperature_max)}°C` : "—"}
              {w.temperature_min != null && <span className="text-blue-300 font-normal"> / {Math.round(w.temperature_min)}°C</span>}
            </div>
            {w.description && !/forecast not available/i.test(w.description) && (
              <div className="text-xs text-blue-200 mt-1 capitalize">{w.description}</div>
            )}
            {w.precipitation_chance != null && w.precipitation_chance > 0 && (
              <div className="text-xs text-blue-300 mt-1">💧 {w.precipitation_chance}% rain</div>
            )}
            {w.humidity != null && w.humidity > 0 && (
              <div className="text-xs text-blue-300">💦 {w.humidity}% humidity</div>
            )}
          </div>
        ))}
      </div>
      {weather.some(w => w.temperature_max == null) && (
        <p className="text-xs text-blue-400 mt-3 text-center">
          ℹ️ Forecast beyond 16 days uses seasonal estimates for the destination
        </p>
      )}
    </motion.div>
  );
};

// ─── RouteCard ────────────────────────────────────────────────────────────────
const RouteCard = ({ maps }: { maps: MapsData }) => {
  const primary = maps.primary_route;
  const alts = maps.alternative_routes || {};
  const hasRouteData = (primary?.distance && primary.distance !== "Unknown") || Object.keys(alts).length > 0;
  if (!hasRouteData && !maps.route_analysis) return null;
  return (
    <motion.div initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.3 }}
      className="mb-8 p-6 bg-gradient-to-br from-emerald-900/20 to-green-900/20 backdrop-blur-md border border-emerald-800/30 rounded-2xl">
      <h3 className="text-xl font-light text-zinc-100 mb-1 flex items-center gap-2"><span>🗺️</span> Getting There</h3>
      {maps.origin && maps.destination && <p className="text-sm text-emerald-300 mb-4">{maps.origin} → {maps.destination}</p>}
      {maps.route_analysis && <p className="text-sm text-zinc-300 mb-4 p-3 bg-black/20 rounded-xl border border-emerald-700/20">{maps.route_analysis}</p>}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {primary && (primary.distance || primary.duration) && (
          <div className="p-4 bg-emerald-900/30 border border-emerald-600/30 rounded-xl">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xl">{modeEmoji(primary.transport_mode)}</span>
              <span className="text-white font-semibold capitalize">{primary.transport_mode || "Recommended"}</span>
              <span className="ml-auto text-xs bg-emerald-600/40 text-emerald-200 px-2 py-0.5 rounded-full">Best option</span>
            </div>
            {primary.distance && <div className="text-sm text-emerald-200">📍 {primary.distance}</div>}
            {primary.duration && <div className="text-sm text-emerald-200">⏱️ {primary.duration}</div>}
          </div>
        )}
        {Object.entries(alts).filter(([, r]) => r.distance || r.duration).map(([mode, route], idx) => (
          <div key={mode || idx} className="p-4 bg-black/20 border border-emerald-800/20 rounded-xl">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xl">{modeEmoji(mode)}</span>
              <span className="text-zinc-300 capitalize">{mode}</span>
            </div>
            {route.distance && <div className="text-sm text-zinc-400">📍 {route.distance}</div>}
            {route.duration && <div className="text-sm text-zinc-400">⏱️ {route.duration}</div>}
          </div>
        ))}
      </div>
    </motion.div>
  );
};

// ─── TravelOptionsCard ────────────────────────────────────────────────────────
const TravelOptionsCard = ({ travelOptions, origin, destination }: { travelOptions: TravelOptions; origin?: string; destination?: string }) => {
  const [activeMode, setActiveMode] = useState<"flights" | "trains" | "buses">("flights");
  const flights = travelOptions?.flights?.flights || [];
  const trains = travelOptions?.trains?.trains || [];
  const buses = travelOptions?.buses?.buses || [];

  const totalOptions = flights.length + trains.length + buses.length;
  if (totalOptions === 0) return null;

  const tabs = [
    { key: "flights" as const, label: "Flights", emoji: "✈️", count: flights.length, color: "sky" },
    { key: "trains" as const, label: "Trains", emoji: "🚂", count: trains.length, color: "amber" },
    { key: "buses" as const, label: "Buses", emoji: "🚌", count: buses.length, color: "emerald" },
  ];

  const fmtTime = (t?: string) => {
    if (!t) return "";
    try {
      const d = new Date(t);
      if (isNaN(d.getTime())) return t;
      return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
    } catch { return t; }
  };

  const fmtDur = (mins?: number) => {
    if (!mins) return "";
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}
      className="mb-8 p-6 bg-gradient-to-br from-indigo-900/20 to-violet-900/20 backdrop-blur-md border border-indigo-800/30 rounded-2xl"
    >
      <h3 className="text-xl font-light text-zinc-100 mb-1 flex items-center gap-2">
        <span>🚀</span> Travel Options
        <span className="ml-auto text-xs text-indigo-300">{totalOptions} options found</span>
      </h3>
      {origin && destination && <p className="text-sm text-indigo-300 mb-4">{origin} → {destination}</p>}

      {/* Tabs */}
      <div className="flex gap-2 mb-4">
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveMode(tab.key)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
              activeMode === tab.key
                ? tab.color === "sky"
                  ? "bg-sky-600/40 text-sky-200 border border-sky-500/40 shadow-lg shadow-sky-900/20"
                  : tab.color === "amber"
                  ? "bg-amber-600/40 text-amber-200 border border-amber-500/40 shadow-lg shadow-amber-900/20"
                  : "bg-emerald-600/40 text-emerald-200 border border-emerald-500/40 shadow-lg shadow-emerald-900/20"
                : "bg-black/20 text-zinc-400 border border-zinc-700/30 hover:bg-white/5"
            }`}
          >
            <span>{tab.emoji}</span>
            {tab.label}
            {tab.count > 0 && (
              <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                activeMode === tab.key ? "bg-white/15" : "bg-zinc-700/50"
              }`}>{tab.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Flights Tab */}
      <AnimatePresence mode="wait">
        {activeMode === "flights" && (
          <motion.div key="flights" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }} transition={{ duration: 0.2 }}
            className="space-y-3">
            {flights.length === 0 ? (
              <div className="text-center py-8 text-zinc-500">
                <span className="text-3xl block mb-2">✈️</span>
                <p className="text-sm">{travelOptions?.flights?.note || "No flights found for this route"}</p>
              </div>
            ) : (
              flights.map((f, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                  className="p-4 bg-gradient-to-r from-sky-900/20 to-blue-900/15 border border-sky-700/25 rounded-xl hover:border-sky-600/40 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-sky-600/30 flex items-center justify-center text-lg">✈️</div>
                      <div>
                        <div className="text-white font-medium">{f.airline || "Airline"}</div>
                        <div className="text-xs text-sky-300">
                          {f.origin_code && f.dest_code ? `${f.origin_code} → ${f.dest_code}` : ""}
                          {f.stops !== undefined && <span className="ml-2">{f.stops === 0 ? "Non-stop" : `${f.stops} stop${f.stops > 1 ? "s" : ""}`}</span>}
                        </div>
                      </div>
                    </div>
                    {f.price && (
                      <div className="text-right">
                        <div className="text-sky-200 font-semibold text-lg">₹{f.price.toLocaleString()}</div>
                        <div className="text-xs text-zinc-500">{f.currency || "INR"}</div>
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs text-zinc-400">
                    {f.departure_time && <span>🛫 {fmtTime(f.departure_time)}</span>}
                    {f.arrival_time && <span>🛬 {fmtTime(f.arrival_time)}</span>}
                    {f.duration_minutes && <span>⏱️ {fmtDur(f.duration_minutes)}</span>}
                  </div>
                </motion.div>
              ))
            )}
          </motion.div>
        )}

        {/* Trains Tab */}
        {activeMode === "trains" && (
          <motion.div key="trains" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }} transition={{ duration: 0.2 }}
            className="space-y-3">
            {trains.length === 0 ? (
              <div className="text-center py-8 text-zinc-500">
                <span className="text-3xl block mb-2">🚂</span>
                <p className="text-sm">{travelOptions?.trains?.note || "No trains found for this route"}</p>
              </div>
            ) : (
              trains.map((t, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                  className="p-4 bg-gradient-to-r from-amber-900/20 to-orange-900/15 border border-amber-700/25 rounded-xl hover:border-amber-600/40 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-amber-600/30 flex items-center justify-center text-lg">🚂</div>
                      <div>
                        <div className="text-white font-medium">{t.train_name || "Train"}</div>
                        <div className="text-xs text-amber-300">
                          {t.train_number && <span>#{t.train_number} </span>}
                          {t.from_station && t.to_station ? `${t.from_station} → ${t.to_station}` : ""}
                        </div>
                      </div>
                    </div>
                    {t.duration && (
                      <div className="text-right">
                        <div className="text-amber-200 font-semibold">⏱️ {t.duration}</div>
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs text-zinc-400">
                    {t.departure_time && <span>🚉 Dep: {t.departure_time}</span>}
                    {t.arrival_time && <span>🚉 Arr: {t.arrival_time}</span>}
                    {t.classes && Array.isArray(t.classes) && t.classes.length > 0 && (
                      <span>🎫 {t.classes.join(", ")}</span>
                    )}
                  </div>
                  {t.days_of_run && <div className="mt-2 text-xs text-zinc-500">📅 Runs: {t.days_of_run}</div>}
                </motion.div>
              ))
            )}
          </motion.div>
        )}

        {/* Buses Tab */}
        {activeMode === "buses" && (
          <motion.div key="buses" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }} transition={{ duration: 0.2 }}
            className="space-y-3">
            {buses.length === 0 ? (
              <div className="text-center py-8 text-zinc-500">
                <span className="text-3xl block mb-2">🚌</span>
                <p className="text-sm">{travelOptions?.buses?.note || "No bus/transit options found for this route"}</p>
              </div>
            ) : (
              buses.map((b, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                  className="p-4 bg-gradient-to-r from-emerald-900/20 to-teal-900/15 border border-emerald-700/25 rounded-xl hover:border-emerald-600/40 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-emerald-600/30 flex items-center justify-center text-lg">🚌</div>
                      <div>
                        <div className="text-white font-medium">{b.operator_name || "Transit"}</div>
                        <div className="text-xs text-emerald-300">
                          {b.bus_type || "Public Transit"}
                          {b.service_number && <span className="ml-2">#{b.service_number}</span>}
                        </div>
                      </div>
                    </div>
                    {b.price && (
                      <div className="text-right">
                        <div className="text-emerald-200 font-semibold text-lg">{b.currency || "₹"}{b.price.toLocaleString()}</div>
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs text-zinc-400">
                    {b.departure_time && <span>🚏 Dep: {fmtTime(b.departure_time)}</span>}
                    {b.arrival_time && <span>🚏 Arr: {fmtTime(b.arrival_time)}</span>}
                    {b.duration_minutes && <span>⏱️ {fmtDur(b.duration_minutes)}</span>}
                  </div>
                </motion.div>
              ))
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

// ─── EventsCard ───────────────────────────────────────────────────────────────
const EventsCard = ({ events }: { events: EventInfo[] }) => {
  if (!events?.length) return null;
  const catColor: Record<string, string> = { music:"from-purple-900/30 border-purple-700/30", arts:"from-blue-900/30 border-blue-700/30", food:"from-orange-900/30 border-orange-700/30", sports:"from-green-900/30 border-green-700/30", culture:"from-pink-900/30 border-pink-700/30" };
  return (
    <motion.div initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.35 }}
      className="mb-8 p-6 bg-gradient-to-br from-fuchsia-900/20 to-pink-900/20 backdrop-blur-md border border-fuchsia-800/30 rounded-2xl">
      <h3 className="text-xl font-light text-zinc-100 mb-4 flex items-center gap-2">
        <span>🎉</span> Local Events <span className="ml-auto text-xs text-fuchsia-300">{events.length} events</span>
      </h3>
      <div className="space-y-3">
        {events.slice(0,6).map((e, i) => {
          const cc = catColor[(e.category||"").toLowerCase()] || "from-zinc-800/30 border-zinc-700/30";
          return (
            <div key={i} className={`p-4 bg-gradient-to-r ${cc} border rounded-xl`}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1">
                  <div className="text-white font-medium">{e.name}</div>
                  {e.description && <div className="text-xs text-zinc-300 mt-0.5">{e.description}</div>}
                </div>
                {e.category && <span className="text-xs bg-black/30 text-zinc-300 px-2 py-0.5 rounded-full capitalize flex-shrink-0">{e.category}</span>}
              </div>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-zinc-400">
                {e.date && <span>📅 {e.date}{e.time ? ` at ${e.time}` : ""}</span>}
                {e.venue && <span>📍 {e.venue}</span>}
                {e.price_min != null && <span className={e.price_min===0?"text-emerald-400":""}>{e.price_min===0?"🎟️ Free":`🎟️ ${e.currency||"INR"} ${e.price_min}${e.price_max&&e.price_max!==e.price_min?`–${e.price_max}`:""}`}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </motion.div>
  );
};

// ─── HotelCard ────────────────────────────────────────────────────────────────
const TIER_STYLES: Record<string, { gradient: string; border: string; badge: string; badgeBg: string }> = {
  budget:      { gradient: "from-emerald-900/20 to-green-900/10", border: "border-emerald-700/30", badge: "💚", badgeBg: "bg-emerald-900/50 text-emerald-300" },
  "mid-range": { gradient: "from-amber-900/20 to-yellow-900/10", border: "border-amber-700/30",   badge: "💛", badgeBg: "bg-amber-900/50 text-amber-300" },
  luxury:      { gradient: "from-purple-900/20 to-violet-900/10", border: "border-purple-700/30", badge: "💎", badgeBg: "bg-purple-900/50 text-purple-300" },
};

const HotelShimmer = () => (
  <div className="space-y-4">
    {[...Array(3)].map((_, i) => (
      <div key={i} className="h-36 bg-zinc-800/50 rounded-2xl animate-pulse" />
    ))}
  </div>
);

const HotelCard = ({
  hotels,
  source,
  generatedAt,
  destination,
  onRetry,
  loading,
  error,
}: {
  hotels: HotelInfo[];
  source: string;
  generatedAt: string;
  destination: string;
  onRetry: () => void;
  loading: boolean;
  error: string | null;
}) => {
  const [searchQuery, setSearchQuery] = useState("");
  const [minRating, setMinRating] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<"popularity" | "price-asc" | "price-desc" | "rating">("popularity");
  const [selectedAmenities, setSelectedAmenities] = useState<string[]>([]);

  const fmtPrice = (n: number | null) =>
    n != null ? new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n) : "Price N/A";

  const timeAgo = (iso: string) => {
    try {
      const diff = (Date.now() - new Date(iso).getTime()) / 1000;
      if (diff < 60) return "just now";
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      return `${Math.floor(diff / 3600)}h ago`;
    } catch { return ""; }
  };

  // Loading state
  if (loading) return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="p-6 bg-zinc-900/50 backdrop-blur-md border border-zinc-800 rounded-2xl">
      <h3 className="text-xl font-light text-zinc-100 mb-4 flex items-center gap-2">
        <span>🏨</span> Finding Hotels...
      </h3>
      <HotelShimmer />
    </motion.div>
  );

  // Error state with retry
  if (error) return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center py-16">
      <span className="text-4xl block mb-3">⚠️</span>
      <p className="text-xl text-zinc-300 mb-2">Failed to load hotels</p>
      <p className="text-sm text-zinc-500 mb-4">{error}</p>
      <button onClick={onRetry} className="px-6 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-xl transition-colors text-sm font-medium">
        🔄 Try Again
      </button>
    </motion.div>
  );

  // Empty state
  if (!hotels?.length) return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center py-16">
      <span className="text-4xl block mb-3">🏨</span>
      <p className="text-xl text-zinc-300 mb-2">No hotels found</p>
      <p className="text-sm text-zinc-500 mb-4">We couldn&apos;t find hotels for {destination}.</p>
      <a
        href={`https://www.booking.com/searchresults.html?ss=${encodeURIComponent(destination)}`}
        target="_blank" rel="noopener noreferrer"
        className="inline-block px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl transition-colors text-sm font-medium"
      >
        🔗 Search on Booking.com
      </a>
    </motion.div>
  );

  // Extract unique amenities for filter options (take top 10)
  const allAmenities = Array.from(
    new Set((hotels || []).flatMap((h) => h.amenities || []))
  ).slice(0, 10);

  // Filter logic
  const filteredHotels = (hotels || []).filter((h) => {
    const matchQuery =
      searchQuery === "" ||
      h.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      h.area?.toLowerCase().includes(searchQuery.toLowerCase());

    const matchRating = minRating === null || (h.rating && h.rating >= minRating);

    const matchAmenities = selectedAmenities.every((amenity) =>
      h.amenities?.includes(amenity)
    );

    return matchQuery && matchRating && matchAmenities;
  });

  // Sort logic
  const sortedHotels = [...filteredHotels].sort((a, b) => {
    if (sortBy === "price-asc") {
      const pa = a.price_per_night ?? Infinity;
      const pb = b.price_per_night ?? Infinity;
      return pa - pb;
    }
    if (sortBy === "price-desc") {
      const pa = a.price_per_night ?? -Infinity;
      const pb = b.price_per_night ?? -Infinity;
      return pb - pa;
    }
    if (sortBy === "rating") {
      const ra = a.rating ?? 0;
      const rb = b.rating ?? 0;
      return rb - ra;
    }
    return 0; // popularity / default
  });

  // Group by tier
  const tiers = ["budget", "mid-range", "luxury"] as const;
  const tierLabels: Record<string, string> = { budget: "Budget Stays", "mid-range": "Mid-Range", luxury: "Luxury" };

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
      {/* Fallback disclaimer */}
      {source === "groq_fallback" && (
        <div className="mb-4 p-3 bg-amber-900/20 border border-amber-700/30 rounded-xl flex items-center gap-2 text-sm text-amber-300">
          <span>⚠️</span>
          <span>Estimated recommendations — verify pricing before booking</span>
        </div>
      )}

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <h3 className="text-xl font-light text-zinc-100 flex items-center gap-2">
          <span>🏨</span> Hotel Recommendations
          <span className="text-xs text-zinc-500 font-normal">{hotels.length} found</span>
        </h3>
        {generatedAt && (
          <span className="text-xs text-zinc-500">Updated {timeAgo(generatedAt)}</span>
        )}
      </div>

      {/* Dynamic Filters & Search Panel */}
      <div className="mb-6 p-4 bg-zinc-900/40 backdrop-blur-md border border-zinc-800/80 rounded-2xl space-y-4 shadow-xl">
        <div className="grid gap-3 md:grid-cols-3">
          {/* Search bar */}
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400 text-sm">🔍</span>
            <input
              type="text"
              placeholder="Search hotel name or area..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-black/40 border border-zinc-800 rounded-xl text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-violet-500/50 transition-colors"
            />
          </div>

          {/* Rating filter */}
          <div className="flex gap-1">
            <button
              onClick={() => setMinRating(null)}
              className={`flex-1 py-2 rounded-xl border text-[11px] font-medium transition-all ${
                minRating === null
                  ? "bg-violet-600 border-violet-500 text-white"
                  : "bg-black/30 border-zinc-800 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              All Ratings
            </button>
            <button
              onClick={() => setMinRating(7.5)}
              className={`flex-1 py-2 rounded-xl border text-[11px] font-medium transition-all ${
                minRating === 7.5
                  ? "bg-violet-600 border-violet-500 text-white"
                  : "bg-black/30 border-zinc-800 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              ⭐ 7.5+
            </button>
            <button
              onClick={() => setMinRating(8.5)}
              className={`flex-1 py-2 rounded-xl border text-[11px] font-medium transition-all ${
                minRating === 8.5
                  ? "bg-violet-600 border-violet-500 text-white"
                  : "bg-black/30 border-zinc-800 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              ⭐ 8.5+
            </button>
          </div>

          {/* Sort selection */}
          <div className="relative">
            <select
              value={sortBy}
              onChange={(e: any) => setSortBy(e.target.value)}
              className="w-full pl-4 pr-8 py-2 bg-black/40 border border-zinc-800 rounded-xl text-sm text-zinc-300 focus:outline-none focus:border-violet-500/50 transition-colors appearance-none cursor-pointer"
            >
              <option value="popularity" className="bg-zinc-950">Sort by: Popularity</option>
              <option value="price-asc" className="bg-zinc-950">Price: Low to High</option>
              <option value="price-desc" className="bg-zinc-950">Price: High to Low</option>
              <option value="rating" className="bg-zinc-950">Rating: High to Low</option>
            </select>
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 pointer-events-none text-xs">▼</span>
          </div>
        </div>

        {/* Amenities pills */}
        {allAmenities.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-zinc-800/40">
            <span className="text-[11px] text-zinc-500 mr-1 font-medium">Filter by Amenity:</span>
            {allAmenities.map((amenity) => {
              const selected = selectedAmenities.includes(amenity);
              return (
                <button
                  key={amenity}
                  onClick={() => {
                    if (selected) {
                      setSelectedAmenities(selectedAmenities.filter(a => a !== amenity));
                    } else {
                      setSelectedAmenities([...selectedAmenities, amenity]);
                    }
                  }}
                  className={`text-[10px] px-2.5 py-1 rounded-full transition-all border ${
                    selected
                      ? "bg-violet-500/20 border-violet-500 text-violet-300 shadow-sm shadow-violet-500/10"
                      : "bg-black/20 border-zinc-800 text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  {amenity}
                </button>
              );
            })}
            {selectedAmenities.length > 0 && (
              <button
                onClick={() => setSelectedAmenities([])}
                className="text-[10px] px-2.5 py-1 text-red-400 hover:text-red-300 font-medium"
              >
                Clear ×
              </button>
            )}
          </div>
        )}
      </div>

      {/* Tier groups */}
      <div className="space-y-6">
        {sortedHotels.length === 0 && (
          <div className="text-center py-12 bg-zinc-900/20 border border-zinc-800/50 rounded-2xl">
            <span className="text-3xl block mb-2">🔍</span>
            <p className="text-sm text-zinc-400">No hotels match your current search criteria or filters.</p>
            <button
              onClick={() => {
                setSearchQuery("");
                setMinRating(null);
                setSelectedAmenities([]);
              }}
              className="mt-3 text-xs text-violet-400 hover:text-violet-300 underline font-medium"
            >
              Reset all filters
            </button>
          </div>
        )}
        {tiers.map(tier => {
          const tierHotels = sortedHotels.filter(h => h.tier === tier);
          if (!tierHotels.length) return null;
          const style = TIER_STYLES[tier] || TIER_STYLES["mid-range"];
          return (
            <div key={tier}>
              <div className="flex items-center gap-2 mb-3">
                <span>{style.badge}</span>
                <span className="text-sm font-medium text-zinc-300">{tierLabels[tier]}</span>
                <div className="flex-1 h-px bg-zinc-800" />
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {tierHotels.map((hotel, i) => (
                  <motion.div
                    key={hotel.id || i}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.08 }}
                    className={`p-4 bg-gradient-to-br ${style.gradient} backdrop-blur-md border ${style.border} rounded-2xl hover:scale-[1.01] transition-transform duration-200`}
                  >
                    <div className="flex gap-4">
                      {/* Photo */}
                      {hotel.photo_url ? (
                        <div className="w-24 h-24 rounded-xl overflow-hidden flex-shrink-0 bg-zinc-800">
                          <img src={hotel.photo_url} alt={hotel.name} className="w-full h-full object-cover" loading="lazy" />
                        </div>
                      ) : (
                        <div className="w-24 h-24 rounded-xl bg-zinc-800/50 flex items-center justify-center flex-shrink-0">
                          <span className="text-3xl">🏨</span>
                        </div>
                      )}
                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2">
                          <h4 className="text-white font-medium truncate">{hotel.name}</h4>
                          <span className={`text-[10px] px-2 py-0.5 rounded-full flex-shrink-0 ${style.badgeBg}`}>
                            {tier}
                          </span>
                        </div>
                        {hotel.area && <p className="text-xs text-zinc-400 mt-0.5 truncate">📍 {hotel.area}</p>}
                        {hotel.proximity && (
                          <div className="mt-1">
                            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 bg-violet-500/10 text-violet-300 rounded-full border border-violet-500/20">
                              🧭 {hotel.proximity.distance_km} km from {hotel.proximity.attraction_name}
                            </span>
                          </div>
                        )}
                        <div className="flex items-center gap-3 mt-1.5">
                          {hotel.rating > 0 && (
                            <span className="text-xs text-yellow-400">⭐ {hotel.rating}/10</span>
                          )}
                          {hotel.review_count > 0 && (
                            <span className="text-xs text-zinc-500">({hotel.review_count.toLocaleString()} reviews)</span>
                          )}
                        </div>
                        <div className="text-lg font-semibold text-zinc-100 mt-1">
                          {fmtPrice(hotel.price_per_night)}
                          <span className="text-xs font-normal text-zinc-500">/night</span>
                        </div>
                      </div>
                    </div>

                    {/* Amenities */}
                    {hotel.amenities?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-3">
                        {hotel.amenities.slice(0, 4).map((a, j) => (
                          <span key={j} className="text-[10px] px-2 py-0.5 bg-black/30 text-zinc-400 rounded-full">{a}</span>
                        ))}
                      </div>
                    )}

                    {/* Description + Booking tip */}
                    {hotel.description && (
                      <p className="text-xs text-zinc-300 mt-2 leading-relaxed">{hotel.description}</p>
                    )}
                    {hotel.booking_tip && (
                      <p className="text-[11px] text-amber-400/80 mt-1.5 italic">💡 {hotel.booking_tip}</p>
                    )}

                    {/* Booking link */}
                    {hotel.booking_url && (
                      <a
                        href={hotel.booking_url}
                        target="_blank" rel="noopener noreferrer"
                        className="mt-3 inline-flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
                      >
                        View on Booking.com →
                      </a>
                    )}
                  </motion.div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </motion.div>
  );
};

// ─── Tab definitions ──────────────────────────────────────────────────────────
type SectionTab = "itinerary" | "map" | "weather" | "budget" | "hotels" | "events";
const SECTION_TABS: { id: SectionTab; label: string; icon: string }[] = [
  { id: "itinerary", label: "Itinerary", icon: "📅" },
  { id: "map",       label: "Map & Route", icon: "🗺️" },
  { id: "weather",   label: "Weather", icon: "🌤️" },
  { id: "budget",    label: "Budget", icon: "💰" },
  { id: "hotels",    label: "Hotels", icon: "🏨" },
  { id: "events",    label: "Events", icon: "🎭" },
];

// ─── Chat Feature Types ────────────────────────────────────────────────────────
interface PhraseCard { phrase_en: string; phrase_local: string; script?: string; pronunciation?: string; usage_tip?: string; }
interface ChecklistItem { item: string; category: string; packed: boolean; }
interface PlacePin { name: string; lat: number; lng: number; category: string; description?: string; }
interface FlightStatusInfo { flight_code: string; airline: string; status: string; departure?: string; arrival?: string; terminal?: string; gate?: string; delay_minutes: number; }
interface ProactiveAlert { message: string; severity: string; day?: number; }
interface ChatMessage {
  role: string;
  content: string;
  phrase_cards?: PhraseCard[];
  checklist?: ChecklistItem[];
  place_pins?: PlacePin[];
  flight_status?: FlightStatusInfo;
  proactive_alerts?: ProactiveAlert[];
  expense_update?: { logged_expense?: { amount: number; category: string; description: string; date_str?: string }; total_logged?: number; cost_per_person?: number; travelers_count?: number; entry_count?: number; category_breakdown?: Record<string, number>; };
}

// ─── Phrase Card UI ────────────────────────────────────────────────────────────
const PhraseCardBubble = ({ cards }: { cards: PhraseCard[] }) => (
  <div className="mt-3 space-y-2">
    <p className="text-xs text-fuchsia-300/70 font-semibold uppercase tracking-wider mb-2">🌐 Local Phrases</p>
    {cards.map((c, i) => (
      <motion.div key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }}
        className="bg-gradient-to-r from-fuchsia-950/60 to-violet-950/60 border border-fuchsia-500/30 rounded-2xl p-3 group">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1">
            <p className="text-fuchsia-100 font-semibold text-sm">{c.phrase_en}</p>
            <p className="text-violet-200 text-base font-bold mt-0.5">{c.phrase_local}</p>
            {c.script && c.script !== c.phrase_local && <p className="text-fuchsia-300/60 text-xs mt-0.5 italic">{c.script}</p>}
            {c.pronunciation && <p className="text-amber-300/80 text-xs mt-1">🔤 {c.pronunciation}</p>}
            {c.usage_tip && <p className="text-zinc-400 text-xs mt-1">{c.usage_tip}</p>}
          </div>
          <div className="flex gap-1.5 flex-shrink-0">
            <button title="Copy phrase" onClick={() => navigator.clipboard.writeText(c.phrase_local)}
              className="p-1.5 rounded-lg bg-fuchsia-500/10 hover:bg-fuchsia-500/25 text-fuchsia-300 transition-colors text-xs">📋</button>
            <button title="Pronounce" onClick={() => { const u = new SpeechSynthesisUtterance(c.phrase_local); window.speechSynthesis.speak(u); }}
              className="p-1.5 rounded-lg bg-violet-500/10 hover:bg-violet-500/25 text-violet-300 transition-colors text-xs">🔊</button>
          </div>
        </div>
      </motion.div>
    ))}
  </div>
);

// ─── Packing Checklist UI ──────────────────────────────────────────────────────
const PackingChecklistBubble = ({ items, sessionId }: { items: ChecklistItem[]; sessionId: string }) => {
  const storageKey = `packing_checklist_${sessionId}`;
  const [checkedItems, setCheckedItems] = useState<Record<number, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch { return {}; }
  });
  const toggle = (idx: number) => {
    const updated = { ...checkedItems, [idx]: !checkedItems[idx] };
    setCheckedItems(updated);
    localStorage.setItem(storageKey, JSON.stringify(updated));
  };
  const categories = [...new Set(items.map(i => i.category))];
  const packed = Object.values(checkedItems).filter(Boolean).length;
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs text-emerald-300/70 font-semibold uppercase tracking-wider">🎒 Packing Checklist</p>
        <span className="text-xs text-emerald-400 font-bold">{packed}/{items.length} packed</span>
      </div>
      <div className="w-full bg-black/30 rounded-full h-1.5 mb-3">
        <div className="bg-gradient-to-r from-emerald-500 to-teal-400 h-1.5 rounded-full transition-all duration-500" style={{ width: `${(packed / items.length) * 100}%` }} />
      </div>
      {categories.map(cat => (
        <div key={cat} className="mb-2">
          <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1 font-medium">{cat}</p>
          <div className="space-y-1">
            {items.filter(it => it.category === cat).map((it, i) => {
              const globalIdx = items.findIndex(x => x === it);
              return (
                <label key={i} className="flex items-center gap-2 cursor-pointer group">
                  <input type="checkbox" checked={!!checkedItems[globalIdx]} onChange={() => toggle(globalIdx)}
                    className="rounded border-emerald-500/30 bg-black/30 text-emerald-500 focus:ring-emerald-500/20 w-3.5 h-3.5 flex-shrink-0" />
                  <span className={`text-xs transition-all ${checkedItems[globalIdx] ? "line-through text-zinc-600" : "text-zinc-200 group-hover:text-emerald-200"}`}>{it.item}</span>
                </label>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
};

// ─── Flight Status Card ────────────────────────────────────────────────────────
const FlightStatusCard = ({ status }: { status: FlightStatusInfo }) => {
  const color = status.status === "On Time" || status.status === "Arrived" ? "emerald" :
    status.status === "Boarding" || status.status === "Departed" ? "amber" : "red";
  const colorMap: Record<string, string> = {
    emerald: "border-emerald-500/40 from-emerald-950/50 to-teal-950/50 text-emerald-300",
    amber: "border-amber-500/40 from-amber-950/50 to-yellow-950/50 text-amber-300",
    red: "border-red-500/40 from-red-950/50 to-orange-950/50 text-red-300",
  };
  return (
    <div className={`mt-3 rounded-2xl border bg-gradient-to-br p-4 ${colorMap[color]}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xl">✈️</span>
          <div>
            <p className="font-bold text-sm text-white">{status.flight_code}</p>
            <p className="text-xs opacity-70">{status.airline}</p>
          </div>
        </div>
        <span className={`px-3 py-1 rounded-full text-xs font-bold ${colorMap[color]} border`}>{status.status}</span>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs mt-2">
        {status.departure && <div><p className="opacity-50">Departure</p><p className="font-bold text-white">{status.departure}</p></div>}
        {status.arrival && <div><p className="opacity-50">Arrival</p><p className="font-bold text-white">{status.arrival}</p></div>}
        {status.terminal && <div><p className="opacity-50">Terminal</p><p className="font-bold text-white">{status.terminal}</p></div>}
        {status.gate && <div><p className="opacity-50">Gate</p><p className="font-bold text-white">{status.gate}</p></div>}
        {status.delay_minutes > 0 && <div className="col-span-2"><p className="opacity-50">Delay</p><p className="font-bold text-red-300">+{status.delay_minutes} min</p></div>}
      </div>
    </div>
  );
};

// ─── Proactive Alert Banner ────────────────────────────────────────────────────
const ProactiveAlertBubble = ({ alerts }: { alerts: ProactiveAlert[] }) => (
  <div className="space-y-2 mt-1">
    <p className="text-xs text-amber-300/70 font-semibold uppercase tracking-wider">⚡ TBuddy Notices</p>
    {alerts.map((alert, i) => {
      const styles: Record<string, string> = {
        critical: "border-red-500/50 bg-red-950/40 text-red-200",
        warning: "border-amber-500/40 bg-amber-950/40 text-amber-200",
        info: "border-blue-500/30 bg-blue-950/30 text-blue-200",
      };
      const icons: Record<string, string> = { critical: "🚨", warning: "⚠️", info: "💡" };
      return (
        <motion.div key={i} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.1 }}
          className={`flex gap-2.5 p-3 rounded-2xl border ${styles[alert.severity] || styles.warning}`}>
          <span className="text-base flex-shrink-0">{icons[alert.severity] || "⚠️"}</span>
          <div>
            {alert.day && <p className="text-xs font-bold opacity-70 mb-0.5">Day {alert.day}</p>}
            <p className="text-xs leading-relaxed">{alert.message}</p>
          </div>
        </motion.div>
      );
    })}
  </div>
);

// ─── Expense Update Card ───────────────────────────────────────────────────────
const CATEGORY_EMOJI: Record<string, string> = {
  Food: "🍽️", Transport: "🚌", Accommodation: "🏨", Activities: "🏄", Shopping: "🛍️", Other: "📦",
};

const ExpenseUpdateCard = ({ update }: { update: ChatMessage["expense_update"] }) => {
  if (!update) return null;
  const exp = update.logged_expense;
  const categoryEntries = Object.entries(update.category_breakdown ?? {});
  const travelers = update.travelers_count ?? 1;
  return (
    <div className="mt-3 rounded-2xl border border-green-500/30 bg-gradient-to-br from-green-950/40 to-emerald-950/40 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-lg">💸</span>
        <p className="text-xs text-green-300 font-semibold uppercase tracking-wider">Expense Logged</p>
        <span className="ml-auto text-[10px] text-zinc-500 bg-zinc-800/60 px-2 py-0.5 rounded-full">
          #{update.entry_count} entry
        </span>
      </div>

      {/* Latest expense row */}
      {exp && (
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-sm text-zinc-200 font-medium capitalize">{exp.description}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] bg-green-900/50 text-green-400 border border-green-500/20 px-2 py-0.5 rounded-full">
                {CATEGORY_EMOJI[exp.category] ?? "📦"} {exp.category}
              </span>
              {exp.date_str && (
                <span className="text-[10px] text-zinc-500">📅 {exp.date_str}</span>
              )}
            </div>
          </div>
          <span className="text-green-300 font-bold text-base whitespace-nowrap">₹{exp.amount?.toLocaleString("en-IN")}</span>
        </div>
      )}

      {/* Totals grid */}
      <div className="border-t border-green-500/20 pt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <p className="text-zinc-500">Total Logged</p>
          <p className="text-white font-bold text-sm">₹{update.total_logged?.toLocaleString("en-IN")}</p>
        </div>
        <div>
          <p className="text-zinc-500">Per Person</p>
          <p className="text-emerald-300 font-bold text-sm">₹{update.cost_per_person?.toLocaleString("en-IN")}</p>
        </div>
        <div>
          <p className="text-zinc-500">Travelers</p>
          <p className="text-zinc-300 font-bold text-sm">👥 {travelers}</p>
        </div>
      </div>

      {/* Category breakdown */}
      {categoryEntries.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider">By Category</p>
          {categoryEntries.map(([cat, amt]) => (
            <div key={cat} className="flex items-center justify-between text-xs">
              <span className="text-zinc-400">{CATEGORY_EMOJI[cat] ?? "📦"} {cat}</span>
              <span className="text-zinc-300 font-medium">₹{(amt as number).toLocaleString("en-IN")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ─── Map Pin Notification ──────────────────────────────────────────────────────
const MapPinNotice = ({ pins }: { pins: PlacePin[] }) => (
  <div className="mt-3 flex items-start gap-2 p-3 rounded-2xl border border-orange-500/30 bg-orange-950/30">
    <span className="text-base flex-shrink-0">📍</span>
    <div>
      <p className="text-xs text-orange-300 font-semibold">{pins.length} place{pins.length > 1 ? "s" : ""} pinned on your Map!</p>
      <p className="text-xs text-zinc-400 mt-0.5">{pins.map(p => p.name).join(", ")}</p>
      <p className="text-xs text-orange-400/60 mt-1">Switch to the Map tab to explore them →</p>
    </div>
  </div>
);

// ─── Trip Chat Panel ──────────────────────────────────────────────────────────
const TripChatPanel = ({
  sessionId, API_URL, onNewPins, onNewExpense
}: {
  sessionId: string | null;
  API_URL: string;
  onNewPins?: (pins: PlacePin[]) => void;
  onNewExpense?: (update: ChatMessage["expense_update"]) => void;
}) => {
  const [isOpen, setIsOpen] = useState(true);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  if (!sessionId) return null;

  const handleSendChat = async () => {
    if (!chatInput.trim() || isSending) return;

    const userMsg = chatInput.trim();
    setChatMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setChatInput("");
    setIsSending(true);

    try {
      const res = await fetch(
        `${API_URL}/api/v2/orchestrator/session/${sessionId}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: userMsg }),
        }
      );
      if (!res.ok) throw new Error("Chat request failed");
      const data = await res.json();

      // Notify parent about new map pins (Feature 1)
      if (data.place_pins && data.place_pins.length > 0 && onNewPins) {
        onNewPins(data.place_pins);
      }

      const newMsg: ChatMessage = {
        role: "assistant",
        content: data.reply,
        phrase_cards: data.phrase_cards,
        checklist: data.checklist,
        place_pins: data.place_pins,
        flight_status: data.flight_status,
        proactive_alerts: data.proactive_alerts,
        expense_update: data.expense_update,
      };
      setChatMessages((prev) => [...prev, newMsg]);

      // Notify parent about new expense (Feature 2 — Budget Tab sync)
      if (data.expense_update && onNewExpense) {
        onNewExpense(data.expense_update);
      }
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, I couldn't process that. Please try again." },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const suggestedQuestions = [
    "Show me a packing checklist",
    "How do I say 'thank you' locally?",
    "Find cafes near my hotel",
    "I spent ₹800 on lunch today",
    "Is my flight 6E202 on time?",
    "What should I wear to the temple?",
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6 text-left h-full flex flex-col"
    >
      <div className="rounded-3xl bg-gradient-to-br from-red-950/40 via-purple-950/40 to-fuchsia-950/40 border border-red-500/30 backdrop-blur-xl shadow-2xl overflow-hidden flex-1 flex flex-col">
        {/* Header / Toggle */}
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="w-full p-5 flex items-center justify-between hover:bg-white/5 transition-colors flex-shrink-0"
        >
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-red-500/20 rounded-xl animate-pulse">
              <MessageCircle className="w-6 h-6 text-red-300" />
            </div>
            <div className="text-left">
              <h3 className="text-lg font-bold bg-gradient-to-r from-red-300 via-fuchsia-300 to-violet-300 bg-clip-text text-transparent">
                TBuddy Co-Pilot
              </h3>
              <p className="text-red-200/60 text-xs mt-0.5 flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse inline-block" />
                Maps · Expenses · Phrases · Flights · Alerts
              </p>
            </div>
          </div>
          {isOpen ? (
            <ChevronUp className="w-5 h-5 text-red-300" />
          ) : (
            <ChevronDown className="w-5 h-5 text-red-300" />
          )}
        </button>

        {/* Chat body */}
        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="lg:flex-1 lg:flex lg:flex-col lg:overflow-hidden"
            >
              <div className="border-t border-red-500/20 lg:flex-1 lg:flex lg:flex-col lg:overflow-hidden">
                {/* Messages */}
                <div className="max-h-[550px] overflow-y-auto overscroll-contain p-5 space-y-4 lg:flex-1 lg:max-h-none">
                  {chatMessages.length === 0 && (
                    <div className="text-center py-8">
                      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-red-500/20 to-fuchsia-500/20 border border-red-500/20 mx-auto mb-4 flex items-center justify-center">
                        <MessageCircle className="w-8 h-8 text-red-400/60" />
                      </div>
                      <p className="text-red-200/70 text-sm font-medium mb-1">Your AI Travel Co-Pilot</p>
                      <p className="text-zinc-500 text-xs mb-6">Powered by RAG + Groq · 6 intelligent features</p>
                      <div className="grid grid-cols-2 gap-2">
                        {suggestedQuestions.map((q) => (
                          <button
                            key={q}
                            onClick={() => setChatInput(q)}
                            className="px-3 py-2.5 bg-black/30 border border-white/10 rounded-xl text-xs text-zinc-300 hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-200 transition-all text-left leading-snug"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {chatMessages.map((msg, idx) => (
                    <motion.div
                      key={idx}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      {msg.role === "user" ? (
                        <div className="max-w-[80%] p-4 rounded-3xl text-sm leading-relaxed bg-gradient-to-br from-red-600 via-fuchsia-600 to-violet-600 text-white shadow-lg shadow-red-500/10">
                          <p className="whitespace-pre-wrap">{msg.content}</p>
                        </div>
                      ) : (
                        <div className="max-w-[90%] flex flex-col gap-1">
                          {/* Assistant avatar + reply */}
                          <div className="flex items-start gap-2.5">
                            <div className="w-7 h-7 rounded-xl bg-gradient-to-br from-red-500/30 to-fuchsia-500/30 border border-red-500/20 flex items-center justify-center text-xs flex-shrink-0 mt-1">🤖</div>
                            <div className="bg-black/30 border border-red-500/20 rounded-3xl p-4 text-sm leading-relaxed text-red-100">
                              <p className="whitespace-pre-wrap">{msg.content}</p>

                              {/* Feature 3 — Proactive Alerts */}
                              {msg.proactive_alerts && msg.proactive_alerts.length > 0 && (
                                <ProactiveAlertBubble alerts={msg.proactive_alerts} />
                              )}

                              {/* Feature 6 — Phrase Cards */}
                              {msg.phrase_cards && msg.phrase_cards.length > 0 && (
                                <PhraseCardBubble cards={msg.phrase_cards} />
                              )}

                              {/* Feature 4 — Packing Checklist */}
                              {msg.checklist && msg.checklist.length > 0 && (
                                <PackingChecklistBubble items={msg.checklist} sessionId={sessionId} />
                              )}

                              {/* Feature 5 — Flight Status */}
                              {msg.flight_status && (
                                <FlightStatusCard status={msg.flight_status} />
                              )}

                              {/* Feature 2 — Expense Update */}
                              {msg.expense_update && (
                                <ExpenseUpdateCard update={msg.expense_update} />
                              )}

                              {/* Feature 1 — Map Pin Notice */}
                              {msg.place_pins && msg.place_pins.length > 0 && (
                                <MapPinNotice pins={msg.place_pins} />
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </motion.div>
                  ))}

                  {/* Typing indicator */}
                  {isSending && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-xl bg-gradient-to-br from-red-500/30 to-fuchsia-500/30 border border-red-500/20 flex items-center justify-center text-xs">🤖</div>
                        <div className="bg-black/30 border border-red-500/20 rounded-3xl px-5 py-4 flex items-center gap-1.5">
                          {[0, 0.15, 0.3].map((delay, i) => (
                            <motion.span key={i} className="w-1.5 h-1.5 rounded-full bg-red-400"
                              animate={{ y: [0, -5, 0] }} transition={{ duration: 0.7, repeat: Infinity, delay }} />
                          ))}
                        </div>
                      </div>
                    </motion.div>
                  )}

                  <div ref={chatEndRef} />
                </div>

                {/* Input */}
                <div className="p-4 border-t border-red-500/20 flex gap-3 flex-shrink-0">
                  <input
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyPress={(e) => e.key === "Enter" && handleSendChat()}
                    placeholder="Ask about your trip, log expenses, get phrases..."
                    disabled={isSending}
                    className="flex-1 bg-black/40 border border-red-500/30 rounded-2xl px-4 py-3 text-sm text-zinc-100 placeholder-red-300/30 focus:outline-none focus:border-red-400/50 focus:ring-1 focus:ring-red-400/25 disabled:opacity-50 transition-all"
                  />
                  <button
                    onClick={handleSendChat}
                    disabled={!chatInput.trim() || isSending}
                    className="px-5 py-3 bg-gradient-to-r from-red-600 via-fuchsia-600 to-violet-600 hover:from-red-500 hover:to-violet-500 disabled:from-zinc-800 disabled:to-zinc-700 text-white text-sm font-bold rounded-2xl transition-all disabled:opacity-50 shadow-md shadow-red-600/10 hover:shadow-red-600/25"
                  >
                    Send
                  </button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
};

// ─── ItineraryView ────────────────────────────────────────────────────────────
const ItineraryView = ({
  data,
  userQuery,
  sessionId,
  API_URL,
  onUpdatePlanData,
}: {
  data: PlanData;
  userQuery: string;
  sessionId: string | null;
  API_URL: string;
  onUpdatePlanData: (updatedPlan: PlanData) => void;
}) => {
  const [activeTab, setActiveTab] = useState<SectionTab>("itinerary");
  const [swappingActivityId, setSwappingActivityId] = useState<string | null>(null);
  const [swapAlternatives, setSwapAlternatives] = useState<any[]>([]);
  const [loadingSwapOptions, setLoadingSwapOptions] = useState(false);
  const [applyingSwap, setApplyingSwap] = useState(false);

  // Hotel state
  const [hotelData, setHotelData] = useState<HotelData | null>(data.hotels || null);
  const [loadingHotels, setLoadingHotels] = useState(false);
  const [hotelError, setHotelError] = useState<string | null>(null);
  const [hotelsFetched, setHotelsFetched] = useState(false);

  // Dynamic map pins from chatbot (Feature 1 — Map-Linked Chat)
  const [dynamicPins, setDynamicPins] = useState<{ name: string; lat: number; lng: number; category: string; description?: string }[]>([]);
  const handleNewPins = (pins: { name: string; lat: number; lng: number; category: string; description?: string }[]) => {
    setDynamicPins((prev) => {
      // Deduplicate by name
      const existingNames = new Set(prev.map(p => p.name));
      const newUnique = pins.filter(p => !existingNames.has(p.name));
      return [...prev, ...newUnique];
    });
    // Auto-switch to map tab so user sees pins
    setActiveTab("map");
  };

  // Feature 2 — Live Expense Tracker: accumulate all chat-logged expenses
  const [loggedExpenses, setLoggedExpenses] = useState<{
    amount: number; category: string; description: string; date_str?: string;
  }[]>([]);
  const [totalLogged, setTotalLogged] = useState(0);
  const [expenseCategoryBreakdown, setExpenseCategoryBreakdown] = useState<Record<string, number>>({});

  const handleNewExpense = (update: ChatMessage["expense_update"]) => {
    if (!update?.logged_expense) return;
    setLoggedExpenses(prev => [...prev, update.logged_expense!]);
    setTotalLogged(update.total_logged ?? 0);
    setExpenseCategoryBreakdown(update.category_breakdown ?? {});
  };

  const handleFetchHotels = async () => {
    if (!sessionId) return;
    setLoadingHotels(true);
    setHotelError(null);
    try {
      const res = await fetch(`${API_URL}/api/v2/orchestrator/session/${sessionId}/hotels`);
      if (res.status === 429) {
        const body = await res.json().catch(() => ({}));
        setHotelError(body.detail || "Rate limited. Please wait before refreshing.");
        return;
      }
      if (!res.ok) throw new Error("Failed to load hotel recommendations");
      const result: HotelData = await res.json();
      setHotelData(result);
      setHotelsFetched(true);
    } catch (err) {
      console.error(err);
      setHotelError(err instanceof Error ? err.message : "Failed to load hotels");
    } finally {
      setLoadingHotels(false);
    }
  };

  // Auto-fetch hotels on first tab click
  const handleTabChange = (tab: SectionTab) => {
    setActiveTab(tab);
    if (tab === "hotels" && !hotelsFetched && !loadingHotels) {
      handleFetchHotels();
    }
  };

  const handleFetchSwapOptions = async (activityId: string) => {
    setSwappingActivityId(activityId);
    setLoadingSwapOptions(true);
    try {
      const res = await fetch(`${API_URL}/api/v2/orchestrator/session/${sessionId}/swap-options?activity_id=${activityId}`);
      if (!res.ok) throw new Error("Failed to load options");
      const result = await res.json();
      setSwapAlternatives(result.alternatives || []);
    } catch (err) {
      console.error(err);
      alert("Failed to load swap alternatives.");
    } finally {
      setLoadingSwapOptions(false);
    }
  };

  const handleApplySwap = async (activityId: string, alternative: any) => {
    if (!sessionId) return;
    setApplyingSwap(true);
    try {
      const res = await fetch(`${API_URL}/api/v2/orchestrator/session/${sessionId}/swap-apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          activity_id: activityId,
          selected_alternative: alternative
        })
      });
      if (!res.ok) throw new Error("Failed to apply swap");
      const result = await res.json();
      if (result.success) {
        onUpdatePlanData({
          ...data,
          itinerary: result.itinerary.itinerary_days || result.itinerary || [],
          route_optimization: result.route_optimization
        });
        setSwappingActivityId(null);
      }
    } catch (err) {
      console.error(err);
      alert("Failed to swap activity. Please try again.");
    } finally {
      setApplyingSwap(false);
    }
  };
  const currency = data.budget?.currency || "INR";
  const fmt = (n: number) => new Intl.NumberFormat("en-IN", { style:"currency", currency, maximumFractionDigits:0 }).format(n||0);
  const budget: Budget = {
    total: data.budget?.total || 0,
    transportation: data.budget?.transportation || 0,
    accommodation: data.budget?.accommodation || 0,
    food: data.budget?.food || 0,
    activities: data.budget?.activities || 0,
    currency: data.budget?.currency || "INR",
  };
  const remaining = budget.total > 0 ? budget.total - totalLogged : 0;
  const spendPct = budget.total > 0 ? Math.min(100, Math.round((totalLogged / budget.total) * 100)) : 0;

  // Badge text for each tab
  const badges: Record<SectionTab, string> = {
    itinerary: `${data.itinerary.length} day${data.itinerary.length !== 1 ? "s" : ""}`,
    map: data.maps ? "✓" : "—",
    weather: `${data.weather.filter(w => w.temperature_max != null || w.description).length} days`,
    budget: fmt(budget.total),
    hotels: hotelData ? `${hotelData.hotels.length}` : "—",
    events: `${data.events?.length || 0} found`,
  };

  return (
    <motion.div initial={{ opacity:0 }} animate={{ opacity:1 }} className="w-full h-full max-w-7xl mx-auto px-4 overflow-hidden">
      <div className="flex flex-col lg:flex-row gap-8 h-full overflow-hidden">
        {/* Left Column: Itinerary Details (scrolls internally) */}
        <div className="flex-1 lg:w-2/3 h-full overflow-y-auto pr-2 scrollbar-none pb-12">
      {/* Query bubble */}
      <motion.div initial={{ opacity:0, y:-20 }} animate={{ opacity:1, y:0 }} className="mb-6 p-6 bg-zinc-900/50 backdrop-blur-md border border-zinc-800 rounded-2xl">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-400 to-red-500 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">You</div>
          <p className="text-zinc-300 text-lg">{userQuery}</p>
        </div>
      </motion.div>
      {/* AI header */}
      <motion.div initial={{ opacity:0, y:-20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.1 }} className="mb-6 flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-red-700 to-red-900 flex items-center justify-center"><span className="text-xl">🎪</span></div>
        <div><h2 className="text-2xl font-light text-zinc-100">Ringmaster</h2><p className="text-sm text-zinc-500">Your AI Travel Planner</p></div>
      </motion.div>

      {/* ── Tab Bar ──────────────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity:0, y:10 }}
        animate={{ opacity:1, y:0 }}
        transition={{ delay:0.15 }}
        className="mb-8 sticky top-0 z-30"
      >
        <div className="flex items-center gap-1 p-1.5 bg-black/50 backdrop-blur-xl border border-zinc-800/60 rounded-2xl shadow-2xl overflow-x-auto scrollbar-none">
          {SECTION_TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                className={`relative flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium whitespace-nowrap transition-all duration-200 ${
                  isActive
                    ? "bg-gradient-to-r from-violet-600/80 to-fuchsia-600/60 text-white shadow-lg shadow-violet-500/20"
                    : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
                }`}
              >
                <span className="text-base">{tab.icon}</span>
                <span>{tab.label}</span>
                {badges[tab.id] && badges[tab.id] !== "—" && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                    isActive
                      ? "bg-white/20 text-white/90"
                      : "bg-zinc-800 text-zinc-500"
                  }`}>
                    {badges[tab.id]}
                  </span>
                )}
                {isActive && (
                  <motion.div
                    layoutId="activeTabIndicator"
                    className="absolute inset-0 rounded-xl bg-gradient-to-r from-violet-600/80 to-fuchsia-600/60 -z-10"
                    transition={{ type: "spring", stiffness: 380, damping: 30 }}
                  />
                )}
              </button>
            );
          })}
        </div>
      </motion.div>

      {/* ── Tab Content ─────────────────────────────────────────────────────── */}
      <AnimatePresence mode="wait">
        {/* ── Itinerary Tab ─────────────────────────────────────────────────── */}
        {activeTab === "itinerary" && (
          <motion.div
            key="tab-itinerary"
            initial={{ opacity:0, y:16 }}
            animate={{ opacity:1, y:0 }}
            exit={{ opacity:0, y:-12 }}
            transition={{ duration:0.25 }}
          >
            {data.itinerary?.length > 0 ? data.itinerary.map((day, index) => {
              const w = data.weather?.[index];
              return (
                <motion.div key={day.day || index} initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.05+index*0.06 }}
                  className="mb-6 p-6 bg-black/40 backdrop-blur-md border border-zinc-800/50 rounded-2xl hover:border-zinc-700/50 transition-all">
                  <div className="flex justify-between items-start mb-4">
                    <div>
                      <h3 className="text-2xl font-light text-zinc-100 mb-1">Day {day.day}</h3>
                      <p className="text-zinc-400">{fmtDate(day.date)}</p>
                    </div>
                    <div className="text-right flex flex-col items-end gap-1">
                      {day.estimated_cost != null && <div className="text-lg text-amber-400 font-semibold">{fmt(day.estimated_cost)}</div>}
                      {w && (
                        <div className="flex items-center gap-1.5 text-sm text-blue-300">
                          <span>{weatherEmoji(w.description, w.precipitation_chance)}</span>
                          {w.temperature_max != null && <span>{Math.round(w.temperature_max)}°C</span>}
                          {w.temperature_min != null && <span className="text-zinc-500">/ {Math.round(w.temperature_min)}°C</span>}
                        </div>
                      )}
                      {w?.precipitation_chance != null && w.precipitation_chance > 0 && (
                        <div className="text-xs text-blue-400">💧 {w.precipitation_chance}% rain</div>
                      )}
                    </div>
                  </div>
                  {w && w.precipitation_chance != null && w.precipitation_chance > 40 && (
                    <div className="mb-3 px-3 py-2 bg-blue-900/20 border border-blue-700/20 rounded-lg text-xs text-blue-300 flex items-center gap-2">
                      <span>🌧️</span>{w.precipitation_chance > 70 ? "High rain expected — carry umbrella, prefer indoor attractions" : "Moderate rain chance — keep umbrella handy"}
                    </div>
                  )}
                  {day.notes && (
                    <div className="mb-4 p-3 bg-amber-900/10 border border-amber-800/30 rounded-lg">
                      <p className="text-sm text-amber-200/80 flex items-start gap-2"><span className="text-amber-500">⚠️</span>{day.notes}</p>
                    </div>
                  )}
                  <div className="space-y-3">
                    {day.activities.map((act, ai) => {
                      const activityId = `day_${day.day}_act_${ai}`;
                      const isThisSwapping = swappingActivityId === activityId;
                      return (
                        <div key={ai} className="flex flex-col gap-2">
                          <motion.div initial={{ opacity:0, x:-10 }} animate={{ opacity:1, x:0 }} transition={{ delay:0.08+index*0.06+ai*0.03 }} className="flex gap-3 items-center justify-between group">
                            <div className="flex gap-3 items-start">
                              <div className="w-2 h-2 mt-2 rounded-full bg-red-800 group-hover:bg-red-500 transition-colors flex-shrink-0" />
                              <p className="text-zinc-300 group-hover:text-zinc-100 transition-colors">{act}</p>
                            </div>
                            {sessionId && (
                              <button
                                onClick={() => handleFetchSwapOptions(activityId)}
                                disabled={loadingSwapOptions || applyingSwap}
                                className="opacity-0 group-hover:opacity-100 text-xs px-2.5 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white rounded-lg transition-all flex items-center gap-1.5 ml-4 flex-shrink-0 border border-zinc-700/50"
                              >
                                <span>🔄</span> Swap
                              </button>
                            )}
                          </motion.div>
                          
                          {/* Swap alternatives sub-panel */}
                          {isThisSwapping && (
                            <div className="ml-5 mt-2 p-4 bg-zinc-950/80 border border-violet-500/20 rounded-xl">
                              {loadingSwapOptions ? (
                                <div className="flex items-center gap-2 text-sm text-zinc-400">
                                  <div className="w-4 h-4 border-2 border-zinc-600 border-t-violet-500 rounded-full animate-spin" />
                                  Finding alternative spots...
                                </div>
                              ) : (
                                <div className="space-y-3">
                                  <div className="flex justify-between items-center mb-1">
                                    <span className="text-xs font-semibold text-violet-300">Alternative Options:</span>
                                    <button 
                                      onClick={() => setSwappingActivityId(null)}
                                      className="text-xs text-zinc-500 hover:text-zinc-300"
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                  {swapAlternatives.length === 0 ? (
                                    <p className="text-xs text-zinc-500">No alternatives found.</p>
                                  ) : (
                                    swapAlternatives.map((alt, idx) => (
                                      <div key={idx} className="p-3 bg-zinc-900/50 hover:bg-zinc-900 border border-zinc-800/80 rounded-lg flex justify-between items-center gap-4 transition-all">
                                        <div className="min-w-0">
                                          <div className="flex items-center gap-2">
                                            <span className="font-semibold text-sm text-white">{alt.name}</span>
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 capitalize">{alt.category}</span>
                                          </div>
                                          <p className="text-xs text-zinc-400 truncate mt-0.5">{alt.description}</p>
                                          <span className="text-[10px] text-amber-400 font-medium mt-1 block">Cost: {alt.estimated_cost}</span>
                                        </div>
                                        <button
                                          onClick={() => handleApplySwap(activityId, alt)}
                                          disabled={applyingSwap}
                                          className="px-3 py-1.5 bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 text-white text-xs font-bold rounded-lg shadow-md transition-all flex-shrink-0"
                                        >
                                          {applyingSwap ? "Swapping..." : "Select"}
                                        </button>
                                      </div>
                                    ))
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </motion.div>
              );
            }) : (
              <div className="text-center text-zinc-400 py-12">
                <p className="text-xl mb-2">No itinerary days found</p>
                <p className="text-sm">The plan was generated but contained no day-by-day schedule.</p>
              </div>
            )}
          </motion.div>
        )}

        {/* ── Map & Route Tab ───────────────────────────────────────────────── */}
        {activeTab === "map" && (
          <motion.div
            key="tab-map"
            initial={{ opacity:0, y:16 }}
            animate={{ opacity:1, y:0 }}
            exit={{ opacity:0, y:-12 }}
            transition={{ duration:0.25 }}
          >
            {data.maps ? (
              <>
              <RouteCard maps={data.maps} />
                {data.maps.travel_options && (
                  <TravelOptionsCard
                    travelOptions={data.maps.travel_options}
                    origin={data.maps.origin}
                    destination={data.maps.destination}
                  />
                )}
                <TripMap
                  mapsData={data.maps}
                  itineraryDays={data.itinerary}
                  origin={data.maps.origin}
                  destination={data.maps.destination}
                  routeOptimization={data.route_optimization}
                  hotels={hotelData?.hotels || []}
                  dynamicPins={dynamicPins}
                />
              </>
            ) : (
              <div className="text-center text-zinc-400 py-16">
                <span className="text-4xl block mb-3">🗺️</span>
                <p className="text-xl mb-2">No map data available</p>
                <p className="text-sm">Route information was not generated for this trip.</p>
              </div>
            )}
          </motion.div>
        )}

        {/* ── Weather Tab ───────────────────────────────────────────────────── */}
        {activeTab === "weather" && (
          <motion.div
            key="tab-weather"
            initial={{ opacity:0, y:16 }}
            animate={{ opacity:1, y:0 }}
            exit={{ opacity:0, y:-12 }}
            transition={{ duration:0.25 }}
          >
            <WeatherStrip weather={data.weather} />
            {(!data.weather || data.weather.filter(w => w.temperature_max != null || w.description).length === 0) && (
              <div className="text-center text-zinc-400 py-16">
                <span className="text-4xl block mb-3">🌤️</span>
                <p className="text-xl mb-2">No weather data available</p>
                <p className="text-sm">Weather forecast was not generated for this trip.</p>
              </div>
            )}
          </motion.div>
        )}

        {/* ── Budget Tab ────────────────────────────────────────────────────── */}
        {activeTab === "budget" && (
          <motion.div
            key="tab-budget"
            initial={{ opacity:0, y:16 }}
            animate={{ opacity:1, y:0 }}
            exit={{ opacity:0, y:-12 }}
            transition={{ duration:0.25 }}
          >
            <motion.div initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }}
              className="mb-8 p-6 bg-gradient-to-br from-red-900/20 to-amber-900/20 backdrop-blur-md border border-red-800/30 rounded-2xl">
              <h3 className="text-xl font-light text-zinc-100 mb-6 flex items-center gap-2"><span>💰</span> Budget Breakdown</h3>
              {/* Total highlight */}
              <div className="text-center mb-8">
                <div className="text-4xl font-bold text-amber-400">{fmt(budget.total)}</div>
                <div className="text-sm text-zinc-400 mt-1">Estimated Total</div>
              </div>
              {/* Category grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                  { label:"Transport", value:budget.transportation, icon:"🚗", color:"from-violet-900/30 border-violet-700/30" },
                  { label:"Accommodation", value:budget.accommodation, icon:"🏨", color:"from-blue-900/30 border-blue-700/30" },
                  { label:"Food", value:budget.food, icon:"🍽️", color:"from-orange-900/30 border-orange-700/30" },
                  { label:"Activities", value:budget.activities, icon:"🎯", color:"from-emerald-900/30 border-emerald-700/30" },
                ].map(({ label, value, icon, color }) => (
                  <div key={label} className={`p-4 bg-gradient-to-br ${color} border rounded-xl text-center`}>
                    <div className="text-2xl mb-2">{icon}</div>
                    <div className="text-lg font-semibold text-zinc-100">{fmt(value)}</div>
                    <div className="text-xs text-zinc-400 mt-1">{label}</div>
                    {budget.total > 0 && (
                      <div className="mt-2 h-1.5 bg-black/30 rounded-full overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${Math.round((value / budget.total) * 100)}%` }}
                          transition={{ delay: 0.3, duration: 0.6 }}
                          className="h-full bg-amber-400/60 rounded-full"
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>
              {/* Per-day estimate */}
              {data.itinerary.length > 0 && budget.total > 0 && (
                <div className="mt-6 pt-4 border-t border-zinc-800/50 text-center">
                  <span className="text-sm text-zinc-400">≈ </span>
                  <span className="text-lg font-semibold text-zinc-200">{fmt(Math.round(budget.total / data.itinerary.length))}</span>
                  <span className="text-sm text-zinc-400"> per day</span>
                </div>
              )}
            </motion.div>

            {/* ── Live Expense Tracker (from TBuddy chat) ────────────────── */}
            {loggedExpenses.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
                className="p-6 bg-gradient-to-br from-green-900/20 to-emerald-900/10 backdrop-blur-md border border-green-800/30 rounded-2xl"
              >
                <h3 className="text-xl font-light text-zinc-100 mb-6 flex items-center gap-2">
                  <span>💸</span> Actual Spending
                  <span className="ml-auto text-xs text-green-400 bg-green-900/40 border border-green-700/30 px-2 py-1 rounded-full">
                    Logged via TBuddy
                  </span>
                </h3>

                {/* Spent vs Planned bar */}
                {budget.total > 0 && (
                  <div className="mb-6">
                    <div className="flex justify-between text-sm mb-2">
                      <span className="text-zinc-400">Spent so far</span>
                      <span className={`font-semibold ${totalLogged > budget.total ? "text-red-400" : "text-green-400"}`}>
                        {fmt(totalLogged)} / {fmt(budget.total)} ({spendPct}%)
                      </span>
                    </div>
                    <div className="h-3 bg-zinc-800 rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${spendPct}%` }}
                        transition={{ duration: 0.7 }}
                        className={`h-full rounded-full ${
                          spendPct > 90 ? "bg-red-500" : spendPct > 70 ? "bg-amber-400" : "bg-emerald-500"
                        }`}
                      />
                    </div>
                    <div className="flex justify-between text-xs text-zinc-500 mt-1">
                      <span>₹0</span>
                      <span className={remaining < 0 ? "text-red-400 font-medium" : "text-zinc-400"}>
                        {remaining < 0 ? `Over budget by ${fmt(Math.abs(remaining))}` : `${fmt(remaining)} remaining`}
                      </span>
                    </div>
                  </div>
                )}

                {/* Category breakdown */}
                {Object.keys(expenseCategoryBreakdown).length > 0 && (
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
                    {Object.entries(expenseCategoryBreakdown).map(([cat, amt]) => (
                      <div key={cat} className="p-3 bg-black/20 border border-zinc-700/30 rounded-xl text-center">
                        <div className="text-xl mb-1">{({Food:"🍽️",Transport:"🚌",Accommodation:"🏨",Activities:"🏄",Shopping:"🛍️",Other:"📦"})[cat] ?? "📦"}</div>
                        <div className="text-sm font-semibold text-zinc-100">{fmt(amt as number)}</div>
                        <div className="text-xs text-zinc-500 mt-0.5">{cat}</div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Individual expense log */}
                <div className="space-y-2">
                  <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Expense Log</p>
                  {loggedExpenses.map((exp, i) => (
                    <div key={i} className="flex items-center justify-between text-sm py-2 border-b border-zinc-800/40 last:border-0">
                      <div className="flex items-center gap-2">
                        <span>{({Food:"🍽️",Transport:"🚌",Accommodation:"🏨",Activities:"🏄",Shopping:"🛍️",Other:"📦"})[exp.category] ?? "📦"}</span>
                        <div>
                          <p className="text-zinc-300 capitalize">{exp.description}</p>
                          {exp.date_str && <p className="text-[11px] text-zinc-600">{exp.date_str}</p>}
                        </div>
                      </div>
                      <span className="text-green-300 font-semibold">{fmt(exp.amount)}</span>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </motion.div>
        )}

        {/* ── Events Tab ────────────────────────────────────────────────────── */}
        {activeTab === "events" && (
          <motion.div
            key="tab-events"
            initial={{ opacity:0, y:16 }}
            animate={{ opacity:1, y:0 }}
            exit={{ opacity:0, y:-12 }}
            transition={{ duration:0.25 }}
          >
            <EventsCard events={data.events} />
            {(!data.events || data.events.length === 0) && (
              <div className="text-center text-zinc-400 py-16">
                <span className="text-4xl block mb-3">🎭</span>
                <p className="text-xl mb-2">No events found</p>
                <p className="text-sm">No local events or festivals were found for your travel dates.</p>
              </div>
            )}
          </motion.div>
        )}

        {/* ── Hotels Tab ─────────────────────────────────────────────────────── */}
        {activeTab === "hotels" && (
          <motion.div
            key="tab-hotels"
            initial={{ opacity:0, y:16 }}
            animate={{ opacity:1, y:0 }}
            exit={{ opacity:0, y:-12 }}
            transition={{ duration:0.25 }}
          >
            <HotelCard
              hotels={hotelData?.hotels || []}
              source={hotelData?.source || ""}
              generatedAt={hotelData?.generated_at || ""}
              destination={hotelData?.destination || data.maps?.destination || "your destination"}
              onRetry={handleFetchHotels}
              loading={loadingHotels}
              error={hotelError}
            />
          </motion.div>
        )}
      </AnimatePresence>
        </div>

        {/* Right Column: Chat Co-Pilot (scrolls internally, doesn't affect left column) */}
        <div className="lg:w-1/3 h-[500px] lg:h-full flex flex-col pb-12 flex-shrink-0">
          {sessionId && (
            <TripChatPanel sessionId={sessionId} API_URL={API_URL} onNewPins={handleNewPins} onNewExpense={handleNewExpense} />
          )}
        </div>
      </div>
    </motion.div>
  );
};

// ─── Main Page ────────────────────────────────────────────────────────────────
const Page = () => {
  const [titleIdx, setTitleIdx] = useState(0);
  const [isPlanning, setIsPlanning] = useState(false);
  const [planData, setPlanData] = useState<PlanData | null>(null);
  const [userQuery, setUserQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [preferenceWeights, setPreferenceWeights] = useState<Record<string, number> | null>(null);
  const [showPreferencePoll, setShowPreferencePoll] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const handleUpdatePlanData = (updatedPlan: PlanData) => {
    setPlanData(updatedPlan);
  };
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8010";

  useEffect(() => { const t = setInterval(() => setTitleIdx(p => (p+1)%titles.length), 4000); return () => clearInterval(t); }, []);

  const handlePlanSubmit = useCallback(async (query: string) => {
    setUserQuery(query); setIsPlanning(true); setError(null); setPlanData(null);
    try {
      const startRes = await fetch(`${API_URL}/api/v2/orchestrator/plan`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ query, session_id: null, include_travel_options: true, ...(preferenceWeights ? { preference_weights: preferenceWeights } : {}) }),
      });
      if (!startRes.ok) throw new Error((await startRes.json().catch(()=>({}))).detail || "Failed to start plan");
      const { session_id } = await startRes.json();
      if (!session_id) throw new Error("No session ID returned");
      setSessionId(session_id);

      for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 3000));
        const res = await fetch(`${API_URL}/api/v2/orchestrator/session/${session_id}/result`);
        if (res.status === 400) continue;
        if (!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || "Failed to fetch result");
        const result = await res.json();
        if (result.status !== "completed") continue;

        console.log("RAW RESULT:", JSON.stringify(result, null, 2));

        const expandedDates = expandTravelDates(result.travel_dates || []);
        const itineraryDays: ItineraryDay[] = result.itinerary?.itinerary_days || [];

        // Weather — normalize field names
        let weather: DayWeather[] = [];
        if (Array.isArray(result.weather)) weather = result.weather.map(normalizeWeatherDay);
        else if (result.weather?.weather_forecast) weather = result.weather.weather_forecast.map(normalizeWeatherDay);

        // Budget
        let budget: Budget = { total:0, transportation:0, accommodation:0, food:0, activities:0, currency:"INR" };
        if (result.budget) {
          if (typeof result.budget.total === "number") budget = result.budget;
          else if (result.budget.budget_breakdown) budget = result.budget.budget_breakdown;
        }

        // Maps — normalize field names
        let maps: MapsData | null = null;
        if (result.maps && typeof result.maps === "object") maps = normalizeMaps(result.maps as Record<string, unknown>);

        // Events
        let events: EventInfo[] = [];
        if (Array.isArray(result.events)) events = result.events;
        else if (result.events?.events) events = result.events.events;

        const finalDays = itineraryDays.length >= expandedDates.length && itineraryDays.length > 0
          ? itineraryDays : reconstructItineraryDays(itineraryDays, expandedDates, budget);

        setPlanData({
          itinerary: finalDays,
          budget,
          weather,
          maps,
          events,
          processing_time_ms: 0,
          route_optimization: result.route_optimization || result.itinerary?.route_optimization,
        });
        setIsPlanning(false);
        return;
      }
      throw new Error("Timed out — please try again");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      console.error("Plan error:", msg); setError(msg); setIsPlanning(false);
    }
  }, [API_URL, preferenceWeights]);

  const handleNewPlan = () => { setPlanData(null); setIsPlanning(false); setUserQuery(""); setError(null); setPreferenceWeights(null); setShowPreferencePoll(true); setSessionId(null); };

  return (
    <div className="h-screen w-screen overflow-hidden bg-black relative">
      <LightRaysBackground /><HyperspeedBackground />
      <div className="bg-black/60 inset-0 absolute" />
      <div className="relative z-10 h-full w-full pt-16 flex flex-col overflow-hidden">
        <AnimatePresence mode="wait">
          {!isPlanning && !planData && (
            <motion.div key="landing" initial={{ opacity:0 }} animate={{ opacity:1 }} exit={{ opacity:0 }}
              className="h-full flex flex-col items-center px-4 py-4 overflow-y-auto">
              <div className="mt-28 mb-8 text-center">
                <AnimatePresence mode="wait">
                  <motion.h1 key={titleIdx} initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} exit={{ opacity:0, y:-20 }} transition={{ duration:0.5 }}
                    className="text-5xl font-light bg-gradient-to-r from-white via-zinc-300 to-zinc-700 bg-clip-text text-transparent mb-4">
                    {titles[titleIdx]}
                  </motion.h1>
                </AnimatePresence>
                <motion.p initial={{ opacity:0 }} animate={{ opacity:1 }} transition={{ delay:0.2 }} className="text-zinc-400 text-lg">
                  Describe your dream trip and let AI craft the perfect itinerary
                </motion.p>
              </div>

              {/* Pre-Trip Preference Poll */}
              {showPreferencePoll ? (
                <div className="w-full flex justify-center mb-6">
                  <PreferencePoll
                    onSubmit={(weights) => {
                      setPreferenceWeights(weights);
                      setShowPreferencePoll(false);
                    }}
                    onSkip={() => setShowPreferencePoll(false)}
                  />
                </div>
              ) : (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mb-6"
                >
                  {preferenceWeights ? (
                    <div className="flex items-center gap-3 px-5 py-2.5 bg-violet-500/10 border border-violet-500/25 rounded-full backdrop-blur-md">
                      <span className="text-emerald-400 text-sm">✅ Preferences applied</span>
                      <button
                        onClick={() => setShowPreferencePoll(true)}
                        className="text-xs text-violet-300 hover:text-violet-100 underline underline-offset-2 transition-colors"
                      >
                        Edit
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setShowPreferencePoll(true)}
                      className="flex items-center gap-2 px-5 py-2.5 bg-zinc-800/50 border border-zinc-700/50 rounded-full text-sm text-zinc-400 hover:text-zinc-200 hover:border-violet-500/30 transition-all backdrop-blur-md"
                    >
                      <span>⚖️</span> Set travel preferences
                    </button>
                  )}
                </motion.div>
              )}

              <TypewriterPrompt onSubmit={handlePlanSubmit} />
            </motion.div>
          )}
          {isPlanning && !planData && (
            <motion.div key="loading" initial={{ opacity:0, scale:0.9 }} animate={{ opacity:1, scale:1 }} exit={{ opacity:0, scale:0.9 }} className="h-full flex items-center justify-center">
              <LoadingState />
            </motion.div>
          )}
          {planData && (
            <motion.div key="results" initial={{ opacity:0 }} animate={{ opacity:1 }} className="h-full flex flex-col overflow-hidden">
              <div className="flex-shrink-0 backdrop-blur-xl bg-black/80 border-b border-zinc-800 px-4 py-4 z-20">
                <div className="max-w-6xl mx-auto flex justify-between items-center">
                  <motion.button whileHover={{ scale:1.05 }} whileTap={{ scale:0.95 }} onClick={handleNewPlan}
                    className="px-4 py-2 bg-zinc-800/50 hover:bg-zinc-700/50 border border-zinc-700 rounded-lg text-zinc-300 transition-all">← New Plan</motion.button>
                  <div className="text-zinc-400 text-sm">{planData.itinerary.length} day{planData.itinerary.length!==1?"s":""} planned</div>
                </div>
              </div>
              <div className="flex-1 overflow-hidden pt-6">
                <ItineraryView
                  data={planData}
                  userQuery={userQuery}
                  sessionId={sessionId}
                  API_URL={API_URL}
                  onUpdatePlanData={handleUpdatePlanData}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {error && (
            <motion.div initial={{ opacity:0, y:50 }} animate={{ opacity:1, y:0 }} exit={{ opacity:0, y:50 }}
              className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 w-full max-w-md px-4">
              <div className="bg-red-900/90 backdrop-blur-md border border-red-700 rounded-xl p-4 flex items-center gap-3 shadow-2xl">
                <span className="text-red-200 text-xl">❌</span>
                <p className="text-red-100 flex-1 text-sm">{error}</p>
                <button onClick={() => setError(null)} className="text-red-300 hover:text-white ml-2 text-lg leading-none">✕</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default Page;