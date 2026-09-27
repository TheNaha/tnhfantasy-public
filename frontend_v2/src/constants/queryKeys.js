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
