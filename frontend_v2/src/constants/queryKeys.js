export const QUERY_KEYS = {
    WORLD_VAULT: 'world_vault',
    CHARACTERS: 'characters',
    CHATS: 'chats',
    MESSAGES: 'messages',
    STORIES: 'stories',
    LOREBOOKS: 'lorebooks',
    SCENARIOS: 'scenarios',
    VOICES: 'voices',
    MEMORIES: 'memories',
    EXPRESSIONS: 'expressions',
    BRANCHES: 'branches',
    LOCATIONS: 'locations',
    SEARCH: 'search',
    GALLERY: 'gallery',
    MODELS: 'models',
    PROVIDERS: 'providers',
    SETTINGS: 'settings',
    STATISTICS: 'statistics',
    PERSONAS: 'personas',
    ENTITY: 'entity',
    DASHBOARD: 'dashboard',
    RELATIONSHIPS: 'relationships',
    GRAPH_LAYOUT: 'graph-layout',
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
