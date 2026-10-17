const DEFAULT_BASE_URL = "https://api.nessieisreal.com";

export class NessieApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "NessieApiError";
  }
}

export type NessieClientOptions = {
  apiKey: string;
  baseUrl?: string;
  timeoutMs?: number;
};

export class NessieClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(private readonly options: NessieClientOptions) {
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, "");
    this.timeoutMs = options.timeoutMs ?? 10_000;
  }

  async get<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }

  async post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  async put<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>("PUT", path, body);
  }

  async delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    url.searchParams.set("key", this.options.apiKey);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(url, {
        method,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });

      const text = await response.text();
      let data: unknown = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }

      if (!response.ok) {
        throw new NessieApiError(`Nessie request failed with status ${response.status}`, response.status, data);
      }

      return data as T;
    } catch (error) {
      if (error instanceof NessieApiError) {
        throw error;
      }
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new NessieApiError("Nessie request timed out", 408);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
}