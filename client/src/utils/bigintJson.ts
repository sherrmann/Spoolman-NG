import JSONbig from "json-bigint";

// Parse JSON while keeping integers that exceed Number.MAX_SAFE_INTEGER as strings instead of
// silently rounding them. CockroachDB's unique_rowid() primary keys exceed the safe range, and
// the rounded value made the client fetch the wrong id and 404 (issue #69). `storeAsString` leaves
// safely-representable numbers — the common serial ids on SQLite/Postgres/MariaDB — as normal JS
// numbers, so this only changes behaviour for oversized integers, and never touches the server.
const JSONBigString = JSONbig({ storeAsString: true });

export function parseJsonWithBigIntIds(text: string): unknown {
  return JSONBigString.parse(text);
}
