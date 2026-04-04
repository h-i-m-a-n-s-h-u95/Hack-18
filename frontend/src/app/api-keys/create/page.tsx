// app/api-keys/create/page.tsx
"use client";

import { useState } from "react";
import { APIKeyService } from "@/lib/api-key";
import type { CreateAPIKeyResponse } from "@/lib/api-key";

export default function CreateAPIKeyPage() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiKeyResponse, setApiKeyResponse] =
    useState<CreateAPIKeyResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      setError("Name is required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await APIKeyService.createAPIKey({
        name: name.trim(),
        description: description.trim() || undefined,
        expires_in_days: 1, // Fixed 1 day expiration
        rate_limit_qps: 10.0,
        scopes: ["read", "write"],
      });

      setApiKeyResponse(response);
      setName("");
      setDescription("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create API key");
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async () => {
    if (apiKeyResponse?.api_key) {
      await navigator.clipboard.writeText(apiKeyResponse.api_key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "Never";
    return new Date(dateStr).toLocaleString();
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-2xl mx-auto">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">
            🔑 Create API Key
          </h1>
          <p className="text-gray-600">
            Generate a 24-hour API key for Ringmaster Round Table
          </p>
        </div>

        {!apiKeyResponse ? (
          <div className="bg-white rounded-lg shadow-lg p-8">
            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label
                  htmlFor="name"
                  className="block text-sm font-medium text-gray-700 mb-2"
                >
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., John's Travel Planner"
                  maxLength={100}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition"
                  disabled={loading}
                />
              </div>

              <div>
                <label
                  htmlFor="description"
                  className="block text-sm font-medium text-gray-700 mb-2"
                >
                  Description (Optional)
                </label>
                <textarea
                  id="description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What will you use this key for?"
                  maxLength={500}
                  rows={3}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition resize-none"
                  disabled={loading}
                />
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-blue-900 mb-2">
                  Key Details
                </h3>
                <ul className="text-sm text-blue-800 space-y-1">
                  <li>
                    ⏱️ <strong>Expiration:</strong> 24 hours (1 day)
                  </li>
                  <li>
                    ⚡ <strong>Rate Limit:</strong> 10 requests/second
                  </li>
                  <li>
                    🔐 <strong>Permissions:</strong> Read & Write
                  </li>
                </ul>
              </div>

              {error && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                  <p className="text-sm text-red-800">❌ {error}</p>
                </div>
              )}

              <button
                type="submit"
                disabled={loading || !name.trim()}
                className="w-full bg-indigo-600 text-white py-3 px-4 rounded-lg font-semibold hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
              >
                {loading ? (
                  <span className="flex items-center justify-center">
                    <svg
                      className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      ></circle>
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      ></path>
                    </svg>
                    Creating...
                  </span>
                ) : (
                  "Generate API Key"
                )}
              </button>
            </form>
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow-lg p-8">
            <div className="text-center mb-6">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
                <svg
                  className="w-8 h-8 text-green-600"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              </div>
              <h2 className="text-2xl font-bold text-gray-900 mb-2">
                API Key Created Successfully!
              </h2>
              <p className="text-gray-600">
                ⚠️ Save this key now - it won&apos;t be shown again
              </p>
            </div>

            <div className="space-y-4">
              <div className="bg-gray-50 rounded-lg p-4 border-2 border-dashed border-gray-300">
                <label className="block text-xs font-semibold text-gray-700 mb-2 uppercase tracking-wide">
                  Your API Key
                </label>
                <div className="flex gap-2">
                  <code className="flex-1 bg-white px-4 py-3 rounded border border-gray-300 text-sm font-mono break-all">
                    {apiKeyResponse.api_key}
                  </code>
                  <button
                    onClick={handleCopy}
                    className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 transition flex-shrink-0"
                  >
                    {copied ? "✓ Copied" : "📋 Copy"}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Key ID</p>
                  <p className="text-sm font-mono text-gray-900">
                    {apiKeyResponse.key_id}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Name</p>
                  <p className="text-sm font-semibold text-gray-900">
                    {apiKeyResponse.name}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Created At</p>
                  <p className="text-sm text-gray-900">
                    {formatDate(apiKeyResponse.created_at)}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Expires At</p>
                  <p className="text-sm text-red-600 font-semibold">
                    {formatDate(apiKeyResponse.expires_at)}
                  </p>
                </div>
              </div>

              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-yellow-900 mb-2">
                  ⚠️ Important
                </h3>
                <ul className="text-sm text-yellow-800 space-y-1">
                  <li>• This key will be shown only once</li>
                  <li>• Store it securely (e.g., password manager)</li>
                  <li>• Include it in X-API-Key header for requests</li>
                  <li>• Key expires in 24 hours</li>
                </ul>
              </div>

              <div className="bg-gray-50 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-gray-900 mb-2">
                  Usage Example
                </h3>
                <pre className="text-xs bg-gray-900 text-green-400 p-3 rounded overflow-x-auto">
                  {`curl -X POST https://api.example.com/api/v2/orchestrator/plan \\
  -H "X-API-Key: ${apiKeyResponse.api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "Plan a trip to Paris"}'`}
                </pre>
              </div>

              <button
                onClick={() => {
                  setApiKeyResponse(null);
                  setError(null);
                }}
                className="w-full bg-gray-600 text-white py-3 px-4 rounded-lg font-semibold hover:bg-gray-700 transition"
              >
                Create Another Key
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
