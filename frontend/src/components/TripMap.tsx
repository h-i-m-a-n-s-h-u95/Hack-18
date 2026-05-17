"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

// ── Types ─────────────────────────────────────────────────────────────────────
interface Coord { lat: number; lng: number; label?: string }
interface RoutePolyline {
  coordinates: Coord[];
  distance?: string;
  duration?: string;
  transport_mode: string;
}
interface MapsData {
  origin?: string;
  destination?: string;
  origin_city?: string;
  destination_city?: string;
  origin_coords?: Coord;
  destination_coords?: Coord;
  polyline?: Coord[];
  primary_route?: { distance?: string; duration?: string; transport_mode?: string };
  alternative_routes?: Record<string, { distance?: string; duration?: string; transport_mode?: string }>;
  route_analysis?: string;
  recommended_mode?: string;
}
interface ItineraryDay { day: number; date: string; activities: string[] }
interface TripMapProps {
  mapsData: MapsData;
  itineraryDays?: ItineraryDay[];
  origin?: string;
  destination?: string;
  apiBaseUrl?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const MODE_COLOURS: Record<string, string> = {
  driving: "#a78bfa", walking: "#34d399", cycling: "#fb923c", default: "#818cf8",
};
const modeColour = (mode?: string) =>
  MODE_COLOURS[(mode ?? "").toLowerCase()] ?? MODE_COLOURS.default;

const modeEmoji = (mode?: string) => {
  const m = (mode ?? "").toLowerCase();
  if (m.includes("walk")) return "🚶";
  if (m.includes("cycl") || m.includes("bike")) return "🚲";
  if (m.includes("train")) return "🚂";
  if (m.includes("flight") || m.includes("air")) return "✈️";
  return "🚗";
};

const makeMarkerSvg = (label: string, colour: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="44" viewBox="0 0 36 44">
    <ellipse cx="18" cy="41" rx="7" ry="3" fill="rgba(0,0,0,0.25)"/>
    <path d="M18 2C9.2 2 2 9.2 2 18C2 28 18 42 18 42C18 42 34 28 34 18C34 9.2 26.8 2 18 2Z"
      fill="${colour}" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"/>
    <text x="18" y="22" text-anchor="middle" dominant-baseline="middle"
      font-family="system-ui,sans-serif" font-size="11" font-weight="700"
      fill="white">${label}</text>
  </svg>`;

// ── Inject Leaflet CSS once into <head> via DOM (App Router safe) ─────────────
function ensureLeafletCSS() {
  const id = "leaflet-css";
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id   = id;
  link.rel  = "stylesheet";
  link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
  link.integrity = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=";
  link.crossOrigin = "";
  document.head.appendChild(link);
}

type PolylineLayer = import("leaflet").Polyline;

// ══════════════════════════════════════════════════════════════════════════════
export default function TripMap({
  mapsData,
  itineraryDays = [],
  origin,
  destination,
  apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010",
}: TripMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef          = useRef<import("leaflet").Map | null>(null);
  const layersRef       = useRef<Record<string, PolylineLayer>>({});

  const [activeMode, setActiveMode] = useState("primary");
  const [isLoading,  setIsLoading]  = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [mapData, setMapData] = useState<{
    originCoord?: Coord;
    destCoord?: Coord;
    primaryPolyline: Coord[];
    altPolylines: Record<string, Coord[]>;
    altMeta: Record<string, { distance?: string; duration?: string }>;
    primaryMeta: { distance?: string; duration?: string; transport_mode?: string };
  } | null>(null);

  // Resolve origin/destination from every possible field the backend might send
  const resolvedOrigin = (origin || mapsData?.origin || mapsData?.origin_city || "").trim();
  const resolvedDest   = (destination || mapsData?.destination || mapsData?.destination_city || "").trim();

  // ── Step 1: fetch map data ────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);

      if (!resolvedOrigin || !resolvedDest) {
        setError(`Origin/destination missing — got "${resolvedOrigin}" → "${resolvedDest}"`);
        setIsLoading(false);
        return;
      }

      try {
        // Use pre-built polyline from backend if present
        if (mapsData?.polyline && mapsData.polyline.length > 2) {
          if (!cancelled) {
            setMapData({
              originCoord:     mapsData.origin_coords,
              destCoord:       mapsData.destination_coords,
              primaryPolyline: mapsData.polyline,
              altPolylines:    {},
              altMeta:         {},
              primaryMeta:     mapsData.primary_route ?? {},
            });
          }
          return;
        }

        const body = {
          origin:         resolvedOrigin,
          destination:    resolvedDest,
          transport_mode: mapsData?.recommended_mode
                            ?? mapsData?.primary_route?.transport_mode
                            ?? "driving",
        };

        const res  = await fetch(`${apiBaseUrl}/api/v1/map/data`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify(body),
        });
        const json = await res.json();

        if (!res.ok || !json.success) {
          throw new Error(json.error ?? `Map API returned ${res.status}`);
        }

        const altPolylines: Record<string, Coord[]> = {};
        const altMeta: Record<string, { distance?: string; duration?: string }> = {};
        for (const [mode, poly] of Object.entries(json.alternative_routes ?? {})) {
          const p = poly as RoutePolyline;
          altPolylines[mode] = p.coordinates ?? [];
          altMeta[mode]      = { distance: p.distance, duration: p.duration };
        }

        if (!cancelled) {
          setMapData({
            originCoord:     json.origin_coords,
            destCoord:       json.destination_coords,
            primaryPolyline: json.primary_route?.coordinates ?? [],
            altPolylines,
            altMeta,
            primaryMeta: {
              distance:       json.primary_route?.distance,
              duration:       json.primary_route?.duration,
              transport_mode: json.primary_route?.transport_mode,
            },
          });
        }
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Map load failed");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedOrigin, resolvedDest]);

  // ── Step 2: init Leaflet once mapData is ready ────────────────────────────
  useEffect(() => {
    if (!mapData || !mapContainerRef.current) return;
    let isMounted = true;

    async function initMap() {
      // FIX: inject CSS via DOM instead of <Head> (App Router compatible)
      ensureLeafletCSS();

      // Small delay so the CSS link can be parsed before Leaflet renders
      await new Promise(r => setTimeout(r, 80));

      const L = (await import("leaflet")).default;

      // Fix broken default icon paths under webpack/Next.js
      // @ts-expect-error private internals
      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconUrl:       "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        shadowUrl:     "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      if (!isMounted || !mapContainerRef.current) return;

      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
        layersRef.current = {};
      }

      const map = L.map(mapContainerRef.current, {
        zoomControl: true,
        scrollWheelZoom: true,
        attributionControl: false,
      });

      L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        { maxZoom: 19 }
      ).addTo(map);

      L.control.attribution({ prefix: false, position: "bottomright" })
        .addAttribution('&copy; <a href="https://carto.com">CARTO</a>')
        .addTo(map);

      const bounds: [number, number][] = [];

      const addMarker = (coord: Coord, label: string, colour: string, popup: string) => {
        const icon = L.divIcon({
          html: makeMarkerSvg(label, colour),
          className: "",
          iconSize:    [36, 44],
          iconAnchor:  [18, 42],
          popupAnchor: [0, -40],
        });
        L.marker([coord.lat, coord.lng], { icon }).addTo(map).bindPopup(popup);
        bounds.push([coord.lat, coord.lng]);
      };

      // Primary polyline
      if (mapData.primaryPolyline.length > 1) {
        const latlngs = mapData.primaryPolyline.map(c => [c.lat, c.lng] as [number, number]);
        const pl = L.polyline(latlngs, {
          color: modeColour(mapData.primaryMeta.transport_mode),
          weight: 5, opacity: 0.9, lineCap: "round", lineJoin: "round",
        }).addTo(map);
        layersRef.current["primary"] = pl;
        bounds.push(...latlngs);
      }

      // Alternative polylines (dimmed)
      for (const [mode, coords] of Object.entries(mapData.altPolylines)) {
        if (coords.length < 2) continue;
        const latlngs = coords.map(c => [c.lat, c.lng] as [number, number]);
        const pl = L.polyline(latlngs, {
          color: modeColour(mode), weight: 3, opacity: 0.3,
          dashArray: "8 6", lineCap: "round",
        }).addTo(map);
        layersRef.current[mode] = pl;
      }

      // Markers
      if (mapData.originCoord)
        addMarker(mapData.originCoord, "A", "#f59e0b",
          `<b>${mapData.originCoord.label ?? resolvedOrigin}</b><br/>Start`);

      if (mapData.destCoord)
        addMarker(mapData.destCoord, "B", "#ef4444",
          `<b>${mapData.destCoord.label ?? resolvedDest}</b><br/>End`);

      // Day stop markers (best-effort geocode)
      const dayPlaces = itineraryDays
        .map(day => {
          const place = day.activities.find(a => a.length < 60 && !/[.?!]$/.test(a));
          return place ? { day: day.day, text: place } : null;
        })
        .filter(Boolean) as { day: number; text: string }[];

      await Promise.allSettled(
        dayPlaces.slice(0, 6).map(async ({ day, text }) => {
          try {
            const r = await fetch(`${apiBaseUrl}/api/v1/map/geocode/${encodeURIComponent(text)}`);
            if (!r.ok) return;
            const geo = await r.json();
            if (!geo.success || !isMounted) return;
            const icon = L.divIcon({
              html: makeMarkerSvg(String(day), "#7c3aed"),
              className: "",
              iconSize: [36, 44], iconAnchor: [18, 42], popupAnchor: [0, -40],
            });
            L.marker([geo.lat, geo.lng], { icon })
              .addTo(map)
              .bindPopup(`<b>Day ${day}</b><br/>${geo.name ?? text}`);
          } catch { /* best-effort */ }
        })
      );

      // Fit bounds
      if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [48, 48], maxZoom: 13 });
      } else if (bounds.length === 1) {
        map.setView(bounds[0], 10);
      } else {
        map.setView([20, 77], 5); // fallback: India
      }

      mapRef.current = map;
    }

    initMap();
    return () => { isMounted = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapData]);

  // ── Step 3: toggle polyline styles on mode change ─────────────────────────
  useEffect(() => {
    for (const [mode, layer] of Object.entries(layersRef.current)) {
      const active = mode === activeMode;
      layer.setStyle({
        weight:    active ? 5 : 3,
        opacity:   active ? 0.9 : 0.25,
        dashArray: active ? "" : "8 6",
      });
      if (active) layer.bringToFront();
    }
  }, [activeMode]);

  // ── Cleanup on unmount ────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
      layersRef.current = {};
    };
  }, []);

  // ── Derived display values ────────────────────────────────────────────────
  const primaryMode = mapsData?.primary_route?.transport_mode ?? mapsData?.recommended_mode ?? "driving";
  const altModes    = Object.keys(mapsData?.alternative_routes ?? {});
  const allModes    = ["primary", ...altModes];
  const activeMeta  = activeMode === "primary"
    ? mapData?.primaryMeta
    : { ...(mapData?.altMeta?.[activeMode] ?? {}), transport_mode: activeMode };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="mb-6"
    >
      {/*
        FIX: removed overflow-hidden from the outer wrapper — it was clipping
        the Leaflet tile layer and making the map appear blank.
        Border-radius is applied only to header/footer, not the map canvas.
      */}
      <div className="bg-zinc-950 border border-violet-500/20 shadow-2xl rounded-3xl">

        {/* Header */}
        <div className="px-6 py-5 bg-gradient-to-r from-violet-900/40 to-fuchsia-900/40 border-b border-violet-500/20 rounded-t-3xl">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-violet-500/20 rounded-xl">
                <span className="text-2xl">🗺️</span>
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Route Map</h3>
                {(resolvedOrigin || resolvedDest) && (
                  <p className="text-sm text-violet-300">{resolvedOrigin} → {resolvedDest}</p>
                )}
              </div>
            </div>

            {/* Mode pills */}
            <div className="flex gap-2 flex-wrap">
              {allModes.map(mode => {
                const active = activeMode === mode;
                const colour = mode === "primary" ? modeColour(primaryMode) : modeColour(mode);
                const label  = mode === "primary" ? primaryMode : mode;
                return (
                  <button key={mode} onClick={() => setActiveMode(mode)}
                    style={{ borderColor: active ? colour : "transparent", color: active ? colour : "#a1a1aa" }}
                    className="px-3 py-1.5 rounded-full text-xs font-semibold border-2 transition-all bg-black/30 hover:bg-black/50">
                    {modeEmoji(label)} {label}
                    {mode === "primary" && (
                      <span className="ml-1.5 text-[10px] bg-violet-500/30 text-violet-200 px-1.5 py-0.5 rounded-full">
                        best
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {mapsData?.route_analysis && (
            <p className="mt-3 text-sm text-zinc-300 bg-black/20 rounded-xl px-4 py-3 border border-violet-500/10 leading-relaxed">
              {mapsData.route_analysis}
            </p>
          )}
        </div>

        {/* Map canvas — position:relative so the overlay can sit on top */}
        <div style={{ position: "relative", height: "420px" }}>

          {/* Loading / error overlays */}
          <AnimatePresence>
            {isLoading && (
              <motion.div key="loader"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                style={{ position: "absolute", inset: 0, zIndex: 1000 }}
                className="flex flex-col items-center justify-center bg-zinc-950/90 gap-4">
                <motion.div animate={{ rotate: 360 }}
                  transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }}
                  className="w-10 h-10 border-4 border-violet-800 border-t-violet-400 rounded-full" />
                <p className="text-sm text-violet-300">Loading map…</p>
              </motion.div>
            )}
            {error && !isLoading && (
              <motion.div key="error"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                style={{ position: "absolute", inset: 0, zIndex: 1000 }}
                className="flex flex-col items-center justify-center bg-zinc-950/90 gap-3 px-8 text-center">
                <span className="text-3xl">🗺️</span>
                <p className="text-zinc-400 text-sm">{error}</p>
                <p className="text-zinc-600 text-xs">Route info is shown in the card above.</p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Leaflet mounts here — explicit px height is required */}
          <div ref={mapContainerRef} style={{ width: "100%", height: "420px" }} />
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-zinc-900/60 border-t border-violet-500/10 rounded-b-3xl">
          <div className="flex flex-wrap items-center gap-6">
            {activeMeta?.distance && (
              <div className="flex items-center gap-2">
                <span className="text-violet-400 text-sm">📍</span>
                <span className="text-white font-semibold text-sm">{activeMeta.distance}</span>
                <span className="text-zinc-500 text-xs">distance</span>
              </div>
            )}
            {activeMeta?.duration && (
              <div className="flex items-center gap-2">
                <span className="text-violet-400 text-sm">⏱️</span>
                <span className="text-white font-semibold text-sm">{activeMeta.duration}</span>
                <span className="text-zinc-500 text-xs">travel time</span>
              </div>
            )}
            <div className="ml-auto flex items-center gap-4 text-xs text-zinc-600">
              <span className="flex items-center gap-1">
                <span className="inline-block w-3 h-3 rounded-full bg-amber-400" /> Origin
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-3 h-3 rounded-full bg-red-500" /> Destination
              </span>
              {itineraryDays.length > 0 && (
                <span className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-full bg-violet-500" /> Day stops
                </span>
              )}
            </div>
          </div>
        </div>

      </div>
    </motion.div>
  );
}