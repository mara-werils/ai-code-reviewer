import * as https from "https";
import * as http from "http";

/** Configuration for the LLM provider. */
export interface LLMConfig {
  provider: string;
  model: string;
  apiKey: string;
  apiBaseUrl: string;
}

/** Structured response from the LLM. */
export interface LLMResponse {
  content: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  model: string;
}

/** Pricing per 1M tokens [input, output]. */
const PRICING: Record<string, [number, number]> = {
  "gpt-4o": [2.5, 10],
  "gpt-4o-mini": [0.15, 0.6],
  "claude-sonnet-4-20250514": [3, 15],
  "claude-haiku-4-5-20251001": [0.8, 4],
  "llama-3.3-70b-versatile": [0.059, 0.079],
  "gemini-2.0-flash": [0.075, 0.3],
};

const MODEL_DEFAULTS: Record<string, string> = {
  openai: "gpt-4o",
  anthropic: "claude-sonnet-4-20250514",
  groq: "llama-3.3-70b-versatile",
  google: "gemini-2.0-flash",
  ollama: "llama3.1:8b",
};

function resolveApiKey(config: LLMConfig): string {
  if (config.apiKey) {
    return config.apiKey;
  }
  const envMap: Record<string, string> = {
    openai: "OPENAI_API_KEY",
    anthropic: "ANTHROPIC_API_KEY",
    groq: "GROQ_API_KEY",
    google: "GOOGLE_API_KEY",
  };
  const envVar = envMap[config.provider];
  return envVar ? process.env[envVar] ?? "" : "";
}

function resolveBaseUrl(config: LLMConfig): string {
  if (config.apiBaseUrl) {
    return config.apiBaseUrl;
  }
  const defaults: Record<string, string> = {
    openai: "https://api.openai.com/v1",
    groq: "https://api.groq.com/openai/v1",
    ollama: "http://localhost:11434/v1",
    google: "https://generativelanguage.googleapis.com/v1beta/openai",
  };
  return defaults[config.provider] ?? "https://api.openai.com/v1";
}

function estimateCost(
  model: string,
  inputTokens: number,
  outputTokens: number
): number {
  const pricing = PRICING[model];
  if (!pricing) {
    return 0;
  }
  const [inputPrice, outputPrice] = pricing;
  return (inputTokens * inputPrice + outputTokens * outputPrice) / 1_000_000;
}

/** Sends a chat completion request (OpenAI-compatible API). */
export async function chatCompletion(
  config: LLMConfig,
  messages: Array<{ role: string; content: string }>,
  options: { temperature?: number; maxTokens?: number; jsonMode?: boolean } = {}
): Promise<LLMResponse> {
  const apiKey = resolveApiKey(config);
  const model = config.model || MODEL_DEFAULTS[config.provider] || "gpt-4o";

  // Anthropic uses a different API format
  if (config.provider === "anthropic") {
    return anthropicCompletion(apiKey, model, messages, options);
  }

  const baseUrl = resolveBaseUrl(config);
  const url = `${baseUrl}/chat/completions`;

  const body: Record<string, unknown> = {
    model,
    messages,
    temperature: options.temperature ?? 0.1,
    max_tokens: options.maxTokens ?? 4096,
  };

  if (options.jsonMode) {
    body.response_format = { type: "json_object" };
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (apiKey) {
    headers["Authorization"] = `Bearer ${apiKey}`;
  }

  const responseData = await httpRequest(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  const data = JSON.parse(responseData);
  const content = data.choices?.[0]?.message?.content ?? "";
  const inputTokens = data.usage?.prompt_tokens ?? 0;
  const outputTokens = data.usage?.completion_tokens ?? 0;

  return {
    content,
    inputTokens,
    outputTokens,
    costUsd: estimateCost(model, inputTokens, outputTokens),
    model,
  };
}

async function anthropicCompletion(
  apiKey: string,
  model: string,
  messages: Array<{ role: string; content: string }>,
  options: { temperature?: number; maxTokens?: number }
): Promise<LLMResponse> {
  const url = "https://api.anthropic.com/v1/messages";

  // Extract system message
  const systemMsg = messages.find((m) => m.role === "system");
  const userMessages = messages.filter((m) => m.role !== "system");

  const body: Record<string, unknown> = {
    model,
    max_tokens: options.maxTokens ?? 4096,
    temperature: options.temperature ?? 0.1,
    messages: userMessages,
  };
  if (systemMsg) {
    body.system = systemMsg.content;
  }

  const responseData = await httpRequest(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify(body),
  });

  const data = JSON.parse(responseData);
  const content =
    data.content?.map((c: { text: string }) => c.text).join("") ?? "";
  const inputTokens = data.usage?.input_tokens ?? 0;
  const outputTokens = data.usage?.output_tokens ?? 0;

  return {
    content,
    inputTokens,
    outputTokens,
    costUsd: estimateCost(model, inputTokens, outputTokens),
    model,
  };
}

/** Simple HTTP request using Node built-ins (no dependencies needed). */
function httpRequest(
  url: string,
  options: {
    method: string;
    headers: Record<string, string>;
    body: string;
  }
): Promise<string> {
  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const lib = parsedUrl.protocol === "https:" ? https : http;

    const req = lib.request(
      {
        hostname: parsedUrl.hostname,
        port: parsedUrl.port,
        path: parsedUrl.pathname + parsedUrl.search,
        method: options.method,
        headers: {
          ...options.headers,
          "Content-Length": Buffer.byteLength(options.body),
        },
        timeout: 120_000,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk: Buffer) => chunks.push(chunk));
        res.on("end", () => {
          const body = Buffer.concat(chunks).toString("utf-8");
          if (res.statusCode && res.statusCode >= 400) {
            reject(
              new Error(
                `HTTP ${res.statusCode}: ${body.substring(0, 500)}`
              )
            );
          } else {
            resolve(body);
          }
        });
      }
    );

    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("Request timed out (120s)"));
    });
    req.write(options.body);
    req.end();
  });
}
