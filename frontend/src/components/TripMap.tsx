"use client";
/**
 * TripMap.tsx — Fixed Leaflet map for Ringmaster Round Table
 *
 * Fixes applied:
 *  1. Leaflet CSS imported via next/head (required for map to render correctly)
 *  2. Map init no longer re-runs on activeMode change — polyline layers are
 *     stored in a ref and toggled in place instead of rebuilding the map.
 *  3. apiBaseUrl defaults match the WS port (8010) used in TravelChatPage.
 *  4. Cleanup on unmount is guarded with isMounted flag.
 */

import { useEffect, useRef, useState } from "react";
import Head from "next/head";
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
  /** Should match the port your FastAPI app runs on */
  apiBaseUrl?: string;
}

// ── Colour helpers ────────────────────────────────────────────────────────────
const MODE_COLOURS: Record<string, string> = {
  driving: "#a78bfa",
  walking: "#34d399",
  cycling: "#fb923c",
  default: "#818cf8",
};
function modeColour(mode?: string) {
  return MODE_COLOURS[(mode ?? "").toLowerCase()] ?? MODE_COLOURS.default;
}
function modeEmoji(mode?: string) {
  const m = (mode ?? "").toLowerCase();
  if (m.includes("walk"))  return "🚶";
  if (m.includes("cycl") || m.includes("bike")) return "🚲";
  if (m.includes("train")) return "🚂";
  if (m.includes("flight") || m.includes("air")) return "✈️";
  return "🚗";
}

// ── SVG marker (no external image dependency) ─────────────────────────────────
function makeMarkerSvg(label: string, colour: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="44" viewBox="0 0 36 44">
    <ellipse cx="18" cy="41" rx="7" ry="3" fill="rgba(0,0,0,0.25)"/>
    <path d="M18 2C9.2 2 2 9.2 2 18C2 28 18 42 18 42C18 42 34 28 34 18C34 9.2 26.8 2 18 2Z"
      fill="${colour}" stroke="rgba(255,255,255,0.6)" stroke-width="1.5"/>
    <text x="18" y="22" text-anchor="middle" dominant-baseline="middle"
      font-family="system-ui,sans-serif" font-size="11" font-weight="700" fill="white">${label}</text>
  </svg>`;
}

// ── Stored layer refs (keyed by mode) ──────────────────────────────────────────
type PolylineLayer = import("leaflet").Polyline;
type LayerMap = Record<string, PolylineLayer>;

// ══════════════════════════════════════════════════════════════════════════════
export default function TripMap({
  mapsData,
  itineraryDays = [],
  origin,
  destination,
  // FIX 3: default port matches TravelChatPage WebSocket (8010)
  apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010",
}: TripMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef          = useRef<import("leaflet").Map | null>(null);
  // FIX 2: store polyline layers so we can toggle them without rebuilding the map
  const layersRef       = useRef<LayerMap>({});

  const [activeMode,  setActiveMode]  = useState<string>("primary");
  const [isLoading,   setIsLoading]   = useState(true);
  const [error,       setError]       = useState<string | null>(null);
  const [mapData, setMapData] = useState<{
    originCoord?: Coord;
    destCoord?: Coord;
    primaryPolyline: Coord[];
    altPolylines: Record<string, Coord[]>;
    altMeta: Record<string, { distance?: string; duration?: string }>;
    primaryMeta: { distance?: string; duration?: string; transport_mode?: string };
  } | null>(null);

  // ── Step 1: Fetch / derive map data (runs once on mount) ─────────────────
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);

      try {
        const fromName = origin ?? mapsData.origin ?? "";
        const toName   = destination ?? mapsData.destination ?? "";

        if (!fromName || !toName) {
          setError("Origin or destination missing");
          setIsLoading(false);
          return;
        }

        // If the backend already shipped a polyline, use it directly
        if (mapsData.polyline && mapsData.polyline.length > 2) {
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

        // Otherwise call the dedicated map endpoint
        const res = await fetch(`${apiBaseUrl}/api/v1/map/data`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            origin:         fromName,
            destination:    toName,
            transport_mode: mapsData.recommended_mode
                              ?? mapsData.primary_route?.transport_mode
                              ?? "driving",
          }),
        });

        if (!res.ok) throw new Error(`Map API ${res.status}: ${res.statusText}`);
        const json = await res.json();
        if (!json.success) throw new Error(json.error ?? "Map data failed");

        const altPolylines: Record<string, Coord[]> = {};
        const altMeta: Record<string, { distance?: string; duration?: string }> = {};
        for (const [mode, poly] of Object.entries(json.alternative_routes ?? {})) {
          const p = poly as RoutePolyline;
          altPolylines[mode] = p.coordinates ?? [];
          altMeta[mode] = { distance: p.distance, duration: p.duration };
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
  }, []); // intentionally empty — re-run only if parent remounts

  // ── Step 2: Initialise Leaflet map (runs once when mapData is ready) ──────
  // FIX 2: activeMode is NOT in the dep array — toggling mode no longer
  //         rebuilds the map.  We draw ALL polylines once, then show/hide them.
  useEffect(() => {
    if (!mapData || !mapContainerRef.current) return;
    let isMounted = true;

    async function initMap() {
      // FIX 1: import leaflet CSS dynamically so Next.js doesn't SSR it
      await import("leaflet/dist/leaflet.css");
      const L = (await import("leaflet")).default;

      // Fix Leaflet's broken default icon URLs under webpack
      // @ts-expect-error private internals
      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconUrl:       "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        shadowUrl:     "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      if (!isMounted || !mapContainerRef.current) return;

      // Destroy any previous instance (e.g. React StrictMode double-mount)
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

      // ── Helper to add a divIcon marker ────────────────────────────────────
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

      // ── Primary polyline (stored under "primary" key) ─────────────────────
      if (mapData.primaryPolyline.length > 1) {
        const latlngs = mapData.primaryPolyline.map(c => [c.lat, c.lng] as [number, number]);
        const pl = L.polyline(latlngs, {
          color:   modeColour(mapData.primaryMeta.transport_mode),
          weight:  5,
          opacity: 0.9,
          lineCap: "round",
          lineJoin: "round",
        }).addTo(map);
        layersRef.current["primary"] = pl;
        bounds.push(...latlngs);
      }

      // ── Alternative polylines ─────────────────────────────────────────────
      for (const [mode, coords] of Object.entries(mapData.altPolylines)) {
        if (coords.length < 2) continue;
        const latlngs = coords.map(c => [c.lat, c.lng] as [number, number]);
        const pl = L.polyline(latlngs, {
          color:     modeColour(mode),
          weight:    3,
          opacity:   0.3,       // dimmed by default
          dashArray: "8 6",
          lineCap:   "round",
        }).addTo(map);
        layersRef.current[mode] = pl;
      }

      // ── Origin / destination markers ──────────────────────────────────────
      if (mapData.originCoord)
        addMarker(mapData.originCoord, "A", "#f59e0b",
          `<b>${mapData.originCoord.label ?? origin ?? "Origin"}</b><br/>Start`);

      if (mapData.destCoord)
        addMarker(mapData.destCoord, "B", "#ef4444",
          `<b>${mapData.destCoord.label ?? destination ?? "Destination"}</b><br/>End`);

      // ── Itinerary day markers (best-effort geocode) ───────────────────────
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

      // ── Fit bounds ────────────────────────────────────────────────────────
      if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [48, 48], maxZoom: 13 });
      } else if (bounds.length === 1) {
        map.setView(bounds[0], 10);
      } else {
        map.setView([20, 0], 2);
      }

      mapRef.current = map;
    }

    initMap();
    return () => { isMounted = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapData]); // only re-init when data changes, NOT when activeMode changes

  // ── Step 3: Toggle polyline opacity when activeMode changes ───────────────
  // FIX 2 continued: no map re-build, just restyle the existing layers
  useEffect(() => {
    const layers = layersRef.current;
    for (const [mode, layer] of Object.entries(layers)) {
      const isActive = mode === activeMode;
      layer.setStyle({
        weight:  isActive ? 5 : 3,
        opacity: isActive ? 0.9 : 0.25,
        dashArray: isActive ? "" : "8 6",
      });
      if (isActive) layer.bringToFront();
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
  const primaryMode = mapsData.primary_route?.transport_mode
                   ?? mapsData.recommended_mode
                   ?? "driving";
  const altModes = Object.keys(mapsData.alternative_routes ?? {});
  const allModes = ["primary", ...altModes];

  const activeMeta =
    activeMode === "primary"
      ? mapData?.primaryMeta
      : { ...(mapData?.altMeta?.[activeMode] ?? {}), transport_mode: activeMode };

  return (
    <>
      {/* FIX 1: Leaflet CSS loaded via <Head> — critical for correct rendering */}
      <Head>
        <link
          rel="stylesheet"
          href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossOrigin=""
        />
      </Head>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="mb-6"
      >
        <div className="rounded-3xl overflow-hidden bg-zinc-950 border border-violet-500/20 shadow-2xl">

          {/* ── Header ───────────────────────────────────────────────────── */}
          <div className="px-6 py-5 bg-gradient-to-r from-violet-900/40 to-fuchsia-900/40 border-b border-violet-500/20">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-violet-500/20 rounded-xl">
                  <span className="text-2xl">🗺️</span>
                </div>
                <div>
                  <h3 className="text-lg font-bold text-white">Route Map</h3>
                  {mapsData.origin && mapsData.destination && (
                    <p className="text-sm text-violet-300">
                      {mapsData.origin} → {mapsData.destination}
                    </p>
                  )}
                </div>
              </div>

              {/* Mode switcher pills */}
              <div className="flex gap-2 flex-wrap">
                {allModes.map(mode => {
                  const isActive = activeMode === mode;
                  const colour   = mode === "primary" ? modeColour(primaryMode) : modeColour(mode);
                  const label    = mode === "primary" ? primaryMode : mode;
                  return (
                    <button
                      key={mode}
                      onClick={() => setActiveMode(mode)}
                      style={{
                        borderColor: isActive ? colour : "transparent",
                        color: isActive ? colour : "#a1a1aa",
                      }}
                      className="px-3 py-1.5 rounded-full text-xs font-semibold border-2 transition-all bg-black/30 hover:bg-black/50"
                    >
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

            {mapsData.route_analysis && (
              <p className="mt-3 text-sm text-zinc-300 bg-black/20 rounded-xl px-4 py-3 border border-violet-500/10 leading-relaxed">
                {mapsData.route_analysis}
              </p>
            )}
          </div>

          {/* ── Map canvas ───────────────────────────────────────────────── */}
          <div className="relative" style={{ height: "420px" }}>
            <AnimatePresence>
              {isLoading && (
                <motion.div
                  key="loader"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-zinc-950/90 gap-4"
                >
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }}
                    className="w-10 h-10 border-4 border-violet-800 border-t-violet-400 rounded-full"
                  />
                  <p className="text-sm text-violet-300">Loading map…</p>
                </motion.div>
              )}
              {error && !isLoading && (
                <motion.div
                  key="error"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                  className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-zinc-950/90 gap-3 px-8 text-center"
                >
                  <span className="text-3xl">🗺️</span>
                  <p className="text-zinc-400 text-sm">{error}</p>
                  <p className="text-zinc-600 text-xs">Route info is shown in the card above.</p>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Leaflet attaches here */}
            <div ref={mapContainerRef} className="w-full h-full" />
          </div>

          {/* ── Stats footer ─────────────────────────────────────────────── */}
          <div className="px-6 py-4 bg-zinc-900/60 border-t border-violet-500/10">
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
                  <span className="inline-block w-3 h-3 rounded-full bg-amber-400" />Origin
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-full bg-red-500" />Destination
                </span>
                {itineraryDays.length > 0 && (
                  <span className="flex items-center gap-1">
                    <span className="inline-block w-3 h-3 rounded-full bg-violet-500" />Day stops
                  </span>
                )}
              </div>
            </div>
          </div>

        </div>
      </motion.div>
    </>
  );
}