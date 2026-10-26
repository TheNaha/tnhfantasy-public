/**
 * The World Vault cache namespaces, and ONLY those.
 *
 * Every member here is safe to write as `buildQueryKey(QUERY_KEYS.X)` because
 * every World Vault query actually hangs off `['world_vault', …]`. Anything the
 * vault does not own — the gallery, providers, settings, statistics, models —
 * lives under its own string namespace and must be written as a literal; see
 * `invalidateVaultAggregates` for the boundary.
 *
 * Six members used to be here with zero readers: `EXPRESSIONS`, `BRANCHES`,
 * `GALLERY`, `PROVIDERS`, `SETTINGS`, `STATISTICS`. They are deleted rather than
 * renamed, because `buildQueryKey` unconditionally prepends `world_vault`, so
 * each of them could only ever produce a key that matches no query in the app —
 * and four of them (`GALLERY`, `PROVIDERS`, `SETTINGS`, `STATISTICS`) collided
 * *in name* with a real non-vault namespace, so a reader who reached for
 * `buildQueryKey(QUERY_KEYS.GALLERY)` to "find the gallery key" would get
 * `['world_vault','gallery',…]`, which prefix-matches nothing, and would see a
 * no-op invalidation with no error. A member here must name a query that exists
 * under `['world_vault', …]`; if it does not, it does not belong in this table.
 *
 * `src/test/vaultQueryKeyInvariants.test.js` enforces both halves of that.
 */
export const QUERY_KEYS = {
    WORLD_VAULT: 'world_vault',
    CHARACTERS: 'characters',
    CHATS: 'chats',
    MESSAGES: 'messages',
    STORIES: 'stories',
    LOREBOOKS: 'lorebooks',
    SCENARIOS: 'scenarios',
    VOICES: 'voices',
    VOICE_PRESETS: 'voice_presets',
    MEMORIES: 'memories',
    LOCATIONS: 'locations',
    WORLDS: 'worlds',
    SEARCH: 'search',
    MODELS: 'models',
    PERSONAS: 'personas',
    ENTITY: 'entity',
    DASHBOARD: 'dashboard',
    RELATIONSHIPS: 'relationships',
    GRAPH_LAYOUT: 'graph-layout',
    GRAPH_EDGES: 'graph-edges',
    TIMELINE: 'timeline',
    AGENTS: 'agents',
};

export const buildQueryKey = (...parts) => {
    return [QUERY_KEYS.WORLD_VAULT, ...parts];
};

/**
 * The installed-model list, as one key.
 *
 * The picker inside the generators and the Model Manager tab are the same list
 * from the same endpoint (`filesApi.list`) with the same filters. They used to
 * live under `['models', …]` and `['installed-models', …]` respectively, which
 * made them two independent caches of one thing: a resync or a metadata edit
 * that invalidated only one of them left the other showing pre-edit names, tags
 * and stats, and since `refetchOnWindowFocus` is off globally the staleness was
 * not time-bounded. Four call sites had grown a `MODEL_LIST_QUERY_KEYS` array to
 * remember to invalidate both. One key removes the class of bug.
 *
 * `pageSize` is part of the key because it drives the offset cursor in
 * `getNextPageParam`: changing it with the key unchanged made the next page
 * skip or repeat rows.
 */
export function modelListKey({
    directory,
    search = '',
    sortBy = 'name_asc',
    baseModel = 'all',
    modelType = 'all',
    showNSFW = true,
    selectedTags = [],
    pageSize = 50,
} = {}) {
    return [
        QUERY_KEYS.MODELS,
        'list',
        directory ?? null,
        search,
        sortBy,
        baseModel,
        modelType,
        showNSFW,
        // Sorted so that a set built in a different order is the same key.
        [...selectedTags].sort().join(','),
        pageSize,
    ];
}
