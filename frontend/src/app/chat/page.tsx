"use client";
import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  MapPin,
  Calendar,
  DollarSign,
  Cloud,
  Star,
  TrendingUp,
  Users,
  Clock,
  Thermometer,
  Wind,
  Droplets,
  Car,
  Train,
  Plane,
  Navigation,
  AlertCircle,
  CheckCircle,
  XCircle,
} from "lucide-react";

const HyperspeedBackground = () => {
  return (
    <div className="absolute inset-0 pointer-events-none">
      <div className="w-full h-full bg-gradient-to-br from-violet-950/20 via-purple-900/10 to-fuchsia-950/20" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_50%,rgba(120,0,255,0.1),transparent_50%)]" />
      <div className="absolute inset-0 opacity-30">
        {[...Array(30)].map((_, i) => (
          <motion.div
            key={i}
            className="absolute w-1 h-1 bg-violet-400 rounded-full"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
            }}
            animate={{
              opacity: [0.2, 0.8, 0.2],
              scale: [1, 1.5, 1],
            }}
            transition={{
              duration: 2 + Math.random() * 2,
              repeat: Infinity,
              delay: Math.random() * 2,
            }}
          />
        ))}
      </div>
    </div>
  );
};

const ChatMessage = ({ message, isUser }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 100 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"} mb-6`}
    >
      <div
        className={`max-w-[85%] p-5 rounded-3xl backdrop-blur-xl ${
          isUser
            ? "bg-gradient-to-br from-violet-600 to-fuchsia-600 text-white shadow-lg shadow-violet-500/20"
            : "bg-zinc-900/80 border border-violet-500/20 text-zinc-100 shadow-xl"
        }`}
      >
        <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        {message.timestamp && (
          <p className="text-xs opacity-50 mt-3 flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {new Date(message.timestamp).toLocaleTimeString()}
          </p>
        )}
      </div>
    </motion.div>
  );
};

const StreamingIndicator = ({ message }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-start mb-6"
    >
      <div className="max-w-[85%] p-5 rounded-3xl bg-gradient-to-br from-violet-900/40 to-fuchsia-900/40 border border-violet-500/30 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
            className="w-5 h-5 border-3 border-violet-400/30 border-t-violet-400 rounded-full"
          />
          <p className="text-violet-200 text-sm font-medium">{message}</p>
        </div>
      </div>
    </motion.div>
  );
};

const AgentStatusCard = ({ agent, status }) => {
  const getStatusConfig = (status) => {
    switch (status) {
      case "completed":
        return {
          color: "from-emerald-500/20 to-green-500/20 border-emerald-500/40",
          textColor: "text-emerald-300",
          icon: <CheckCircle className="w-5 h-5" />,
        };
      case "processing":
        return {
          color: "from-amber-500/20 to-yellow-500/20 border-amber-500/40",
          textColor: "text-amber-300",
          icon: <Clock className="w-5 h-5 animate-spin" />,
        };
      case "pending":
        return {
          color: "from-zinc-700/20 to-zinc-600/20 border-zinc-600/40",
          textColor: "text-zinc-400",
          icon: <AlertCircle className="w-5 h-5" />,
        };
      default:
        return {
          color: "from-red-500/20 to-rose-500/20 border-red-500/40",
          textColor: "text-red-300",
          icon: <XCircle className="w-5 h-5" />,
        };
    }
  };

  const agentConfig = {
    weather: { icon: "🌤️", label: "Weather" },
    events: { icon: "🎉", label: "Events" },
    maps: { icon: "🗺️", label: "Routes" },
    budget: { icon: "💰", label: "Budget" },
    itinerary: { icon: "✨", label: "Itinerary" },
    orchestrator: { icon: "🎯", label: "Planner" },
  };

  const config = getStatusConfig(status);
  const agentInfo = agentConfig[agent] || { icon: "🤖", label: agent };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      whileHover={{ scale: 1.05 }}
      transition={{ type: "spring", stiffness: 200 }}
      className={`p-4 rounded-2xl bg-gradient-to-br ${config.color} border backdrop-blur-xl`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{agentInfo.icon}</span>
          <span className={`text-sm font-bold ${config.textColor}`}>
            {agentInfo.label}
          </span>
        </div>
        <span className={config.textColor}>{config.icon}</span>
      </div>
      {status === "processing" && (
        <motion.div className="mt-3 w-full bg-zinc-800/50 rounded-full h-1.5 overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-amber-400 to-yellow-400 rounded-full"
            animate={{ x: ["-100%", "100%"] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
            style={{ width: "40%" }}
          />
        </motion.div>
      )}
    </motion.div>
  );
};

const WeatherCard = ({ data }) => {
  if (!data || !data.weather_forecast) return null;

  const getAQILevel = (aqi) => {
    if (aqi <= 1)
      return {
        label: "Good",
        color: "text-emerald-400",
        bg: "bg-emerald-500/20",
      };
    if (aqi <= 2)
      return { label: "Fair", color: "text-green-400", bg: "bg-green-500/20" };
    if (aqi <= 3)
      return {
        label: "Moderate",
        color: "text-yellow-400",
        bg: "bg-yellow-500/20",
      };
    if (aqi <= 4)
      return {
        label: "Poor",
        color: "text-orange-400",
        bg: "bg-orange-500/20",
      };
    return { label: "Very Poor", color: "text-red-400", bg: "bg-red-500/20" };
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6"
    >
      <div className="p-6 rounded-3xl bg-gradient-to-br from-blue-900/40 to-cyan-900/40 border border-blue-500/30 backdrop-blur-xl shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 bg-blue-500/20 rounded-2xl">
            <Cloud className="w-8 h-8 text-blue-300" />
          </div>
          <div>
            <h3 className="text-2xl font-bold text-white">Weather Forecast</h3>
            <p className="text-blue-200 text-sm">{data.destination}</p>
          </div>
        </div>

        {data.weather_summary && (
          <div className="mb-6 p-4 bg-black/20 rounded-2xl border border-blue-500/20">
            <p className="text-blue-100 leading-relaxed">
              {data.weather_summary}
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {data.weather_forecast.map((day, idx) => {
            const aqiInfo = getAQILevel(day.air_quality?.aqi || 0);
            return (
              <motion.div
                key={idx}
                whileHover={{ scale: 1.02 }}
                className="p-5 bg-gradient-to-br from-blue-800/30 to-cyan-800/30 rounded-2xl border border-blue-400/20"
              >
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-blue-300" />
                    <p className="text-white font-bold">
                      {new Date(day.date).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                      })}
                    </p>
                  </div>
                  <div className={`px-3 py-1 rounded-full ${aqiInfo.bg}`}>
                    <p className={`text-xs font-bold ${aqiInfo.color}`}>
                      AQI: {aqiInfo.label}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="flex items-center gap-2">
                    <Thermometer className="w-5 h-5 text-orange-400" />
                    <div>
                      <p className="text-xs text-blue-200">High</p>
                      <p className="text-lg font-bold text-white">
                        {day.temp_max.toFixed(1)}°C
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Thermometer className="w-5 h-5 text-blue-400" />
                    <div>
                      <p className="text-xs text-blue-200">Low</p>
                      <p className="text-lg font-bold text-white">
                        {day.temp_min.toFixed(1)}°C
                      </p>
                    </div>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
};

const EventsCard = ({ data }) => {
  if (!data || !data.events || data.events.length === 0) return null;

  const getCategoryColor = (category) => {
    const colors = {
      music:
        "from-purple-500/20 to-pink-500/20 border-purple-500/30 text-purple-300",
      arts: "from-blue-500/20 to-cyan-500/20 border-blue-500/30 text-blue-300",
      food: "from-orange-500/20 to-red-500/20 border-orange-500/30 text-orange-300",
      sports:
        "from-green-500/20 to-emerald-500/20 border-green-500/30 text-green-300",
    };
    return (
      colors[category] ||
      "from-zinc-500/20 to-zinc-600/20 border-zinc-500/30 text-zinc-300"
    );
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6"
    >
      <div className="p-6 rounded-3xl bg-gradient-to-br from-fuchsia-900/40 to-pink-900/40 border border-fuchsia-500/30 backdrop-blur-xl shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 bg-fuchsia-500/20 rounded-2xl">
            <span className="text-4xl">🎉</span>
          </div>
          <div>
            <h3 className="text-2xl font-bold text-white">Local Events</h3>
            <p className="text-fuchsia-200 text-sm">
              {data.total_events} events found
            </p>
          </div>
        </div>

        {data.event_summary && (
          <div className="mb-6 p-4 bg-black/20 rounded-2xl border border-fuchsia-500/20">
            <p className="text-fuchsia-100 leading-relaxed">
              {data.event_summary}
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4">
          {data.events.slice(0, 6).map((event, idx) => (
            <motion.div
              key={idx}
              whileHover={{ scale: 1.02, x: 5 }}
              className={`p-5 rounded-2xl bg-gradient-to-br ${getCategoryColor(
                event.category
              )} border backdrop-blur-xl`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                  <h4 className="text-white font-bold text-lg mb-1">
                    {event.name}
                  </h4>
                  <p className="text-sm text-zinc-300">{event.description}</p>
                </div>
                <span className="px-3 py-1 bg-black/30 rounded-full text-xs font-bold uppercase">
                  {event.category}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="flex items-center gap-2 text-zinc-300">
                  <Calendar className="w-4 h-4" />
                  <span>
                    {new Date(event.date).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                    })}{" "}
                    at {event.time}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-zinc-300">
                  <MapPin className="w-4 h-4" />
                  <span>{event.venue}</span>
                </div>
                {event.price_min > 0 && (
                  <div className="flex items-center gap-2 text-zinc-300">
                    <DollarSign className="w-4 h-4" />
                    <span>
                      {event.currency} {event.price_min}-{event.price_max}
                    </span>
                  </div>
                )}
                {event.price_min === 0 && (
                  <div className="flex items-center gap-2 text-emerald-300">
                    <Star className="w-4 h-4" />
                    <span className="font-bold">FREE</span>
                  </div>
                )}
              </div>
            </motion.div>
          ))}
        </div>

        {data.statistics && (
          <div className="mt-6 grid grid-cols-3 gap-3">
            <div className="p-3 bg-black/20 rounded-xl text-center">
              <p className="text-2xl font-bold text-white">
                {data.statistics.total_events}
              </p>
              <p className="text-xs text-fuchsia-200">Total Events</p>
            </div>
            <div className="p-3 bg-black/20 rounded-xl text-center">
              <p className="text-2xl font-bold text-emerald-300">
                {data.free_events_count}
              </p>
              <p className="text-xs text-fuchsia-200">Free Events</p>
            </div>
            <div className="p-3 bg-black/20 rounded-xl text-center">
              <p className="text-2xl font-bold text-white">
                {data.statistics.venues_count}
              </p>
              <p className="text-xs text-fuchsia-200">Venues</p>
            </div>
          </div>
        )}
      </div>
    </motion.div>
  );
};

const RouteCard = ({ data }) => {
  if (!data || !data.primary_route) return null;

  const getModeIcon = (mode) => {
    switch (mode) {
      case "driving":
        return <Car className="w-6 h-6" />;
      case "walking":
        return <Users className="w-6 h-6" />;
      case "cycling":
        return <Navigation className="w-6 h-6" />;
      default:
        return <Navigation className="w-6 h-6" />;
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6"
    >
      <div className="p-6 rounded-3xl bg-gradient-to-br from-emerald-900/40 to-green-900/40 border border-emerald-500/30 backdrop-blur-xl shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 bg-emerald-500/20 rounded-2xl">
            <MapPin className="w-8 h-8 text-emerald-300" />
          </div>
          <div>
            <h3 className="text-2xl font-bold text-white">Route Information</h3>
            <p className="text-emerald-200 text-sm">
              {data.origin} → {data.destination}
            </p>
          </div>
        </div>

        {data.route_analysis && (
          <div className="mb-6 p-4 bg-black/20 rounded-2xl border border-emerald-500/20">
            <p className="text-emerald-100 leading-relaxed">
              {data.route_analysis}
            </p>
          </div>
        )}

        {/* Primary Route */}
        <div className="mb-6 p-5 bg-gradient-to-br from-emerald-800/30 to-green-800/30 rounded-2xl border border-emerald-400/30">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              {getModeIcon(data.primary_route.transport_mode)}
              <span className="text-white font-bold text-lg capitalize">
                {data.primary_route.transport_mode}
              </span>
              <span className="px-2 py-1 bg-emerald-500/20 rounded-full text-xs font-bold text-emerald-300">
                RECOMMENDED
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="flex items-center gap-2">
              <Navigation className="w-5 h-5 text-emerald-300" />
              <div>
                <p className="text-xs text-emerald-200">Distance</p>
                <p className="text-lg font-bold text-white">
                  {data.primary_route.distance}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-emerald-300" />
              <div>
                <p className="text-xs text-emerald-200">Duration</p>
                <p className="text-lg font-bold text-white">
                  {data.primary_route.duration}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Alternative Routes */}
        {data.alternative_routes && (
          <div className="space-y-3">
            <h4 className="text-white font-bold mb-3">Alternative Options</h4>
            {Object.entries(data.alternative_routes).map(([mode, route]) => (
              <motion.div
                key={mode}
                whileHover={{ scale: 1.02 }}
                className="p-4 bg-black/20 rounded-xl border border-emerald-500/10"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {getModeIcon(mode)}
                    <span className="text-white font-medium capitalize">
                      {mode}
                    </span>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-emerald-200">
                      {route.distance} • {route.duration}
                    </p>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
};

const BudgetCard = ({ data }) => {
  if (!data || !data.budget_breakdown) return null;

  const breakdown = data.budget_breakdown;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6"
    >
      <div className="p-6 rounded-3xl bg-gradient-to-br from-amber-900/40 to-yellow-900/40 border border-amber-500/30 backdrop-blur-xl shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 bg-amber-500/20 rounded-2xl">
            <DollarSign className="w-8 h-8 text-amber-300" />
          </div>
          <div>
            <h3 className="text-2xl font-bold text-white">Budget Breakdown</h3>
            <p className="text-amber-200 text-sm">
              {data.budget_category || "mid-range"} budget for{" "}
              {data.travelers_count} travelers
            </p>
          </div>
        </div>

        {data.budget_analysis && (
          <div className="mb-6 p-4 bg-black/20 rounded-2xl border border-amber-500/20">
            <p className="text-amber-100 leading-relaxed">
              {data.budget_analysis}
            </p>
          </div>
        )}

        {/* Total Budget */}
        <div className="mb-6 p-6 bg-gradient-to-br from-amber-700/30 to-yellow-700/30 rounded-2xl border border-amber-400/40 text-center">
          <p className="text-amber-200 text-sm mb-2">Total Budget</p>
          <p className="text-5xl font-bold text-white">
            {breakdown.currency} {breakdown.total.toLocaleString()}
          </p>
          {data.cost_per_person && (
            <p className="text-amber-200 text-sm mt-2">
              {breakdown.currency} {data.cost_per_person.toLocaleString()} per
              person
            </p>
          )}
        </div>

        {/* Breakdown */}
        <div className="space-y-3">
          {[
            {
              label: "Transportation",
              value: breakdown.transportation,
              icon: Car,
              color: "blue",
            },
            {
              label: "Accommodation",
              value: breakdown.accommodation,
              icon: MapPin,
              color: "purple",
            },
            {
              label: "Food & Dining",
              value: breakdown.food,
              icon: Star,
              color: "orange",
            },
            {
              label: "Activities",
              value: breakdown.activities,
              icon: TrendingUp,
              color: "green",
            },
          ].map((item, idx) => {
            const percentage = ((item.value / breakdown.total) * 100).toFixed(
              1
            );
            return (
              <motion.div
                key={idx}
                whileHover={{ x: 5 }}
                className="p-4 bg-black/20 rounded-xl border border-amber-500/10"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <item.icon className="w-5 h-5 text-amber-300" />
                    <span className="text-white font-medium">{item.label}</span>
                  </div>
                  <span className="text-white font-bold">
                    {breakdown.currency} {item.value.toLocaleString()}
                  </span>
                </div>
                <div className="w-full bg-zinc-800/50 rounded-full h-2 overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${percentage}%` }}
                    transition={{ duration: 1, delay: idx * 0.1 }}
                    className={`h-full bg-gradient-to-r from-amber-500 to-yellow-500 rounded-full`}
                  />
                </div>
                <p className="text-xs text-amber-200 mt-1">
                  {percentage}% of total
                </p>
              </motion.div>
            );
          })}
        </div>

        {/* Recommendations */}
        {data.recommendations && data.recommendations.length > 0 && (
          <div className="mt-6">
            <h4 className="text-white font-bold mb-3">💡 Money-Saving Tips</h4>
            <div className="space-y-2">
              {data.recommendations.map((tip, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2 p-3 bg-black/20 rounded-xl border border-amber-500/10"
                >
                  <CheckCircle className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-amber-100">{tip}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </motion.div>
  );
};

const ItineraryCard = ({ data }) => {
  if (!data || !data.itinerary_days) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6"
    >
      <div className="p-6 rounded-3xl bg-gradient-to-br from-violet-900/40 to-purple-900/40 border border-violet-500/30 backdrop-blur-xl shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 bg-violet-500/20 rounded-2xl">
            <span className="text-4xl">✨</span>
          </div>
          <div>
            <h3 className="text-2xl font-bold text-white">Your Itinerary</h3>
            <p className="text-violet-200 text-sm">
              {data.total_days} days in {data.destination}
            </p>
          </div>
        </div>

        {data.itinerary_narrative && (
          <div className="mb-6 p-4 bg-black/20 rounded-2xl border border-violet-500/20">
            <p className="text-violet-100 leading-relaxed line-clamp-3">
              {data.itinerary_narrative.split("\n")[0]}
            </p>
          </div>
        )}

        <div className="space-y-6">
          {data.itinerary_days.map((day, dayIdx) => (
            <motion.div
              key={dayIdx}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: dayIdx * 0.1 }}
              className="p-5 bg-gradient-to-br from-violet-800/30 to-purple-800/30 rounded-2xl border border-violet-400/30"
            >
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 bg-violet-500/20 rounded-full flex items-center justify-center">
                    <span className="text-xl font-bold text-white">
                      {day.day}
                    </span>
                  </div>
                  <div>
                    <h4 className="text-white font-bold text-lg">
                      Day {day.day}
                    </h4>
                    <p className="text-violet-200 text-sm">
                      {new Date(day.date).toLocaleDateString("en-US", {
                        weekday: "long",
                        month: "long",
                        day: "numeric",
                      })}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-white font-bold">
                    {day.estimated_cost
                      ? `₹${day.estimated_cost.toLocaleString()}`
                      : ""}
                  </p>
                  <p className="text-violet-200 text-xs">estimated cost</p>
                </div>
              </div>

              {day.notes && (
                <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/20 rounded-xl">
                  <p className="text-sm text-blue-200 flex items-center gap-2">
                    <Cloud className="w-4 h-4" />
                    {day.notes}
                  </p>
                </div>
              )}

              <div className="space-y-2">
                {day.activities.map((activity, actIdx) => (
                  <motion.div
                    key={actIdx}
                    whileHover={{ x: 5 }}
                    className="p-3 bg-black/20 rounded-xl border border-violet-500/10 hover:border-violet-500/30 transition-colors"
                  >
                    <p className="text-violet-100 text-sm leading-relaxed">
                      {activity}
                    </p>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          ))}
        </div>

        {/* Transport Details */}
        {data.transport_details && (
          <div className="mt-6 p-5 bg-black/20 rounded-2xl border border-violet-500/20">
            <h4 className="text-white font-bold mb-3 flex items-center gap-2">
              <Train className="w-5 h-5" />
              Transportation Info
            </h4>
            {data.transport_details.recommended_trains && (
              <div className="mb-3">
                <p className="text-violet-200 text-sm mb-2">
                  Recommended Trains:
                </p>
                <div className="space-y-2">
                  {data.transport_details.recommended_trains.map(
                    (train, idx) => (
                      <div
                        key={idx}
                        className="p-2 bg-violet-500/10 rounded-lg"
                      >
                        <p className="text-white text-sm">{train}</p>
                      </div>
                    )
                  )}
                </div>
              </div>
            )}
            {data.transport_details.local_transport && (
              <div className="p-3 bg-violet-500/10 rounded-lg">
                <p className="text-violet-100 text-sm">
                  {data.transport_details.local_transport}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Key Tips */}
        {data.key_tips && data.key_tips.length > 0 && (
          <div className="mt-6">
            <h4 className="text-white font-bold mb-3">💡 Pro Tips</h4>
            <div className="space-y-2">
              {data.key_tips.map((tip, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2 p-3 bg-black/20 rounded-xl border border-violet-500/10"
                >
                  <Star className="w-4 h-4 text-yellow-400 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-violet-100">{tip}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </motion.div>
  );
};

const TravelChatPage = () => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isConnected, setIsConnected] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState("");
  const [agentStatuses, setAgentStatuses] = useState({});
  const [progressPercent, setProgressPercent] = useState(0);
  const [results, setResults] = useState({});

  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingMessage, agentStatuses]);

  const connectWebSocket = (sessionId) => {
    return new Promise((resolve, reject) => {
      if (wsRef.current) {
        wsRef.current.close();
      }

      const ws = new WebSocket(
        `ws://localhost:8000/api/v2/orchestrator/ws/${sessionId}`
      );

      ws.onopen = () => {
        setIsConnected(true);
        resolve(ws);
      };

      ws.onmessage = (event) => {
        try {
          const update = JSON.parse(event.data);

          switch (update.type) {
            case "connected":
              setStreamingMessage("Connected to travel planning system...");
              if (update.context) {
                setMessages((prev) => [
                  ...prev,
                  {
                    role: "assistant",
                    content: `Continuing your trip to ${update.context.destination}`,
                    timestamp: update.timestamp,
                  },
                ]);
              }
              break;

            case "agent_start":
              setAgentStatuses((prev) => ({
                ...prev,
                [update.agent]: "processing",
              }));
              setStreamingMessage(update.message);
              break;

            case "progress":
              setStreamingMessage(update.message);
              if (update.progress_percent) {
                setProgressPercent(update.progress_percent);
              }
              break;

            case "agent_update":
              if (update.agent) {
                setAgentStatuses((prev) => ({
                  ...prev,
                  [update.agent]: "completed",
                }));
              }
              setStreamingMessage(update.message);

              if (update.data) {
                setResults((prev) => ({ ...prev, ...update.data }));

                // Check if itinerary data was included and mark it as completed
                if (update.data.itinerary_data) {
                  setAgentStatuses((prev) => ({
                    ...prev,
                    itinerary: "completed",
                  }));
                }
              }
              break;

            case "completed":
              setStreamingMessage("");
              setIsProcessing(false);
              setProgressPercent(100);

              const resultSummary = [];
              if (update.data?.weather_data) resultSummary.push("Weather");
              if (update.data?.events_data) resultSummary.push("Events");
              if (update.data?.maps_data) resultSummary.push("Routes");
              if (update.data?.budget_data) resultSummary.push("Budget");
              if (update.data?.itinerary_data) resultSummary.push("Itinerary");

              setMessages((prev) => [
                ...prev,
                {
                  role: "assistant",
                  content: `✨ Travel plan complete! Generated: ${resultSummary.join(
                    ", "
                  )}`,
                  timestamp: update.timestamp,
                },
              ]);

              if (update.data) {
                setResults(update.data);
              }
              break;

            case "error":
              setStreamingMessage("");
              if (update.agent) {
                setAgentStatuses((prev) => ({
                  ...prev,
                  [update.agent]: "failed",
                }));
              }
              setMessages((prev) => [
                ...prev,
                {
                  role: "assistant",
                  content: `❌ Error: ${update.message}`,
                  timestamp: update.timestamp,
                },
              ]);
              break;

            case "timeout":
              setIsConnected(false);
              setStreamingMessage("");
              break;
          }
        } catch (error) {
          console.error("Error parsing WebSocket message:", error);
        }
      };

      ws.onerror = (error) => {
        setIsConnected(false);
        setStreamingMessage("");
        reject(error);
      };

      ws.onclose = () => {
        setIsConnected(false);
      };

      wsRef.current = ws;
    });
  };

  const handleSendMessage = async () => {
    if (!input.trim() || isProcessing) return;

    const userMessage = {
      role: "user",
      content: input,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const userInput = input;
    setInput("");
    setIsProcessing(true);
    setStreamingMessage("Connecting...");
    setAgentStatuses({});
    setProgressPercent(0);
    setResults({});

    try {
      const newSessionId =
        sessionId ||
        `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

      if (!sessionId) {
        setSessionId(newSessionId);
      }

      await connectWebSocket(newSessionId);
      await new Promise((resolve) => setTimeout(resolve, 300));

      setStreamingMessage("Initiating workflow...");

      const response = await fetch(
        "http://localhost:8000/api/v2/orchestrator/plan",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: userInput,
            session_id: newSessionId,
          }),
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to process query");
      }

      setStreamingMessage("Workflow started - processing agents...");
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `❌ Failed to process your request: ${error.message}`,
          timestamp: new Date().toISOString(),
        },
      ]);
      setIsProcessing(false);
      setStreamingMessage("");
      if (wsRef.current) {
        wsRef.current.close();
      }
    }
  };

  const handleNewConversation = () => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    setMessages([]);
    setSessionId(null);
    setIsConnected(false);
    setIsProcessing(false);
    setStreamingMessage("");
    setAgentStatuses({});
    setProgressPercent(0);
    setResults({});
  };

  return (
    <div className="min-h-screen w-screen overflow-x-hidden bg-black relative">
      <HyperspeedBackground />
      <div className="bg-gradient-to-b from-black/80 via-black/60 to-black/80 inset-0 absolute" />

      <div className="relative z-10 flex flex-col h-screen">
        {/* Header */}
        <div className="sticky top-0 backdrop-blur-2xl bg-black/70 border-b border-violet-500/20 px-6 py-5 shadow-2xl">
          <div className="max-w-6xl mx-auto flex justify-between items-center">
            <div>
              <h1 className="text-3xl font-bold bg-gradient-to-r from-violet-400 via-fuchsia-400 to-purple-400 bg-clip-text text-transparent">
                Travel Intelligence
              </h1>
              <p className="text-sm text-violet-300/60 mt-1 flex items-center gap-2">
                {sessionId ? (
                  <>
                    <span className="w-2 h-2 bg-violet-400 rounded-full animate-pulse" />
                    Session: {sessionId.slice(0, 15)}...
                  </>
                ) : (
                  "Ready to plan your journey"
                )}
                {isConnected && (
                  <span className="ml-2 text-emerald-400 flex items-center gap-1">
                    <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
                    Live
                  </span>
                )}
              </p>
            </div>
            <button
              onClick={handleNewConversation}
              className="px-6 py-3 bg-gradient-to-r from-violet-600/20 to-fuchsia-600/20 hover:from-violet-600/30 hover:to-fuchsia-600/30 border border-violet-500/30 rounded-2xl text-violet-200 transition-all backdrop-blur-xl font-medium"
            >
              New Journey
            </button>
          </div>
        </div>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto px-6 py-8">
          <div className="max-w-5xl mx-auto">
            <AnimatePresence>
              {messages.map((msg, idx) => (
                <ChatMessage
                  key={idx}
                  message={msg}
                  isUser={msg.role === "user"}
                />
              ))}

              {isProcessing && streamingMessage && (
                <StreamingIndicator message={streamingMessage} />
              )}

              {/* Progress Bar */}
              {isProcessing && progressPercent > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="mb-6"
                >
                  <div className="w-full bg-zinc-800/50 rounded-full h-3 overflow-hidden backdrop-blur-xl border border-violet-500/20">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${progressPercent}%` }}
                      transition={{ duration: 0.5, ease: "easeOut" }}
                      className="h-full bg-gradient-to-r from-violet-500 via-fuchsia-500 to-purple-500 rounded-full shadow-lg shadow-violet-500/50"
                    />
                  </div>
                  <p className="text-xs text-violet-300 mt-2 text-center font-medium">
                    {progressPercent}% complete
                  </p>
                </motion.div>
              )}

              {/* Agent Status Cards */}
              {Object.keys(agentStatuses).length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6"
                >
                  {Object.entries(agentStatuses).map(([agent, status]) => (
                    <AgentStatusCard
                      key={agent}
                      agent={agent}
                      status={status}
                    />
                  ))}
                </motion.div>
              )}

              {/* Results - Beautiful Component Cards */}
              {results.weather_data && (
                <WeatherCard data={results.weather_data} />
              )}
              {results.events_data && <EventsCard data={results.events_data} />}
              {results.maps_data && <RouteCard data={results.maps_data} />}
              {results.budget_data && <BudgetCard data={results.budget_data} />}
              {results.itinerary_data && (
                <ItineraryCard data={results.itinerary_data} />
              )}
            </AnimatePresence>

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input Area */}
        <div className="sticky bottom-0 backdrop-blur-2xl bg-black/70 border-t border-violet-500/20 px-6 py-6 shadow-2xl">
          <div className="max-w-5xl mx-auto">
            <div className="flex gap-3">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={(e) => e.key === "Enter" && handleSendMessage()}
                placeholder="Example: Plan a trip to Paris from London, Oct 20-25, budget $2000"
                disabled={isProcessing}
                className="flex-1 bg-zinc-900/60 border border-violet-500/30 rounded-2xl px-6 py-4 text-zinc-100 placeholder-violet-300/40 focus:outline-none focus:border-violet-400/60 focus:ring-2 focus:ring-violet-400/20 disabled:opacity-50 backdrop-blur-xl transition-all"
              />
              <button
                onClick={handleSendMessage}
                disabled={!input.trim() || isProcessing}
                className="px-8 py-4 bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 disabled:from-zinc-800 disabled:to-zinc-700 text-white rounded-2xl transition-all disabled:cursor-not-allowed disabled:opacity-50 font-bold shadow-lg shadow-violet-500/30 hover:shadow-violet-500/50"
              >
                {isProcessing ? "Planning..." : "Send"}
              </button>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-violet-300/60">
              <div className="flex items-center gap-1.5">
                <MapPin className="w-3 h-3" />
                <span>Include origin & destination</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Calendar className="w-3 h-3" />
                <span>Specify travel dates</span>
              </div>
              <div className="flex items-center gap-1.5">
                <DollarSign className="w-3 h-3" />
                <span>Mention your budget</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Users className="w-3 h-3" />
                <span>Number of travelers (optional)</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TravelChatPage;
