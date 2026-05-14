"use client";
import { useState, useEffect, useCallback, memo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Hyperspeed from "@/components/Hyperspeed/Hyperspeed";

// ─── Memoised backgrounds ────────────────────────────────────────────────────
const HyperspeedBackground = memo(function HyperspeedBackground() {
  return (
    <div className="absolute scale-60 -left-75 -top-50 bottom-0 right-0 h-full w-full pointer-events-none">
      <Hyperspeed
        effectOptions={{
          colors: {
            roadColor: 0x080808,
            islandColor: 0x0a0a0a,
            background: 0x000000,
            shoulderLines: 0x131318,
            brokenLines: 0x131318,
            leftCars: [0x7d0d1b, 0xa90519, 0xff102a],
            rightCars: [0xf1eece, 0xe6e2b1, 0xdfd98a],
            sticks: 0xf1eece,
          },
        }}
      />
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

// ─── Constants ───────────────────────────────────────────────────────────────
const placeholderTexts = [
  "Plan your dream vacation to Paris...",
  "Discover hidden gems in Tokyo...",
  "Create an adventure in Iceland...",
  "Explore the streets of New York...",
  "Find paradise in Bali...",
  "Journey through the Swiss Alps...",
  "Experience the magic of Rome...",
  "Uncover treasures in Morocco...",
];

const titles = [
  "Where planning is Spontaneous",
  "Less Google, More Goggles",
  "Plan less, Chill more",
];

// ─── Types ────────────────────────────────────────────────────────────────────
interface DayWeather {
  description?: string;
  temperature_max?: number;
}

interface ItineraryDay {
  day: number;
  date: string;
  activities: string[];
  notes?: string;
  estimated_cost?: number;
}

interface Budget {
  total: number;
  transportation: number;
  accommodation: number;
  food: number;
  activities: number;
  currency?: string;
}

interface PlanData {
  itinerary: ItineraryDay[];
  budget: Budget;
  weather: DayWeather[];
  processing_time_ms: number;
}

// ─── Pure helpers — OUTSIDE the component so they aren't recreated on renders ─

function expandTravelDates(rawDates: string[]): string[] {
  const expanded: string[] = [];
  for (const d of rawDates) {
    const rangeMatch = d.match(
      /(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})/
    );
    if (rangeMatch) {
      const start = new Date(rangeMatch[1]);
      const end = new Date(rangeMatch[2]);
      const cur = new Date(start);
      while (cur <= end) {
        expanded.push(cur.toISOString().split("T")[0]);
        cur.setDate(cur.getDate() + 1);
      }
    } else {
      expanded.push(d);
    }
  }
  return expanded.length > 0 ? expanded : rawDates;
}

function reconstructItineraryDays(
  existingDays: ItineraryDay[],
  dates: string[],
  budget: Budget
): ItineraryDay[] {
  if (existingDays.length === dates.length) return existingDays;
  const dailyCost = dates.length > 0 ? Math.round(budget.total / dates.length) : 0;
  return dates.map((date, i) => {
    const existing = existingDays[i];
    if (existing) return { ...existing, date, estimated_cost: dailyCost };
    return {
      day: i + 1,
      date,
      activities: [`Day ${i + 1} — refresh to regenerate`],
      notes: "",
      estimated_cost: dailyCost,
    };
  });
}

// ─── TypewriterPrompt ─────────────────────────────────────────────────────────
const TypewriterPrompt = ({
  onSubmit,
  disabled = false,
}: {
  onSubmit: (q: string) => void;
  disabled?: boolean;
}) => {
  const [displayText, setDisplayText] = useState("");
  const [currentPhraseIndex, setCurrentPhraseIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [userInput, setUserInput] = useState("");

  useEffect(() => {
    const currentPhrase = placeholderTexts[currentPhraseIndex];
    const typingSpeed = isDeleting ? 30 : 80;
    const timer = setTimeout(() => {
      if (!isDeleting && displayText === currentPhrase) {
        setTimeout(() => setIsDeleting(true), 2000);
      } else if (isDeleting && displayText === "") {
        setIsDeleting(false);
        setCurrentPhraseIndex((p) => (p + 1) % placeholderTexts.length);
      } else {
        setDisplayText(
          isDeleting
            ? currentPhrase.substring(0, displayText.length - 1)
            : currentPhrase.substring(0, displayText.length + 1)
        );
      }
    }, typingSpeed);
    return () => clearTimeout(timer);
  }, [displayText, isDeleting, currentPhraseIndex]);

  const handleSubmit = () => {
    if (userInput.trim() && !disabled) {
      onSubmit(userInput.trim());
      setUserInput("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleQuickAction = (tag: string) => {
    setUserInput((prev) => (prev ? `${prev} ${tag}` : tag));
  };

  return (
    <motion.div
      className="relative w-full max-w-3xl"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
    >
      <div className="relative">
        <textarea
          value={userInput}
          onChange={(e) => setUserInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          className="w-full min-h-[120px] bg-black/40 backdrop-blur-md border border-zinc-600/50 rounded-2xl p-5 pr-14 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 resize-none transition-all duration-300 shadow-2xl disabled:opacity-50"
          placeholder={displayText}
        />
        <button
          onClick={handleSubmit}
          disabled={!userInput.trim() || disabled}
          className="absolute bottom-4 right-4 bg-gradient-to-r from-red-700 to-red-900 hover:from-red-600 hover:to-red-700 text-white p-3 rounded-xl transition-all duration-300 shadow-lg hover:shadow-red-500/50 group disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-5 w-5 group-hover:translate-x-0.5 transition-transform"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
          </svg>
        </button>
      </div>

      <div className="mt-4 flex gap-3 flex-wrap justify-center">
        {["Weekend Getaway", "Family Trip", "Solo Adventure", "Budget Travel"].map(
          (tag) => (
            <button
              key={tag}
              onClick={() => handleQuickAction(tag)}
              className="px-4 py-2 bg-zinc-800/50 backdrop-blur-sm border border-zinc-700/50 rounded-full text-sm text-zinc-300 hover:bg-zinc-700/50 hover:border-amber-400 transition-all duration-300"
            >
              {tag}
            </button>
          )
        )}
      </div>

      <div className="mt-8 flex gap-6 text-sm text-zinc-400 mb-8 justify-center">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-red-900 rounded-full animate-pulse" />
          <span>Instant Planning</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-zinc-800 rounded-full animate-pulse" />
          <span>Smart Recommendations</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-yellow-800 rounded-full animate-pulse" />
          <span>Budget Friendly</span>
        </div>
      </div>
    </motion.div>
  );
};

// ─── LoadingState ─────────────────────────────────────────────────────────────
const LoadingState = () => {
  const stages = [
    { text: "Ringmaster is thinking", icon: "🎪" },
    { text: "Analysing your preferences", icon: "🔍" },
    { text: "Checking weather conditions", icon: "🌤️" },
    { text: "Finding the best routes", icon: "🗺️" },
    { text: "Calculating your budget", icon: "💰" },
    { text: "Crafting your perfect itinerary", icon: "✨" },
  ];
  const [currentStage, setCurrentStage] = useState(0);

  useEffect(() => {
    const interval = setInterval(
      () => setCurrentStage((p) => (p + 1) % stages.length),
      2000
    );
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col items-center justify-center space-y-8">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
      >
        <div className="w-20 h-20 border-4 border-red-900/30 border-t-red-500 rounded-full" />
      </motion.div>

      <AnimatePresence mode="wait">
        <motion.div
          key={currentStage}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="text-center"
        >
          <div className="text-4xl mb-3">{stages[currentStage].icon}</div>
          <div className="text-xl text-zinc-300 font-light">
            {stages[currentStage].text}
          </div>
        </motion.div>
      </AnimatePresence>

      <div className="flex gap-2">
        {stages.map((_, i) => (
          <motion.div
            key={i}
            className={`h-1.5 rounded-full transition-all duration-300 ${
              i === currentStage ? "w-8 bg-red-500" : "w-1.5 bg-zinc-700"
            }`}
          />
        ))}
      </div>
    </div>
  );
};

// ─── ItineraryView ────────────────────────────────────────────────────────────
const ItineraryView = ({
  data,
  userQuery,
}: {
  data: PlanData;
  userQuery: string;
}) => {
  const currency = data.budget?.currency || "INR";

  const formatCurrency = (amount: number) =>
    new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount || 0);

  const getWeatherIcon = (description?: string) => {
    if (!description) return "🌤️";
    if (description.includes("rain")) return "🌧️";
    if (description.includes("cloud")) return "☁️";
    if (description.includes("sun")) return "☀️";
    return "🌤️";
  };

  const budget: Budget = {
    total: 0,
    transportation: 0,
    accommodation: 0,
    food: 0,
    activities: 0,
    currency: "INR",
    ...(data.budget || {}),
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="w-full max-w-6xl mx-auto px-4 pb-20"
    >
      {/* User query bubble */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8 p-6 bg-zinc-900/50 backdrop-blur-md border border-zinc-800 rounded-2xl"
      >
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-400 to-red-500 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">
            You
          </div>
          <p className="text-zinc-300 text-lg">{userQuery}</p>
        </div>
      </motion.div>

      {/* AI header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="mb-8 flex items-center gap-3"
      >
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-red-700 to-red-900 flex items-center justify-center">
          <span className="text-xl">🎪</span>
        </div>
        <div>
          <h2 className="text-2xl font-light text-zinc-100">Ringmaster</h2>
          <p className="text-sm text-zinc-500">Your AI Travel Planner</p>
        </div>
      </motion.div>

      {/* Budget overview */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mb-8 p-6 bg-gradient-to-br from-red-900/20 to-amber-900/20 backdrop-blur-md border border-red-800/30 rounded-2xl"
      >
        <h3 className="text-xl font-light text-zinc-100 mb-4 flex items-center gap-2">
          <span>💰</span> Budget Breakdown
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { label: "Total", value: budget.total, highlight: true },
            { label: "Transport", value: budget.transportation },
            { label: "Stay", value: budget.accommodation },
            { label: "Food", value: budget.food },
            { label: "Activities", value: budget.activities },
          ].map(({ label, value, highlight }) => (
            <div key={label} className="text-center">
              <div
                className={`font-bold ${
                  highlight ? "text-2xl text-amber-400" : "text-lg text-zinc-300"
                }`}
              >
                {formatCurrency(value)}
              </div>
              <div className="text-sm text-zinc-400">{label}</div>
            </div>
          ))}
        </div>
      </motion.div>

      {/* Itinerary days */}
      {data.itinerary && data.itinerary.length > 0 ? (
        data.itinerary.map((day, index) => (
          <motion.div
            key={day.day}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 + index * 0.1 }}
            className="mb-6 p-6 bg-black/40 backdrop-blur-md border border-zinc-800/50 rounded-2xl hover:border-zinc-700/50 transition-all"
          >
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-2xl font-light text-zinc-100 mb-1">
                  Day {day.day}
                </h3>
                <p className="text-zinc-400">{day.date}</p>
              </div>
              <div className="text-right">
                {day.estimated_cost != null && (
                  <div className="text-lg text-amber-400 font-semibold">
                    {formatCurrency(day.estimated_cost)}
                  </div>
                )}
                {data.weather && data.weather[index] && (
                  <div className="text-sm text-zinc-400 flex items-center gap-2 mt-1 justify-end">
                    <span>{getWeatherIcon(data.weather[index].description)}</span>
                    {data.weather[index].temperature_max != null && (
                      <span>
                        {Math.round(data.weather[index].temperature_max!)}°C
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {day.notes && (
              <div className="mb-4 p-3 bg-amber-900/10 border border-amber-800/30 rounded-lg">
                <p className="text-sm text-amber-200/80 flex items-start gap-2">
                  <span className="text-amber-500">⚠️</span>
                  {day.notes}
                </p>
              </div>
            )}

            <div className="space-y-3">
              {day.activities.map((activity, actIndex) => (
                <motion.div
                  key={actIndex}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.4 + index * 0.1 + actIndex * 0.05 }}
                  className="flex gap-3 items-start group"
                >
                  <div className="w-2 h-2 mt-2 rounded-full bg-red-800 group-hover:bg-red-500 transition-colors flex-shrink-0" />
                  <p className="text-zinc-300 group-hover:text-zinc-100 transition-colors">
                    {activity}
                  </p>
                </motion.div>
              ))}
            </div>
          </motion.div>
        ))
      ) : (
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
  const [currentTitleIndex, setCurrentTitleIndex] = useState(0);
  const [isPlanning, setIsPlanning] = useState(false);
  const [planData, setPlanData] = useState<PlanData | null>(null);
  const [userQuery, setUserQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    const interval = setInterval(
      () => setCurrentTitleIndex((p) => (p + 1) % titles.length),
      4000
    );
    return () => clearInterval(interval);
  }, []);

  const handlePlanSubmit = useCallback(async (query: string) => {
    setUserQuery(query);
    setIsPlanning(true);
    setError(null);
    setPlanData(null);

    try {
      const startRes = await fetch(`${API_URL}/api/v2/orchestrator/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, session_id: null }),
      });

      if (!startRes.ok) {
        const errBody = await startRes.json().catch(() => ({}));
        throw new Error(errBody.detail || "Failed to start plan");
      }

      const { session_id } = await startRes.json();
      if (!session_id) throw new Error("No session ID returned from server");

      const MAX_ATTEMPTS = 40;
      let attempts = 0;

      while (attempts < MAX_ATTEMPTS) {
        attempts++;
        await new Promise((r) => setTimeout(r, 3000));

        const resultRes = await fetch(
          `${API_URL}/api/v2/orchestrator/session/${session_id}/result`
        );

        if (resultRes.status === 400) continue;

        if (!resultRes.ok) {
          const errBody = await resultRes.json().catch(() => ({}));
          throw new Error(errBody.detail || "Failed to fetch result");
        }

        const result = await resultRes.json();
        if (result.status !== "completed") continue;

        console.log("RAW RESULT:", JSON.stringify(result, null, 2));

        // Fix 1: expand date range strings → individual dates
        const expandedDates = expandTravelDates(result.travel_dates || []);

        // Fix 2: itinerary days from result.itinerary.itinerary_days
        const itineraryDays: ItineraryDay[] =
          result.itinerary?.itinerary_days || [];

        // Fix 3: result.weather is already a flat list
        let weatherForecast: DayWeather[] = [];
        if (Array.isArray(result.weather)) {
          weatherForecast = result.weather;
        } else if (result.weather?.weather_forecast) {
          weatherForecast = result.weather.weather_forecast;
        }

        // Fix 4: result.budget is already the breakdown object
        let budgetBreakdown: Budget = {
          total: 0,
          transportation: 0,
          accommodation: 0,
          food: 0,
          activities: 0,
          currency: "INR",
        };
        if (result.budget) {
          if (typeof result.budget.total === "number") {
            budgetBreakdown = result.budget;
          } else if (result.budget.budget_breakdown) {
            budgetBreakdown = result.budget.budget_breakdown;
          }
        }

        // Safety net: reconstruct days if count doesn't match
        const finalItineraryDays =
          itineraryDays.length >= expandedDates.length && itineraryDays.length > 0
            ? itineraryDays
            : reconstructItineraryDays(itineraryDays, expandedDates, budgetBreakdown);

        setPlanData({
          itinerary: finalItineraryDays,
          budget: budgetBreakdown,
          weather: weatherForecast,
          processing_time_ms: 0,
        });

        setIsPlanning(false);
        return;
      }

      throw new Error("Timed out — please try again");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      console.error("Plan error:", message);
      setError(message);
      setIsPlanning(false);
    }
  }, [API_URL]);

  const handleNewPlan = () => {
    setPlanData(null);
    setIsPlanning(false);
    setUserQuery("");
    setError(null);
  };

  return (
    <div className="h-screen w-screen overflow-hidden bg-black relative">
      <LightRaysBackground />
      <HyperspeedBackground />
      <div className="bg-black/60 inset-0 absolute" />

      <div className="relative z-10 h-full w-full">
        <AnimatePresence mode="wait">
          {!isPlanning && !planData && (
            <motion.div
              key="landing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="h-full flex flex-col items-center justify-between px-4 py-4"
            >
              <div className="mt-40 mb-12 text-center">
                <AnimatePresence mode="wait">
                  <motion.h1
                    key={currentTitleIndex}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -20 }}
                    transition={{ duration: 0.5 }}
                    className="text-5xl font-light bg-gradient-to-r from-white via-zinc-300 to-zinc-700 bg-clip-text text-transparent mb-4"
                  >
                    {titles[currentTitleIndex]}
                  </motion.h1>
                </AnimatePresence>
                <motion.p
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.2 }}
                  className="text-zinc-400 text-lg"
                >
                  Describe your dream trip and let AI craft the perfect itinerary
                </motion.p>
              </div>
              <TypewriterPrompt onSubmit={handlePlanSubmit} />
            </motion.div>
          )}

          {isPlanning && !planData && (
            <motion.div
              key="loading"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="h-full flex items-center justify-center"
            >
              <LoadingState />
            </motion.div>
          )}

          {planData && (
            <motion.div
              key="results"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="h-full overflow-y-auto"
            >
              <div className="sticky top-0 z-20 backdrop-blur-xl bg-black/80 border-b border-zinc-800 px-4 py-4">
                <div className="max-w-6xl mx-auto flex justify-between items-center">
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleNewPlan}
                    className="px-4 py-2 bg-zinc-800/50 hover:bg-zinc-700/50 border border-zinc-700 rounded-lg text-zinc-300 transition-all"
                  >
                    ← New Plan
                  </motion.button>
                  <div className="text-zinc-400 text-sm">
                    {planData.itinerary.length} day
                    {planData.itinerary.length !== 1 ? "s" : ""} planned
                  </div>
                </div>
              </div>
              <div className="pt-8">
                <ItineraryView data={planData} userQuery={userQuery} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: 50 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 50 }}
              className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 w-full max-w-md px-4"
            >
              <div className="bg-red-900/90 backdrop-blur-md border border-red-700 rounded-xl p-4 flex items-center gap-3 shadow-2xl">
                <span className="text-red-200 text-xl">❌</span>
                <p className="text-red-100 flex-1 text-sm">{error}</p>
                <button
                  onClick={() => setError(null)}
                  className="text-red-300 hover:text-white transition-colors ml-2 text-lg leading-none"
                >
                  ✕
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default Page;