/**
 * Apply one write to many spools, a few at a time (#412).
 *
 * There is no bulk endpoint, on purpose: `/api/v1` stays what upstream serves, and the per-spool
 * wrappers in spoolSource already update the cache and the list exactly as a single edit does.
 * The concurrency bound is the part that matters: archiving 200 spools should not open 200
 * requests at once against a SQLite install that serialises the writes anyway.
 */
export interface BulkResult {
	ok: number[];
	failed: { id: number; error: unknown }[];
}

export async function bulkApply(
	ids: readonly number[],
	write: (id: number) => Promise<unknown>,
	{ concurrency = 4 }: { concurrency?: number } = {}
): Promise<BulkResult> {
	const result: BulkResult = { ok: [], failed: [] };
	let next = 0;
	async function worker(): Promise<void> {
		while (next < ids.length) {
			const id = ids[next++];
			try {
				await write(id);
				result.ok.push(id);
			} catch (error) {
				result.failed.push({ id, error });
			}
		}
	}
	const workers = Array.from({ length: Math.min(Math.max(1, concurrency), ids.length) }, worker);
	await Promise.all(workers);
	return result;
}
