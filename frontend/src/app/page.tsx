"use client";
import { useState, useEffect, useCallback, memo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import dynamic from "next/dynamic";
import Hyperspeed from "@/components/Hyperspeed/Hyperspeed";

// Leaflet needs `window`, so load TripMap only on the client
const TripMap = dynamic(() => import("@/components/TripMap"), { ssr: false });

const HyperspeedBackground = memo(function HyperspeedBackground() {
  return (
    <div className="absolute scale-60 -left-75 -top-50 bottom-0 right-0 h-full w-full pointer-events-none">
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
interface MapsData { origin?: string; destination?: string; primary_route?: RouteInfo; alternative_routes?: Record<string, RouteInfo>; route_analysis?: string; }
interface EventInfo { name?: string; date?: string; time?: string; venue?: string; category?: string; description?: string; price_min?: number; price_max?: number; currency?: string; }
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
        {Object.entries(alts).filter(([, r]) => r.distance || r.duration).map(([mode, route]) => (
          <div key={mode} className="p-4 bg-black/20 border border-emerald-800/20 rounded-xl">
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

// ─── ItineraryView ────────────────────────────────────────────────────────────
const ItineraryView = ({ data, userQuery }: { data: PlanData; userQuery: string }) => {
  const currency = data.budget?.currency || "INR";
  const fmt = (n: number) => new Intl.NumberFormat("en-IN", { style:"currency", currency, maximumFractionDigits:0 }).format(n||0);
  const budget: Budget = { total:0, transportation:0, accommodation:0, food:0, activities:0, currency:"INR", ...(data.budget||{}) };
  return (
    <motion.div initial={{ opacity:0 }} animate={{ opacity:1 }} className="w-full max-w-6xl mx-auto px-4 pb-20">
      {/* Query bubble */}
      <motion.div initial={{ opacity:0, y:-20 }} animate={{ opacity:1, y:0 }} className="mb-8 p-6 bg-zinc-900/50 backdrop-blur-md border border-zinc-800 rounded-2xl">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-400 to-red-500 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">You</div>
          <p className="text-zinc-300 text-lg">{userQuery}</p>
        </div>
      </motion.div>
      {/* AI header */}
      <motion.div initial={{ opacity:0, y:-20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.1 }} className="mb-8 flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-red-700 to-red-900 flex items-center justify-center"><span className="text-xl">🎪</span></div>
        <div><h2 className="text-2xl font-light text-zinc-100">Ringmaster</h2><p className="text-sm text-zinc-500">Your AI Travel Planner</p></div>
      </motion.div>
      {/* Budget */}
      <motion.div initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.2 }}
        className="mb-8 p-6 bg-gradient-to-br from-red-900/20 to-amber-900/20 backdrop-blur-md border border-red-800/30 rounded-2xl">
        <h3 className="text-xl font-light text-zinc-100 mb-4 flex items-center gap-2"><span>💰</span> Budget Breakdown</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[{label:"Total",value:budget.total,h:true},{label:"Transport",value:budget.transportation},{label:"Stay",value:budget.accommodation},{label:"Food",value:budget.food},{label:"Activities",value:budget.activities}].map(({label,value,h})=>(
            <div key={label} className="text-center">
              <div className={`font-bold ${h?"text-2xl text-amber-400":"text-lg text-zinc-300"}`}>{fmt(value)}</div>
              <div className="text-sm text-zinc-400">{label}</div>
            </div>
          ))}
        </div>
      </motion.div>
      {/* Weather */}
      <WeatherStrip weather={data.weather} />
      {/* Route */}
      {data.maps && <RouteCard maps={data.maps} />}
      {/* Interactive Map */}
      {data.maps && (
        <TripMap
          mapsData={data.maps}
          itineraryDays={data.itinerary}
          origin={data.maps.origin}
          destination={data.maps.destination}
          routeOptimization={data.route_optimization}
        />
      )}
      {/* Events */}
      <EventsCard events={data.events} />
      {/* Days */}
      {data.itinerary?.length > 0 ? data.itinerary.map((day, index) => {
        const w = data.weather?.[index];
        return (
          <motion.div key={day.day} initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.4+index*0.08 }}
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
              {day.activities.map((act, ai) => (
                <motion.div key={ai} initial={{ opacity:0, x:-10 }} animate={{ opacity:1, x:0 }} transition={{ delay:0.5+index*0.08+ai*0.04 }} className="flex gap-3 items-start group">
                  <div className="w-2 h-2 mt-2 rounded-full bg-red-800 group-hover:bg-red-500 transition-colors flex-shrink-0" />
                  <p className="text-zinc-300 group-hover:text-zinc-100 transition-colors">{act}</p>
                </motion.div>
              ))}
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
  );
};

// ─── Main Page ────────────────────────────────────────────────────────────────
const Page = () => {
  const [titleIdx, setTitleIdx] = useState(0);
  const [isPlanning, setIsPlanning] = useState(false);
  const [planData, setPlanData] = useState<PlanData | null>(null);
  const [userQuery, setUserQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8010";

  useEffect(() => { const t = setInterval(() => setTitleIdx(p => (p+1)%titles.length), 4000); return () => clearInterval(t); }, []);

  const handlePlanSubmit = useCallback(async (query: string) => {
    setUserQuery(query); setIsPlanning(true); setError(null); setPlanData(null);
    try {
      const startRes = await fetch(`${API_URL}/api/v2/orchestrator/plan`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ query, session_id: null }),
      });
      if (!startRes.ok) throw new Error((await startRes.json().catch(()=>({}))).detail || "Failed to start plan");
      const { session_id } = await startRes.json();
      if (!session_id) throw new Error("No session ID returned");

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
  }, [API_URL]);

  const handleNewPlan = () => { setPlanData(null); setIsPlanning(false); setUserQuery(""); setError(null); };

  return (
    <div className="h-screen w-screen overflow-hidden bg-black relative">
      <LightRaysBackground /><HyperspeedBackground />
      <div className="bg-black/60 inset-0 absolute" />
      <div className="relative z-10 h-full w-full">
        <AnimatePresence mode="wait">
          {!isPlanning && !planData && (
            <motion.div key="landing" initial={{ opacity:0 }} animate={{ opacity:1 }} exit={{ opacity:0 }}
              className="h-full flex flex-col items-center justify-between px-4 py-4">
              <div className="mt-40 mb-12 text-center">
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
              <TypewriterPrompt onSubmit={handlePlanSubmit} />
            </motion.div>
          )}
          {isPlanning && !planData && (
            <motion.div key="loading" initial={{ opacity:0, scale:0.9 }} animate={{ opacity:1, scale:1 }} exit={{ opacity:0, scale:0.9 }} className="h-full flex items-center justify-center">
              <LoadingState />
            </motion.div>
          )}
          {planData && (
            <motion.div key="results" initial={{ opacity:0 }} animate={{ opacity:1 }} className="h-full overflow-y-auto">
              <div className="sticky top-0 z-20 backdrop-blur-xl bg-black/80 border-b border-zinc-800 px-4 py-4">
                <div className="max-w-6xl mx-auto flex justify-between items-center">
                  <motion.button whileHover={{ scale:1.05 }} whileTap={{ scale:0.95 }} onClick={handleNewPlan}
                    className="px-4 py-2 bg-zinc-800/50 hover:bg-zinc-700/50 border border-zinc-700 rounded-lg text-zinc-300 transition-all">← New Plan</motion.button>
                  <div className="text-zinc-400 text-sm">{planData.itinerary.length} day{planData.itinerary.length!==1?"s":""} planned</div>
                </div>
              </div>
              <div className="pt-8"><ItineraryView data={planData} userQuery={userQuery} /></div>
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