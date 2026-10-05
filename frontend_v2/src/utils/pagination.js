/**
 * Termination rules for offset-paginated `GET /api/files` listings.
 *
 * Two components page the same endpoint and disagreed about when to stop.
 * `ModelSelector` stopped on `lastPage.files?.length === 50` — a hard-coded
 * page size, so a page that came back short for any reason other than
 * exhaustion ended the list, and `total` was never consulted. `InstalledTab`
 * stopped on `length >= itemsPerPage && loaded < total`, which is total-aware
 * but truncates the moment the server returns fewer rows than `limit` while more
 * remain. Neither could tell "the server has nothing more" from "the server gave
 * me fewer rows than I asked for", and the two answers were different rules in
 * two files.
 *
 * `nextOffsetPageParam` is the one rule. It uses `total` when the server sends
 * it (`GET /api/files` always does, alongside `files`) and copes without it when
 * it does not, and it terminates on an empty page rather than on a short one,
 * because a short page is a statement about *this* request, not about the end of
 * the list.
 *
 * The next offset is how many rows are already in hand. A `pageSize` argument
 * would be ignored, and an ignored argument is how the two rules stayed
 * different: the old ones compared against it, so passing it invites writing a
 * comparison against it again.
 */
export function nextOffsetPageParam(lastPage, allPages) {
    const rows = Array.isArray(lastPage?.files) ? lastPage.files.length : 0;
    if (rows === 0) return undefined;

    const loaded = (allPages ?? []).reduce(
        (sum, page) => sum + (Array.isArray(page?.files) ? page.files.length : 0),
        0
    );

    const total = Number(lastPage?.total);
    if (Number.isFinite(total) && total > 0 && loaded >= total) return undefined;

    // `Math.max` so the cursor always advances past the rows just received: an
    // offset equal to the previous one refetches the same page forever.
    return Math.max(loaded, rows);
}

export default nextOffsetPageParam;