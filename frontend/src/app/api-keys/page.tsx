// app/api-keys/page.tsx
"use client";

import Link from "next/link";

export default function APIKeysLandingPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-purple-50 to-pink-50">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="text-center mb-16">
          <h1 className="text-5xl font-bold text-gray-900 mb-4">
            🎪 Ringmaster Round Table
          </h1>
          <p className="text-xl text-gray-600 mb-2">
            API Key Management Portal
          </p>
          <p className="text-gray-500">
            Generate and manage your API keys for the travel planning system
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-8 mb-12">
          <Link href="/api-keys/create">
            <div className="bg-white rounded-xl shadow-lg p-8 hover:shadow-2xl transition-all duration-300 hover:-translate-y-1 cursor-pointer border-2 border-transparent hover:border-indigo-500">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-indigo-100 rounded-full mb-6">
                <span className="text-3xl">🔑</span>
              </div>
              <h2 className="text-2xl font-bold text-gray-900 mb-3">
                Create API Key
              </h2>
              <p className="text-gray-600 mb-4">
                Generate a new 24-hour API key with read and write permissions.
                Perfect for testing and short-term projects.
              </p>
              <div className="flex items-center text-indigo-600 font-semibold">
                Get Started
                <svg
                  className="w-5 h-5 ml-2"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              </div>
            </div>
          </Link>

          <Link href="/api-keys/verify">
            <div className="bg-white rounded-xl shadow-lg p-8 hover:shadow-2xl transition-all duration-300 hover:-translate-y-1 cursor-pointer border-2 border-transparent hover:border-purple-500">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-purple-100 rounded-full mb-6">
                <span className="text-3xl">🔍</span>
              </div>
              <h2 className="text-2xl font-bold text-gray-900 mb-3">
                Verify API Key
              </h2>
              <p className="text-gray-600 mb-4">
                Check the status, usage statistics, and expiration time of your
                existing API key.
              </p>
              <div className="flex items-center text-purple-600 font-semibold">
                Check Status
                <svg
                  className="w-5 h-5 ml-2"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              </div>
            </div>
          </Link>
        </div>

        <div className="bg-white rounded-xl shadow-lg p-8 mb-8">
          <h2 className="text-2xl font-bold text-gray-900 mb-6 flex items-center">
            <span className="mr-3">📚</span>
            Quick Start Guide
          </h2>

          <div className="space-y-6">
            <div className="flex gap-4">
              <div className="flex-shrink-0 w-8 h-8 bg-indigo-600 text-white rounded-full flex items-center justify-center font-bold">
                1
              </div>
              <div>
                <h3 className="font-semibold text-gray-900 mb-2">
                  Create Your API Key
                </h3>
                <p className="text-gray-600 text-sm">
                  Enter your name and optionally a description. Your key will be
                  valid for 24 hours.
                </p>
              </div>
            </div>

            <div className="flex gap-4">
              <div className="flex-shrink-0 w-8 h-8 bg-indigo-600 text-white rounded-full flex items-center justify-center font-bold">
                2
              </div>
              <div>
                <h3 className="font-semibold text-gray-900 mb-2">
                  Save Your Key Securely
                </h3>
                <p className="text-gray-600 text-sm">
                  Copy and store your API key immediately - it will only be
                  shown once!
                </p>
              </div>
            </div>

            <div className="flex gap-4">
              <div className="flex-shrink-0 w-8 h-8 bg-indigo-600 text-white rounded-full flex items-center justify-center font-bold">
                3
              </div>
              <div>
                <h3 className="font-semibold text-gray-900 mb-2">
                  Use in Your Requests
                </h3>
                <p className="text-gray-600 text-sm mb-3">
                  Include the key in the{" "}
                  <code className="bg-gray-100 px-2 py-1 rounded text-xs">
                    X-API-Key
                  </code>{" "}
                  header for all API requests.
                </p>
                <div className="bg-gray-900 rounded-lg p-4 overflow-x-auto">
                  <pre className="text-green-400 text-xs">
                    {`curl -X POST https://api.example.com/api/v2/orchestrator/plan \\
  -H "X-API-Key: rm_your_api_key_here" \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "Plan a 3-day trip to Paris",
    "preferences": {
      "budget": "moderate",
      "interests": ["culture", "food"]
    }
  }'`}
                  </pre>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-6">
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
            <h3 className="font-semibold text-blue-900 mb-2 flex items-center">
              <span className="mr-2">⏱️</span>
              24-Hour Expiration
            </h3>
            <p className="text-sm text-blue-800">
              All keys expire after 1 day for security. Create a new key when
              needed.
            </p>
          </div>

          <div className="bg-green-50 border border-green-200 rounded-lg p-6">
            <h3 className="font-semibold text-green-900 mb-2 flex items-center">
              <span className="mr-2">⚡</span>
              10 Requests/Second
            </h3>
            <p className="text-sm text-green-800">
              Rate limited to ensure fair usage and optimal performance for all
              users.
            </p>
          </div>

          <div className="bg-purple-50 border border-purple-200 rounded-lg p-6">
            <h3 className="font-semibold text-purple-900 mb-2 flex items-center">
              <span className="mr-2">🔐</span>
              Read & Write Access
            </h3>
            <p className="text-sm text-purple-800">
              Full access to all orchestrator endpoints for travel planning.
            </p>
          </div>
        </div>

        <div className="mt-12 text-center">
          <p className="text-gray-500 text-sm">
            Need help? Check out the{" "}
            <a
              href="/docs"
              className="text-indigo-600 hover:text-indigo-800 font-semibold"
            >
              API Documentation
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
