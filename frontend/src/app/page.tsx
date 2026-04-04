"use client"
import { useState, useEffect, useRef, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Hyperspeed from '@/components/Hyperspeed/Hyperspeed';

// Memoized background components to prevent re-renders
const HyperspeedBackground = memo(function HyperspeedBackground() {
  return (
    <div className='absolute scale-60 -left-75 -top-50 bottom-0 right-0 h-full w-full pointer-events-none'>
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
      sticks: 0xf1eece
    }
          }}
      />
      <div className="w-full h-full bg-gradient-to-b from-zinc-900/20 to-black/40" />
    </div>
  );
});

const LightRaysBackground = memo(function LightRaysBackground() {
  return (
    <div className='fixed inset-0 h-screen w-screen pointer-events-none'>
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
  "Uncover treasures in Morocco..."
];

const titles = [
  "Where planning is Spontaneous",
  "Less Google, More Goggles",
  "Plan less, Chill more"
];

const TypewriterPrompt = ({ onSubmit }) => {
  const [displayText, setDisplayText] = useState('');
  const [currentPhraseIndex, setCurrentPhraseIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [userInput, setUserInput] = useState('');

  useEffect(() => {
    const currentPhrase = placeholderTexts[currentPhraseIndex];
    const typingSpeed = isDeleting ? 30 : 80;
    const pauseBeforeDelete = 2000;

    const timer = setTimeout(() => {
      if (!isDeleting && displayText === currentPhrase) {
        setTimeout(() => setIsDeleting(true), pauseBeforeDelete);
      } else if (isDeleting && displayText === '') {
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
    if (userInput.trim()) {
      onSubmit(userInput);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleQuickAction = (tag) => {
    setUserInput(prev => prev ? `${prev} ${tag}` : tag);
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
          className="w-full min-h-[120px] bg-black/40 backdrop-blur-md border border-zinc-600/50 rounded-2xl p-5 pr-14 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 resize-none transition-all duration-300 shadow-2xl"
          placeholder={displayText}
        />
        <button 
          onClick={handleSubmit}
          className="absolute bottom-4 right-4 bg-gradient-to-r from-red-700 to-red-900 hover:from-red-600 hover:to-red-700 text-white p-3 rounded-xl transition-all duration-300 shadow-lg hover:shadow-red-500/50 group disabled:opacity-50 disabled:cursor-not-allowed"
          disabled={!userInput.trim()}
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
        {['Weekend Getaway', 'Family Trip', 'Solo Adventure', 'Budget Travel'].map((tag) => (
          <button
            key={tag}
            onClick={() => handleQuickAction(tag)}
            className="px-4 py-2 bg-zinc-800/50 backdrop-blur-sm border border-zinc-700/50 rounded-full text-sm text-zinc-300 hover:bg-zinc-700/50 hover:border-amber-400 transition-all duration-300"
          >
            {tag}
          </button>
        ))}
      </div>

      <div className="mt-8 flex gap-6 text-sm text-zinc-400 mb-8 justify-center">
        <div className="flex flex-row items-center gap-2">
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

const LoadingState = () => {
  const stages = [
    { text: "Ringmaster is thinking", icon: "🎪" },
    { text: "Analyzing your preferences", icon: "🔍" },
    { text: "Checking weather conditions", icon: "🌤️" },
    { text: "Finding the best routes", icon: "🗺️" },
    { text: "Calculating your budget", icon: "💰" },
    { text: "Crafting your perfect itinerary", icon: "✨" }
  ];

  const [currentStage, setCurrentStage] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentStage(prev => (prev + 1) % stages.length);
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
              i === currentStage ? 'w-8 bg-red-500' : 'w-1.5 bg-zinc-700'
            }`}
          />
        ))}
      </div>
    </div>
  );
};

const ItineraryView = ({ data, userQuery }) => {
  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: data.budget.currency || 'INR',
      maximumFractionDigits: 0
    }).format(amount);
  };

  const getWeatherIcon = (description) => {
    if (description.includes('rain')) return '🌧️';
    if (description.includes('cloud')) return '☁️';
    if (description.includes('sun')) return '☀️';
    return '🌤️';
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="w-full max-w-6xl mx-auto px-4 pb-20"
    >
      {/* User Query Display */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8 p-6 bg-zinc-900/50 backdrop-blur-md border border-zinc-800 rounded-2xl"
      >
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-400 to-red-500 flex items-center justify-center text-white font-bold">
            You
          </div>
          <div className="flex-1">
            <p className="text-zinc-300 text-lg">{userQuery}</p>
          </div>
        </div>
      </motion.div>

      {/* AI Response Header */}
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
            <div className="text-2xl font-bold text-amber-400">{formatCurrency(data.budget.total)}</div>
            <div className="text-sm text-zinc-400">Total</div>
          </div>
          <div className="text-center">
            <div className="text-lg text-zinc-300">{formatCurrency(data.budget.transportation)}</div>
            <div className="text-sm text-zinc-400">Transport</div>
          </div>
          <div className="text-center">
            <div className="text-lg text-zinc-300">{formatCurrency(data.budget.accommodation)}</div>
            <div className="text-sm text-zinc-400">Stay</div>
          </div>
          <div className="text-center">
            <div className="text-lg text-zinc-300">{formatCurrency(data.budget.food)}</div>
            <div className="text-sm text-zinc-400">Food</div>
          </div>
          <div className="text-center">
            <div className="text-lg text-zinc-300">{formatCurrency(data.budget.activities)}</div>
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
              {data.weather[index] && (
                <div className="text-sm text-zinc-400 flex items-center gap-2 mt-1">
                  <span>{getWeatherIcon(data.weather[index].description)}</span>
                  <span>{Math.round(data.weather[index].temperature_max)}°C</span>
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
  const [isPlanning, setIsPlanning] = useState(false);
  const [planData, setPlanData] = useState(null);
  const [userQuery, setUserQuery] = useState('');

  // Animate title changes
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTitleIndex((prev) => (prev + 1) % titles.length);
    }, 4000);
    return () => clearInterval(interval);
  }, []);

 const handlePlanSubmit = async (query) => {
   setUserQuery(query);
   setIsPlanning(true);

   try {
     // Parse the user query to extract trip details
     // This is a simple implementation - you may want to enhance this with NLP
     const payload = {
       query: "Agra to Delhi trip",
       budget_range: "$100-300", // Example, adjust as needed
       destination: "Delhi, India",
       origin: "Agra, India",
       travel_dates: ["2025-10-05", "2025-10-06"], // adjust for actual plan
       travelers_count: 2,
       user_preferences: {
         dietary_restrictions: [],
         interests: ["history", "food", "culture"],
         pace: "moderate",
       },
     };


     const response = await fetch("http://localhost:8000/api/v1/plan-trip", {
       method: "POST",
       headers: {
         "Content-Type": "application/json",
       },
       body: JSON.stringify(payload),
     });

     if (!response.ok) {
       throw new Error("Failed to generate plan");
     }

     const result = await response.json();
     setPlanData(result.data);
   } catch (error) {
     console.error("Error generating plan:", error);
     alert("Failed to generate travel plan. Please try again.");
     setIsPlanning(false);
   }
 };

  const handleNewPlan = () => {
    setIsPlanning(false);
    setPlanData(null);
    setUserQuery('');
  };

  return (
    <div className="h-screen w-screen overflow-hidden bg-black relative">
      <LightRaysBackground />
      <HyperspeedBackground />
      <div className='bg-black/60 inset-0 absolute' />

      <div className="relative z-10 h-full w-full">
        <AnimatePresence mode="wait">
          {!isPlanning && !planData ? (
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
          ) : !planData ? (
            <motion.div
              key="loading"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="h-full flex items-center justify-center"
            >
              <LoadingState />
            </motion.div>
          ) : (
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
                    Generated in {Math.round((planData.processing_time_ms || 88645) / 1000)}s
                  </div>
                </div>
              </div>
              <div className="pt-8">
                <ItineraryView data={planData} userQuery={userQuery} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default Page