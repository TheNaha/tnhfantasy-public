import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Search, Filter, Users, MessageSquare, BookOpen, Music, Shield, Tag, Globe } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useWorldVaultSearch, useWorldVaultDashboard } from '../hooks/useWorldVaultSearch';
import { useDebounce } from '../hooks/useDebounce';
import RoleplayPageShell from '../components/RoleplayPageShell';

const ENTITY_ICONS = {
    character: Users,
    chat: MessageSquare,
    story: BookOpen,
    voice: Music,
    lorebook: Shield,
    scenario: Tag,
    memory: Tag,
    branch: Tag,
};

const ENTITY_COLORS = {
    character: 'text-purple-400 bg-purple-500/20',
    chat: 'text-blue-400 bg-blue-500/20',
    story: 'text-amber-400 bg-amber-500/20',
    voice: 'text-pink-400 bg-pink-500/20',
    lorebook: 'text-emerald-400 bg-emerald-500/20',
    scenario: 'text-cyan-400 bg-cyan-500/20',
    memory: 'text-indigo-400 bg-indigo-500/20',
    branch: 'text-yellow-400 bg-yellow-500/20',
};

export default function WorldVaultHub() {
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedType, setSelectedType] = useState('all');
    const debouncedQuery = useDebounce(searchQuery, 300);
    const navigate = useNavigate();

    const { data: entities, isLoading: entitiesLoading } = useWorldVaultDashboard();
    const { data: searchResults, isLoading: searchLoading } = useWorldVaultSearch(debouncedQuery, selectedType !== 'all' ? selectedType : null);

    const isLoading = entitiesLoading || searchLoading;
    const RECENT_TYPE_KEYS = { characters: 'character', chats: 'chat', stories: 'story' };
    const displayResults = debouncedQuery
        ? (searchResults?.results || [])
        : Object.entries(entities?.recent || {}).flatMap(([key, items]) =>
              items.map((item) => ({ ...item, type: RECENT_TYPE_KEYS[key] || key }))
          );

    const openEntity = (entity) => {
        const id = entity.id ?? entity.entity_id;
        switch (entity.type) {
            case 'chat':
                navigate(`/chat/${id}`);
                break;
            case 'story':
                navigate(`/story/${id}`);
                break;
            case 'character':
                navigate(`/characters#char-${id}`);
                break;
            case 'memory':
                // Deep-link to the character if the search result includes character_id
                if (entity.character_id) {
                    navigate(`/characters#char-${entity.character_id}`);
                } else {
                    navigate(`/characters`);
                }
                break;
            case 'location':
            case 'campaign':
            case 'lorebook':
            case 'scenario':
            case 'persona':
            case 'voice':
                // Navigate to the entity list page (deep-link support pending on target page)
                navigate(`/${entity.type}s`);
                break;
            case 'branch':
                navigate(`/chat/${entity.chat_id || id}`);
                break;
            default:
                navigate('/world-vault');
        }
    };

    const entityTypes = [
        'all', 'character', 'chat', 'story', 'voice', 'lorebook', 'scenario', 'memory',
    ];

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
                        placeholder="Search across all entities..."
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
                    {entityTypes.map((type) => (
                        <option key={type} value={type}>
                            {type.charAt(0).toUpperCase() + type.slice(1)}
                        </option>
                    ))}
                </select>
            </div>

            {entities && (
                <div className="mb-6">
                    <h2 className="text-lg font-semibold text-gray-300 mb-3">Entity Counts</h2>
                    <div className="grid grid-cols-4 sm:grid-cols-8 gap-3">
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
                                    <div className="text-xs text-gray-400 capitalize">{key}</div>
                                </motion.div>
                            );
                        })}
                    </div>
                </div>
            )}

            {isLoading && <div className="text-gray-400">Loading...</div>}

            {!isLoading && displayResults.length === 0 && (
                <div className="text-center py-12 text-gray-500">
                    {debouncedQuery ? 'No results found' : 'No entities yet'}
                </div>
            )}

            {!isLoading && displayResults.length > 0 && (
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
