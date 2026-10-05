import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Search, Filter, Users, MessageSquare, BookOpen, Music, Shield, Tag, Globe, MapPin } from 'lucide-react';
import toast from 'react-hot-toast';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    useWorldVaultSearch,
    useWorldVaultDashboard,
    useWorldVaultEntity,
    WORLD_VAULT_MENTION_TYPES,
    WORLD_VAULT_SEARCH_MIN_LENGTH,
} from '../hooks/useWorldVaultSearch';
import { useDebounce } from '../hooks/useDebounce';
import RoleplayPageShell from '../components/RoleplayPageShell';
import { QueryErrorState } from '../components/common/QueryState';

const ENTITY_ICONS = {
    character: Users,
    chat: MessageSquare,
    story: BookOpen,
    voice: Music,
    lorebook: Shield,
    scenario: Tag,
    memory: Tag,
    location: MapPin,
};

const ENTITY_COLORS = {
    character: 'text-purple-400 bg-purple-500/20',
    chat: 'text-blue-400 bg-blue-500/20',
    story: 'text-amber-400 bg-amber-500/20',
    voice: 'text-pink-400 bg-pink-500/20',
    lorebook: 'text-emerald-400 bg-emerald-500/20',
    scenario: 'text-cyan-400 bg-cyan-500/20',
    memory: 'text-indigo-400 bg-indigo-500/20',
    location: 'text-amber-400 bg-amber-500/20',
};

// Where each entity type the unified search can emit actually lives. The list
// is exactly the set of `_add(...)` calls in
// backend_v2/api/routes/world_vault/world_hub.py: character, story, chat,
// lorebook, location, scenario, voice, memory (handled separately, below).
// The previous switch also carried `persona`, `branch` and `campaign` branches
// that the backend never emits.
const ENTITY_ROUTES = {
    character: (id) => `/characters#char-${id}`,
    chat: (id) => `/chat/${id}`,
    story: (id) => `/story/${id}`,
    // These list pages have no per-entity anchor, so they land on the list.
    lorebook: () => '/lorebooks',
    location: () => '/locations',
    scenario: () => '/scenarios',
    voice: () => '/voices',
};

const ENTITY_TYPE_FILTERS = ['all', 'character', 'chat', 'story', 'voice', 'lorebook', 'location', 'scenario', 'memory'];

// `/world-vault?character=<id>` and its lorebook/location siblings are what
// StoryEditor writes into chapter prose for every @mention. The parameters used
// to be ignored entirely, so each mention link dropped the user on an unfiltered
// hub. Not memoised: it reads three keys off an object that is already stable,
// and the React Compiler memoises it for us.
function readMention(searchParams) {
    for (const type of WORLD_VAULT_MENTION_TYPES) {
        const id = searchParams.get(type);
        if (id) return { type, id };
    }
    return null;
}

export default function WorldVaultHub() {
    const [searchParams] = useSearchParams();
    const mention = readMention(searchParams);

    const [searchQuery, setSearchQuery] = useState('');
    const [selectedType, setSelectedType] = useState(() => mention?.type || 'all');
    const [mentionTypeAtLastSync, setMentionTypeAtLastSync] = useState(mention?.type);
    const debouncedQuery = useDebounce(searchQuery, 300);
    const navigate = useNavigate();

    // A mention link also narrows the type filter, so a search typed after
    // landing stays scoped to what the story was pointing at. `/world-vault` does
    // not remount on a query-string change, so the filter has to be adjusted when
    // the URL does — during render, which is what React asks for instead of an
    // effect (an effect here would cascade a render on every mention change).
    if (mention && mention.type !== mentionTypeAtLastSync) {
        setMentionTypeAtLastSync(mention.type);
        setSelectedType(mention.type);
    }

    // `isError` is load-bearing, not decoration. Both queries used to destructure
    // only `{data, isLoading}`, so a failed fetch left `displayResults` empty
    // and the page rendered "No entities yet" / "No results found" — an outage
    // reported as an empty vault, with no retry and no way to tell the two apart.
    // That is the eleventh file to do this; see `docs/audit-2026-10-05.md`.
    const entitiesQuery = useWorldVaultDashboard();
    const { data: entities, isLoading: entitiesLoading } = entitiesQuery;
    const trimmedQuery = debouncedQuery.trim();
    // One character is below the backend's `min_length=2` and would 422; the
    // search hook stays disabled, so the hub must not present it as an
    // empty-result search either.
    const isSearchActive = trimmedQuery.length >= WORLD_VAULT_SEARCH_MIN_LENGTH;
    const searchResultsQuery = useWorldVaultSearch(trimmedQuery, selectedType !== 'all' ? selectedType : null);
    const { data: searchResults, isLoading: searchLoading } = searchResultsQuery;

    const isLoading = entitiesLoading || searchLoading;
    const failedQuery = entitiesQuery.isError
        ? entitiesQuery
        : (searchResultsQuery.isError ? searchResultsQuery : null);
    const RECENT_TYPE_KEYS = { characters: 'character', chats: 'chat', stories: 'story' };
    const displayResults = isSearchActive
        ? (searchResults?.results || [])
        : Object.entries(entities?.recent || {}).flatMap(([key, items]) =>
              items.map((item) => ({ ...item, type: RECENT_TYPE_KEYS[key] || key }))
          );

    const openEntity = (entity) => {
        const id = entity.id ?? entity.entity_id;
        if (entity.type === 'memory') {
            // Memories are content, not pages: send the user to the character
            // that remembers it, falling back to the character list.
            navigate(entity.character_id ? `/characters#char-${entity.character_id}` : '/characters');
            return;
        }
        const route = ENTITY_ROUTES[entity.type];
        if (!route) {
            // Never fall back to /world-vault: that is the page you are already
            // on, so the row would look broken rather than unroutable.
            toast.error(`There is no page for ${entity.type || 'this kind of'} entity yet.`);
            return;
        }
        navigate(route(id));
    };

    return (
        <RoleplayPageShell
            title="World Vault"
            description="Central hub for all your fantasy entities — characters, chats, stories, voices, and more."
            icon={Globe}
        >

            <div className="flex gap-4 mb-6">
                <div className="flex-1 relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                    <input
                        type="text"
                        aria-label="Search the world vault" placeholder="Search across all entities..."
                        className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                </div>
                <select
                    value={selectedType}
                    onChange={(e) => setSelectedType(e.target.value)}
                    className="px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                    {ENTITY_TYPE_FILTERS.map((type) => (
                        <option key={type} value={type}>
                            {type.charAt(0).toUpperCase() + type.slice(1)}
                        </option>
                    ))}
                </select>
            </div>

            {/* Below the backend's `min_length=2` the search hook stays idle, so
                say so rather than letting a one-character query look like an
                empty result set. */}
            {!isSearchActive && Boolean(trimmedQuery) && (
                <p className="-mt-3 mb-6 text-sm text-gray-500">
                    Type at least {WORLD_VAULT_SEARCH_MIN_LENGTH} characters to search.
                </p>
            )}

            {mention && <MentionTarget mention={mention} onOpen={openEntity} />}

            {entities && (
                <div className="mb-6">
                    <h2 className="text-lg font-semibold text-gray-300 mb-3">Entity Counts</h2>
                    {/* `grid-cols-3` below `sm`, not `grid-cols-4`: at 360px
                        four columns of `p-3` cards is 69px each, and the longest
                        keys need more than that. Measured overflow into the
                        *neighbouring card* (`overflow` is `visible`, so the text
                        painted over the next card's border): `lorebook_entries`
                        needed 98px (+55), `characters` +18, `memories` +14,
                        `locations`/`scenarios` +11, `lorebooks` +16.
                        `break-words` on the label handles the rest. */}
                    <div className="grid grid-cols-3 sm:grid-cols-8 gap-3">
                        {Object.entries(entities.counts || {}).map(([key, count]) => {
                            const Icon = ENTITY_ICONS[key] || Tag;
                            return (
                                <motion.div
                                    key={key}
                                    className="bg-gray-900 border border-gray-700 rounded-xl p-3 text-center"
                                >
                                    <div className={`inline-flex p-2 rounded-lg mb-1 ${ENTITY_COLORS[key] || 'text-gray-400 bg-gray-700'}`}>
                                        <Icon size={18} />
                                    </div>
                                    <div className="text-2xl font-bold text-white">{count}</div>
                                    <div className="text-xs text-gray-400 capitalize break-words hyphens-auto">{key}</div>
                                </motion.div>
                            );
                        })}
                    </div>
                </div>
            )}

            {isLoading && <div className="text-gray-400">Loading...</div>}

            {!isLoading && failedQuery && (
                <QueryErrorState
                    noun={isSearchActive ? 'search results' : 'world vault entities'}
                    error={failedQuery.error}
                    onRetry={failedQuery.refetch}
                />
            )}

            {!isLoading && !failedQuery && displayResults.length === 0 && (
                <div className="text-center py-12 text-gray-500">
                    {isSearchActive ? 'No results found' : 'No entities yet'}
                </div>
            )}

            {!isLoading && !failedQuery && displayResults.length > 0 && (
                <div className="space-y-3">
                    {displayResults.map((entity, i) => {
                        const Icon = (ENTITY_ICONS[entity.type] || Tag);
                        const colorClass = ENTITY_COLORS[entity.type] || 'text-gray-400 bg-gray-700';
                        return (
                            <motion.div
                                key={entity.id || i}
                                role="button"
                                tabIndex={0}
                                onClick={() => openEntity(entity)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        openEntity(entity);
                                    }
                                }}
                                className="bg-gray-900 border border-gray-700 rounded-xl p-4 flex items-center gap-4 cursor-pointer hover:border-gray-500 transition-colors"
                            >
                                <div className={`p-2 rounded-lg ${colorClass}`}>
                                    <Icon size={20} />
                                </div>
                                <div className="flex-1">
                                    <h3 className="font-medium text-white">{entity.name || entity.title}</h3>
                                    {entity.type && (
                                        <span className="text-xs text-gray-500 capitalize">{entity.type}</span>
                                    )}
                                    {(entity.description || entity.content || entity.subtitle) && (
                                        <p className="text-sm text-gray-400 mt-1 line-clamp-2">
                                            {entity.description || entity.content || entity.subtitle}
                                        </p>
                                    )}
                                </div>
                            </motion.div>
                        );
                    })}
                </div>
            )}
        </RoleplayPageShell>
    );
}

/**
 * The entity a story @mention points at. Search matches on names, so the id in
 * the URL cannot be resolved through the search endpoint — it is fetched
 * directly and shown above the results, which is what makes a mention link in
 * chapter prose land on the thing it names instead of an unfiltered hub.
 */
function MentionTarget({ mention, onOpen }) {
    const { data: entity, isLoading, isError } = useWorldVaultEntity(mention.type, mention.id);
    const Icon = ENTITY_ICONS[mention.type] || Tag;
    const colorClass = ENTITY_COLORS[mention.type] || 'text-gray-400 bg-gray-700';
    const name = entity?.name || entity?.title;

    return (
        <section aria-labelledby="vault-mention-heading" className="mb-6">
            <h2 id="vault-mention-heading" className="text-lg font-semibold text-gray-300 mb-3">
                Linked from your story
            </h2>
            <button
                type="button"
                onClick={() => onOpen({ id: mention.id, type: mention.type })}
                className="w-full bg-gray-900 border border-blue-500/40 rounded-xl p-4 flex items-center gap-4 text-left hover:border-blue-400 transition-colors"
            >
                <div className={`p-2 rounded-lg ${colorClass}`}>
                    <Icon size={20} />
                </div>
                <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-white truncate">
                        {isLoading
                            ? `Loading ${mention.type}…`
                            : name || `${mention.type} ${String(mention.id).slice(0, 8)}…`}
                    </h3>
                    <span className="text-xs text-gray-500 capitalize">{mention.type}</span>
                    {entity?.description && (
                        <p className="text-sm text-gray-400 mt-1 line-clamp-2">{entity.description}</p>
                    )}
                    {isError && (
                        <p className="text-sm text-amber-400/80 mt-1">
                            This one could not be loaded — opening its library instead.
                        </p>
                    )}
                </div>
            </button>
        </section>
    );
}
