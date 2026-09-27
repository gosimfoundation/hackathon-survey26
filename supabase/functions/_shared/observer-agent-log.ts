// The team's own project log (build output and stderr, scrubbed by the trusted
// executor) is kept beside, not inside, the immutable result produced by the
// engine. Execute and engine are separate jobs: the engine publishes the result
// before the executor stops the project, so the ZIP is completed on download.
import { appendZipEntry, readZipEntry } from "./observer-zip.ts";

export const AGENT_LOG_BYTES = 2 * 1024 * 1024 + 65536;
export const RESULT_ARCHIVE_BYTES = 52428800;

function run(value: string) {
  if (!/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(value)) throw new Error("invalid_run");
  return value;
}
/** Written only by the job API for the executor's own claimed run. */
export const agentLogPath = (id: string) => "agent-logs/" + run(id) + "/agent-log.zip";
/** A service-written copy of the result with agent.log, served by short signed URL. */
export const resultDownloadPath = (id: string) => "agent-logs/" + run(id) + "/observer-result.zip";

export type ResultStorage = {
  download: (path: string) => Promise<Uint8Array | null>;
  upload: (path: string, data: Uint8Array) => Promise<void>;
  sign: (path: string) => Promise<string>;
};

/**
 * Returns a signed URL for the result with agent.log added, or null when the
 * run has no stored log (local sessions, older runs) so the caller keeps the
 * original result URL. The result bytes come from trusted storage only.
 */
export async function resultWithAgentLog(
  id: string,
  result: () => Promise<Uint8Array>,
  storage: ResultStorage,
): Promise<string | null> {
  const stored = await storage.download(agentLogPath(id));
  if (!stored || stored.length > AGENT_LOG_BYTES + 65536) return null;
  const log = await readZipEntry(stored, "agent.log", AGENT_LOG_BYTES * 3);
  if (!log) return null;
  const archive = await result();
  if (archive.length > RESULT_ARCHIVE_BYTES) return null;
  const merged = await appendZipEntry(archive, "agent.log", log);
  await storage.upload(resultDownloadPath(id), merged);
  return await storage.sign(resultDownloadPath(id));
}

/** Bounded GET of a signed archive URL, without forwarding credentials or following redirects. */
export async function fetchArchive(url: string, fetcher: typeof fetch = fetch): Promise<Uint8Array> {
  const response = await fetcher(url, { redirect: "error", signal: AbortSignal.timeout(30000) });
  if (!response.ok || !response.body) {
    await response.body?.cancel();
    throw new Error("result_download_failed");
  }
  const reader = response.body.getReader();
  const parts: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > RESULT_ARCHIVE_BYTES) throw new Error("result_too_large");
      parts.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
  const out = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.byteLength;
  }
  return out;
}
