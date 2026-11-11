// services/aiClient.js  -- tiny wrapper around the Python AI service
const AI_URL = process.env.AI_SERVICE_URL ?? "http://127.0.0.1:8001";

export class AiServiceError extends Error {
    constructor(message, statusCode = 502) {
        super(message);
        this.statusCode = statusCode;
    }
}

export async function aiPost(path, body) {
    let res;
    try {
        res = await fetch(`${AI_URL}${path}`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-API-Key": process.env.AI_SERVICE_KEY },
            body: JSON.stringify(body),
            signal: AbortSignal.timeout(120_000),
        });
    } catch (err) {
        throw new AiServiceError(`AI service unreachable: ${err.message}`);
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new AiServiceError(data.error ?? data.detail ?? "AI service error", res.status === 422 ? 422 : 502);
    return data;
}
