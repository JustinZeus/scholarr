const SCHOLAR_ID_PATTERN = /^[a-zA-Z0-9_-]{12}$/;

export interface ParsedToken {
  index: number;
  raw: string;
  id: string | null;
  error: string | null;
}

export function extractScholarIdFromUrl(token: string): string | null {
  const cleaned = token.replace(/\/+$/, "").replace(/#.*$/, "");
  try {
    const parsed = new URL(cleaned);
    const userParam = parsed.searchParams.get("user");
    if (!userParam) return null;
    const decoded = decodeURIComponent(userParam).trim();
    if (SCHOLAR_ID_PATTERN.test(decoded)) return decoded;
    return null;
  } catch {
    return null;
  }
}

export function validateTokenAsId(token: string): string | null {
  const trimmed = token.trim();
  if (!trimmed) return "empty input";
  if (/\s/.test(trimmed)) return "contains whitespace";
  if (trimmed.length !== 12) return `must be 12 characters (got ${trimmed.length})`;
  if (!/^[a-zA-Z0-9_-]+$/.test(trimmed)) {
    return "contains invalid characters (only a-z, A-Z, 0-9, _ and - allowed)";
  }
  return null;
}

export function parseScholarTokens(raw: string): ParsedToken[] {
  const tokens = raw.split(/[\s,;]+/).map((v) => v.trim()).filter((v) => v.length > 0);
  const results: ParsedToken[] = [];
  const seen = new Set<string>();

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];

    if (SCHOLAR_ID_PATTERN.test(token)) {
      if (seen.has(token)) {
        results.push({ index: i + 1, raw: token, id: null, error: "duplicate" });
        continue;
      }
      seen.add(token);
      results.push({ index: i + 1, raw: token, id: token, error: null });
      continue;
    }

    if (token.includes("scholar.google") || token.startsWith("http")) {
      const extracted = extractScholarIdFromUrl(token);
      if (extracted) {
        if (seen.has(extracted)) {
          results.push({ index: i + 1, raw: token, id: null, error: "duplicate" });
          continue;
        }
        seen.add(extracted);
        results.push({ index: i + 1, raw: token, id: extracted, error: null });
        continue;
      }
      results.push({ index: i + 1, raw: token, id: null, error: "could not extract scholar ID from URL" });
      continue;
    }

    const reason = validateTokenAsId(token);
    results.push({ index: i + 1, raw: token, id: null, error: reason ?? "invalid scholar ID" });
  }
  return results;
}

export function parseScholarIds(raw: string): string[] {
  return parseScholarTokens(raw).filter((t) => t.id !== null).map((t) => t.id!);
}
