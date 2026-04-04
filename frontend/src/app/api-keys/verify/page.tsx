// app/api-keys/verify/page.tsx
"use client";

import { useState } from "react";
import { APIKeyService } from "@/lib/api-key";
import type { APIKeyInfo } from "@/lib/api-key";

export default function VerifyAPIKeyPage() {
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keyInfo, setKeyInfo] = useState<APIKeyInfo | null>(null);

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!apiKey.trim()) {
      setError("API key is required");
      return;
    }

    setLoading(true);
    setError(null);
    setKeyInfo(null);

    try {
      const info = await APIKeyService.getMyKeyInfo(apiKey.trim());
      setKeyInfo(info);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Invalid or expired API key"
      );
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return "Never";
    return new Date(dateStr).toLocaleString();
  };

  const getTimeRemaining = (expiresAt?: string) => {
    if (!expiresAt) return "Never expires";

    const now = new Date();
    const expiry = new Date(expiresAt);
    const diff = expiry.getTime() - now.getTime();

    if (diff <= 0) return "Expired";

    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));

    return `${hours}h ${minutes}m remaining`;
  };

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case "active":
        return "text-green-700 bg-green-100 border-green-300";
      case "expired":
        return "text-red-700 bg-red-100 border-red-300";
      case "revoked":
        return "text-gray-700 bg-gray-100 border-gray-300";
      default:
        return "text-gray-700 bg-gray-100 border-gray-300";
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-50 to-pink-100 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-2xl mx-auto">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">
            🔍 Verify API Key
          </h1>
          <p className="text-gray-600">
            Check your API key status and usage information
          </p>
        </div>

        <div className="bg-white rounded-lg shadow-lg p-8 mb-6">
          <form onSubmit={handleVerify} className="space-y-6">
            <div>
              <label
                htmlFor="apiKey"
                className="block text-sm font-medium text-gray-700 mb-2"
              >
                API Key <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="apiKey"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="rm_..."
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none transition font-mono text-sm"
                disabled={loading}
              />
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <p className="text-sm text-red-800">❌ {error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !apiKey.trim()}
              className="w-full bg-purple-600 text-white py-3 px-4 rounded-lg font-semibold hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
            >
              {loading ? "Verifying..." : "Verify Key"}
            </button>
          </form>
        </div>

        {keyInfo && (
          <div className="bg-white rounded-lg shadow-lg p-8">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-2xl font-bold text-gray-900">
                Key Information
              </h2>
              <span
                className={`px-3 py-1 rounded-full text-sm font-semibold border ${getStatusColor(
                  keyInfo.status
                )}`}
              >
                {keyInfo.status.toUpperCase()}
              </span>
            </div>

            <div className="space-y-4">
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-xs text-gray-600 mb-1">Name</p>
                <p className="text-lg font-semibold text-gray-900">
                  {keyInfo.name}
                </p>
              </div>

              {keyInfo.description && (
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Description</p>
                  <p className="text-sm text-gray-900">{keyInfo.description}</p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Key ID</p>
                  <p className="text-sm font-mono text-gray-900">
                    {keyInfo.key_id}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Total Requests</p>
                  <p className="text-2xl font-bold text-indigo-600">
                    {keyInfo.total_requests}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Created At</p>
                  <p className="text-sm text-gray-900">
                    {formatDate(keyInfo.created_at)}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-4">
                  <p className="text-xs text-gray-600 mb-1">Last Used</p>
                  <p className="text-sm text-gray-900">
                    {formatDate(keyInfo.last_used_at)}
                  </p>
                </div>
              </div>

              {keyInfo.expires_at && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                  <p className="text-xs text-yellow-700 mb-1 font-semibold">
                    Expiration
                  </p>
                  <p className="text-sm text-yellow-900 font-semibold">
                    {formatDate(keyInfo.expires_at)}
                  </p>
                  <p className="text-xs text-yellow-700 mt-1">
                    ⏱️ {getTimeRemaining(keyInfo.expires_at)}
                  </p>
                </div>
              )}

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-blue-900 mb-2">
                  Permissions & Limits
                </h3>
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-blue-800">Rate Limit:</span>
                    <span className="font-semibold text-blue-900">
                      {keyInfo.rate_limit_qps} req/sec
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-blue-800">Scopes:</span>
                    <span className="font-semibold text-blue-900">
                      {keyInfo.scopes.join(", ")}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <button
              onClick={() => {
                setKeyInfo(null);
                setApiKey("");
                setError(null);
              }}
              className="w-full mt-6 bg-gray-600 text-white py-3 px-4 rounded-lg font-semibold hover:bg-gray-700 transition"
            >
              Check Another Key
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
