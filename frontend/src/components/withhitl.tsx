"use client";
import { useState, useEffect, useRef, memo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Hyperspeed from "@/components/Hyperspeed/Hyperspeed";
import { Send, CheckCircle, XCircle } from "lucide-react";

// Memoized background components to prevent re-renders
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
      {/* Your LightRays component here */}
      <div className="w-full h-full opacity-30">
        <div className="absolute inset-0 bg-gradient-to-br from-red-900/10 via-transparent to-amber-900/10" />
      </div>
    </div>
  );
});

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

const TypewriterPrompt = ({ onSubmit, disabled }) => {
  const [displayText, setDisplayText] = useState("");
  const [currentPhraseIndex, setCurrentPhraseIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [userInput, setUserInput] = useState("");

  useEffect(() => {
    const currentPhrase = placeholderTexts[currentPhraseIndex];
    const typingSpeed = isDeleting ? 30 : 80;
    const pauseBeforeDelete = 2000;

    const timer = setTimeout(() => {
      if (!isDeleting && displayText === currentPhrase) {
        setTimeout(() => setIsDeleting(true), pauseBeforeDelete);
      } else if (isDeleting && displayText === "") {
        setIsDeleting(false);
        setCurrentPhraseIndex((prev) => (prev + 1) % placeholderTexts.length);
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
      onSubmit(userInput);
      setUserInput("");
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
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
          <Send className="h-5 w-5 group-hover:translate-x-0.5 transition-transform" />
        </button>
      </div>
    </motion.div>
  );
};

const ConversationView = ({
  messages,
  collectedInfo,
  stage,
  missingFields,
  isReady,
  onConfirm,
  isLoading,
}) => {
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="w-full max-w-6xl mx-auto px-4 pb-20">
      {/* Chat Messages */}
      <div className="space-y-4 mb-8">
        {messages.map((msg, idx) => (
          <motion.div
            key={idx}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.1 }}
            className={`flex ${
              msg.role === "user" ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`max-w-[80%] rounded-2xl p-5 ${
                msg.role === "user"
                  ? "bg-gradient-to-r from-red-700 to-red-900 text-white"
                  : "bg-black/40 backdrop-blur-md border border-zinc-800/50 text-zinc-100"
              }`}
            >
              <p className="whitespace-pre-wrap leading-relaxed">
                {msg.content}
              </p>
              <p
                className={`text-xs mt-2 ${
                  msg.role === "user" ? "text-red-200" : "text-zinc-500"
                }`}
              >
                {new Date(msg.timestamp).toLocaleTimeString()}
              </p>
            </div>
          </motion.div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Info Panel */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6"
      >
        {/* Stage Indicator */}
        <div className="bg-black/40 backdrop-blur-md border border-zinc-800/50 rounded-2xl p-5">
          <h3 className="text-sm text-zinc-400 mb-2">Conversation Stage</h3>
          <span className="inline-block px-4 py-2 bg-gradient-to-r from-red-900/50 to-amber-900/50 rounded-full text-sm font-medium text-zinc-100 border border-red-800/30">
            {stage}
          </span>
        </div>

        {/* Collected Info Summary */}
        <div className="bg-black/40 backdrop-blur-md border border-zinc-800/50 rounded-2xl p-5">
          <h3 className="text-sm text-zinc-400 mb-3">Trip Details</h3>
          <div className="space-y-2">
            {collectedInfo.destination && (
              <div className="flex items-center gap-2 text-sm">
                <CheckCircle className="w-4 h-4 text-green-500" />
                <span className="text-zinc-300">
                  {collectedInfo.destination}
                </span>
              </div>
            )}
            {collectedInfo.travel_dates && (
              <div className="flex items-center gap-2 text-sm">
                <CheckCircle className="w-4 h-4 text-green-500" />
                <span className="text-zinc-300">
                  {collectedInfo.travel_dates.join(" to ")}
                </span>
              </div>
            )}
            {missingFields.length > 0 && (
              <div className="text-xs text-amber-400 mt-2">
                Still need: {missingFields.join(", ")}
              </div>
            )}
          </div>
        </div>
      </motion.div>

      {/* Confirm Button */}
      {isReady && (
        <motion.button
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={onConfirm}
          disabled={isLoading}
          className="w-full bg-gradient-to-r from-green-600 to-emerald-700 hover:from-green-500 hover:to-emerald-600 text-white py-4 rounded-2xl font-semibold text-lg shadow-xl hover:shadow-green-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoading ? (
            <span className="flex items-center justify-center gap-2">
              <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Planning your trip...
            </span>
          ) : (
            "✈️ Confirm & Generate Itinerary"
          )}
        </motion.button>
      )}
    </div>
  );
};

const LoadingState = () => {
  const stages = [
    { text: "Ringmaster is thinking", icon: "🎪" },
    { text: "Analyzing your preferences", icon: "🔍" },
    { text: "Checking weather conditions", icon: "🌤️" },
    { text: "Finding the best routes", icon: "🗺️" },
    { text: "Calculating your budget", icon: "💰" },
    { text: "Crafting your perfect itinerary", icon: "✨" },
  ];

  const [currentStage, setCurrentStage] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentStage((prev) => (prev + 1) % stages.length);
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col items-center justify-center space-y-8">
      <motion.div
        className="relative"
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

const ItineraryView = ({ data, onNewPlan }) => {
  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: data.budget.currency || "INR",
      maximumFractionDigits: 0,
    }).format(amount);
  };

  const getWeatherIcon = (description) => {
    if (description?.includes("rain")) return "🌧️";
    if (description?.includes("cloud")) return "☁️";
    if (description?.includes("sun")) return "☀️";
    return "🌤️";
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="w-full max-w-6xl mx-auto px-4 pb-20"
    >
      {/* Budget Overview */}
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
          <div className="text-center">
            <div className="text-2xl font-bold text-amber-400">
              {formatCurrency(data.budget.total)}
            </div>
            <div className="text-sm text-zinc-400">Total</div>
          </div>
          <div className="text-center">
            <div className="text-lg text-zinc-300">
              {formatCurrency(data.budget.transportation)}
            </div>
            <div className="text-sm text-zinc-400">Transport</div>
          </div>
          <div className="text-center">
            <div className="text-lg text-zinc-300">
              {formatCurrency(data.budget.accommodation)}
            </div>
            <div className="text-sm text-zinc-400">Stay</div>
          </div>
          <div className="text-center">
            <div className="text-lg text-zinc-300">
              {formatCurrency(data.budget.food)}
            </div>
            <div className="text-sm text-zinc-400">Food</div>
          </div>
          <div className="text-center">
            <div className="text-lg text-zinc-300">
              {formatCurrency(data.budget.activities)}
            </div>
            <div className="text-sm text-zinc-400">Activities</div>
          </div>
        </div>
      </motion.div>

      {/* Itinerary Days */}
      {data.itinerary.map((day, index) => (
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
              <div className="text-lg text-amber-400 font-semibold">
                {formatCurrency(day.estimated_cost)}
              </div>
              {data.weather && data.weather[index] && (
                <div className="text-sm text-zinc-400 flex items-center gap-2 mt-1">
                  <span>{getWeatherIcon(data.weather[index].description)}</span>
                  <span>
                    {Math.round(data.weather[index].temperature_max)}°C
                  </span>
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
      ))}
    </motion.div>
  );
};

const Page = () => {
  const [currentTitleIndex, setCurrentTitleIndex] = useState(0);
  const [phase, setPhase] = useState("landing"); // landing, conversation, planning, results
  const [messages, setMessages] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [collectedInfo, setCollectedInfo] = useState({});
  const [stage, setStage] = useState("greeting");
  const [missingFields, setMissingFields] = useState([]);
  const [isReadyToPlan, setIsReadyToPlan] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [tripPlan, setTripPlan] = useState(null);

  const API_BASE_URL = "http://localhost:8000/api/v1/chat";

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTitleIndex((prev) => (prev + 1) % titles.length);
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  const handleInitialSubmit = async (query) => {
    setPhase("conversation");
    await sendChatMessage(query);
  };

  const sendChatMessage = async (message) => {
    const userMessage = {
      role: "user",
      content: message,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: sessionId || undefined,
        }),
      });

      if (!response.ok)
        throw new Error(`HTTP error! status: ${response.status}`);

      const data = await response.json();

      if (!sessionId) setSessionId(data.session_id);

      const assistantMessage = {
        role: "assistant",
        content: data.message,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setCollectedInfo(data.collected_info);
      setStage(data.stage);
      setMissingFields(data.missing_fields);
      setIsReadyToPlan(data.is_ready);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
      console.error("Error:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirmAndPlan = async () => {
    if (!sessionId || !isReadyToPlan) return;

    setPhase("planning");
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          confirmed: true,
        }),
      });

      if (!response.ok)
        throw new Error(`HTTP error! status: ${response.status}`);

      const data = await response.json();

      if (data.success) {
        setTripPlan(data.data);
        setPhase("results");
      } else {
        throw new Error(data.error || "Failed to create trip plan");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to confirm trip");
      console.error("Error:", err);
      setPhase("conversation");
    } finally {
      setIsLoading(false);
    }
  };

  const handleNewPlan = () => {
    setPhase("landing");
    setMessages([]);
    setSessionId("");
    setCollectedInfo({});
    setStage("greeting");
    setMissingFields([]);
    setIsReadyToPlan(false);
    setTripPlan(null);
    setError(null);
  };

  return (
    <div className="h-screen w-screen overflow-hidden bg-black relative">
      <LightRaysBackground />
      <HyperspeedBackground />
      <div className="bg-black/60 inset-0 absolute" />

      <div className="relative z-10 h-full w-full">
        <AnimatePresence mode="wait">
          {phase === "landing" && (
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
                  Describe your dream trip and let AI craft the perfect
                  itinerary
                </motion.p>
              </div>
              <TypewriterPrompt
                onSubmit={handleInitialSubmit}
                disabled={isLoading}
              />
            </motion.div>
          )}

          {phase === "conversation" && (
            <motion.div
              key="conversation"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
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
                    ← Start Over
                  </motion.button>
                  <div className="text-zinc-400 text-sm">
                    {sessionId && `Session: ${sessionId.substring(0, 15)}...`}
                  </div>
                </div>
              </div>
              <div className="pt-8">
                <ConversationView
                  messages={messages}
                  collectedInfo={collectedInfo}
                  stage={stage}
                  missingFields={missingFields}
                  isReady={isReadyToPlan}
                  onConfirm={handleConfirmAndPlan}
                  isLoading={isLoading}
                />
                <div className="max-w-6xl mx-auto px-4 pb-6">
                  <TypewriterPrompt
                    onSubmit={sendChatMessage}
                    disabled={isLoading || isReadyToPlan}
                  />
                </div>
              </div>
            </motion.div>
          )}

          {phase === "planning" && (
            <motion.div
              key="planning"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="h-full flex items-center justify-center"
            >
              <LoadingState />
            </motion.div>
          )}

          {phase === "results" && tripPlan && (
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
                    Generated in{" "}
                    {Math.round((tripPlan.processing_time_ms || 88645) / 1000)}s
                  </div>
                </div>
              </div>
              <div className="pt-8">
                <ItineraryView data={tripPlan} onNewPlan={handleNewPlan} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <motion.div
            initial={{ opacity: 0, y: 50 }}
            animate={{ opacity: 1, y: 0 }}
            className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50"
          >
            <div className="bg-red-900/90 backdrop-blur-md border border-red-700 rounded-xl p-4 flex items-center gap-3 shadow-2xl">
              <XCircle className="w-5 h-5 text-red-200" />
              <p className="text-red-100">{error}</p>
              <button
                onClick={() => setError(null)}
                className="ml-4 text-red-200 hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
};

export default Page;
