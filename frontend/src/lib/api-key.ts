// lib/types/api-key.ts
export interface CreateAPIKeyRequest {
  name: string;
  description?: string;
  expires_in_days?: number;
  rate_limit_qps?: number;
  scopes?: string[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metadata?: Record<string, any>;
}

export interface CreateAPIKeyResponse {
  api_key: string;
  key_id: string;
  name: string;
  created_at: string;
  expires_at: string | null;
  rate_limit_qps: number;
  scopes: string[];
}

export interface APIKeyInfo {
  key_id: string;
  name: string;
  description?: string;
  created_at: string;
  created_by?: string;
  last_used_at?: string;
  expires_at?: string;
  status: string;
  total_requests: number;
  rate_limit_qps: number;
  scopes: string[];
}

// lib/api/api-keys.ts
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class APIKeyService {
  private static getHeaders() {
    const adminKey = process.env.NEXT_PUBLIC_ADMIN_API_KEY;
    if (!adminKey) {
      throw new Error("Admin API key not configured");
    }
    return {
      "Content-Type": "application/json",
      "X-API-Key": adminKey,
    };
  }

  static async createAPIKey(
    data: CreateAPIKeyRequest
  ): Promise<CreateAPIKeyResponse> {
    const response = await fetch(`${API_BASE_URL}/api/v1/keys`, {
      method: "POST",
      headers: this.getHeaders(),
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const error = await response
        .json()
        .catch(() => ({ detail: "Failed to create API key" }));
      throw new Error(error.detail || "Failed to create API key");
    }

    return response.json();
  }

  static async getMyKeyInfo(apiKey: string): Promise<APIKeyInfo> {
    const response = await fetch(`${API_BASE_URL}/api/v1/keys/me`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
    });

    if (!response.ok) {
      const error = await response
        .json()
        .catch(() => ({ detail: "Failed to fetch key info" }));
      throw new Error(error.detail || "Failed to fetch key info");
    }

    return response.json();
  }
}
