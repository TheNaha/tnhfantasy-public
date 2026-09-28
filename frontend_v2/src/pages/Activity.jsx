import React, { useState, useMemo, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Filter, MessageSquare, BookOpen, Brain, Image, Calendar } from 'lucide-react';
import { useTimeline } from '../hooks/useTimeline';
import { useCharacters } from '../hooks/useCharacters';
import { useStories } from '../hooks/useStories';
import { useChats } from '../hooks/useChats';
import { useLocations } from '../hooks/useLocations';
import EmptyState from '../components/EmptyState';
import RoleplayPageShell from '../components/RoleplayPageShell';
import { useSearchParams, useNavigate } from 'react-router-dom';

const EVENT_ICONS = {
    message: MessageSquare,
    chapter: BookOpen,
    memory: Brain,
    image: Image,
};

const EVENT_COLORS = {
    message: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
    chapter: 'text-green-400 bg-green-500/10 border-green-500/20',
    memory: 'text-purple-400 bg-purple-500/10 border-purple-500/20',
    image: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
};

const EVENT_LABELS = {
    message: 'Message',
    chapter: 'Chapter',
    memory: 'Memory',
    image: 'Image',
};

/**
 * Activity — a chronological log of what happened in the vault.
 *
 * Renamed from "World Timeline". It has no world, no world_id, and no notion of
 * one: it merges chat messages, story chapter edits, character memories and
 * image generations into one list ordered by timestamp. Described as "see how a
 * world changes over time" it read as authored chronology — canon, the order
 * things happened in the fiction — when it is the opposite: a log of what the
 * user did.
 *
 * The default filter is the NARRATIVE streams, not everything. Measured live,
 * the unfiltered first page was 196 image generations against 3 messages and 1
 * chapter, out of 16,530 events — so a user opening this page to see what
 * happened in their story saw a wall of pictures. Images are one click away in
 * the Gallery, which is where clicking an image event already sent them, so they
 * are opt-in rather than the default.
 */
const DEFAULT_TYPES = 'message,chapter,memory';

export default function Activity() {
    const [searchParams, setSearchParams] = useSearchParams();
    const [showImages, setShowImages] = useState(false);
    const [showFilters, setShowFilters] = useState(false);

    const initialFilters = {
        character_id: searchParams.get('character_id') || '',
        story_id: searchParams.get('story_id') || '',
        chat_id: searchParams.get('chat_id') || '',
        location: searchParams.get('location') || '',
    };
    const [filters, setFilters] = useState(initialFilters);
    const [limit, setLimit] = useState(100);

    useEffect(() => {
        const next = {};
        if (filters.character_id) next.character_id = filters.character_id;
        if (filters.story_id) next.story_id = filters.story_id;
        if (filters.chat_id) next.chat_id = filters.chat_id;
        if (filters.location) next.location = filters.location;
        setSearchParams(next, { replace: true });
    }, [filters, setSearchParams]);

    // `showImages` is opt-in. See the module comment: unfiltered, the first page
    // was 196 images against 3 messages, and the Gallery is one click away.
    const types = showImages ? 'message,chapter,memory,image' : DEFAULT_TYPES;
    const { data, isLoading } = useTimeline({ ...filters, limit, types });

    const { data: characters = [] } = useCharacters();
    const { data: stories = [] } = useStories();
    const { data: chats = [] } = useChats();
    const { data: locations = [] } = useLocations();

    const events = useMemo(() => data?.events || [], [data]);

    const groupedEvents = useMemo(() => {
        const groups = {};
        events.forEach(event => {
            const date = event.timestamp ? event.timestamp.split('T')[0] : 'Unknown';
            if (!groups[date]) groups[date] = [];
            groups[date].push(event);
        });
        return groups;
    }, [events]);

    const updateFilter = (key, value) => {
        setFilters(f => ({ ...f, [key]: value }));
    };

    const navigate = useNavigate();
    const total = data?.total ?? 0;

    const destinationLabel = (event) => {
        switch (event.type) {
            case 'message': return 'Open chat';
            case 'chapter': return 'Open story';
            case 'memory': return 'Open characters';
            case 'image': return 'Open gallery';
            default: return 'Open';
        }
    };

    const handleEventClick = (event) => {
        if (event.type === 'message' && event.chat_id) navigate(`/chat/${event.chat_id}`);
        else if (event.type === 'chapter' && event.story_id) navigate(`/story/${event.story_id}`);
        else if (event.type === 'memory' && event.character_id) navigate(`/characters#char-${event.character_id}`);
        else if (event.type === 'image') navigate('/gallery');
    };

    return (
        <RoleplayPageShell
            title="Activity"
            description="Everything that has happened in your vault, newest first — conversations, story chapters, and character memories."
            icon={Calendar}
            actions={
                <div className="flex items-center gap-2">
                    {/* Images are ~99% of the events (16,530 total on the live
                        deployment, and the unfiltered first page was 196 images
                        against 3 messages), so they are opt-in. The Gallery is
                        one click away and is where clicking an image event
                        already sent you. */}
                    <button
                        onClick={() => setShowImages(!showImages)}
                        title={showImages
                            ? 'Hiding image generations'
                            : 'Include image generations'}
                        className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${showImages ? 'bg-purple-500/20 text-purple-300' : 'bg-white/5 text-slate-400 hover:bg-white/10'}`}
                    >
                        <Image size={16} /> Images {showImages ? 'on' : 'off'}
                    </button>
                    <button
                        onClick={() => setShowFilters(!showFilters)}
                        className={`flex items-center gap-2 rounded-lg px-4 py-2 font-medium transition-colors ${showFilters ? 'bg-cyan-500/20 text-cyan-300' : 'bg-white/5 text-slate-300 hover:bg-white/10'}`}
                    >
                        <Filter size={16} /> Filters
                    </button>
                </div>
            }
        >

            {showFilters && (
                <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    className="mb-6 p-4 bg-gray-800/40 border border-white/10 rounded-xl"
                >
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        <div>
                            <label htmlFor="filter-character" className="block text-xs text-gray-400 mb-1">Character</label>
                            <select
                                id="filter-character"
                                value={filters.character_id}
                                onChange={(e) => updateFilter('character_id', e.target.value)}
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                            >
                                <option value="">All characters</option>
                                {characters.map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label htmlFor="filter-story" className="block text-xs text-gray-400 mb-1">Story</label>
                            <select
                                id="filter-story"
                                value={filters.story_id}
                                onChange={(e) => updateFilter('story_id', e.target.value)}
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                            >
                                <option value="">All stories</option>
                                {stories.map(s => (
                                    <option key={s.id} value={s.id}>{s.title || s.id}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label htmlFor="filter-chat" className="block text-xs text-gray-400 mb-1">Chat</label>
                            <select
                                id="filter-chat"
                                value={filters.chat_id}
                                onChange={(e) => updateFilter('chat_id', e.target.value)}
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                            >
                                <option value="">All chats</option>
                                {chats.map(c => (
                                    <option key={c.id} value={c.id}>{c.name || c.id}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label htmlFor="filter-location" className="block text-xs text-gray-400 mb-1">Location</label>
                            <select
                                id="filter-location"
                                value={filters.location}
                                onChange={(e) => updateFilter('location', e.target.value)}
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                            >
                                <option value="">All locations</option>
                                {locations.map(l => (
                                    <option key={l.id} value={l.id}>{l.name}</option>
                                ))}
                            </select>
                        </div>
                    </div>
                </motion.div>
            )}

            {isLoading ? (
                <div className="space-y-8 relative">
                    <div className="absolute left-8 top-0 bottom-0 w-px bg-white/10" />
                    {[1, 2, 3].map(i => (
                        <div key={i} className="relative flex items-start gap-4">
                            <div className="w-16 h-16 rounded-xl bg-gray-800/40 border border-white/5 animate-pulse z-10 shrink-0" />
                            <div className="flex-1 p-4 rounded-xl border border-white/10 bg-gray-800/40 animate-pulse mt-2">
                                <div className="h-5 bg-gray-700 rounded w-1/3 mb-2" />
                                <div className="h-4 bg-gray-700 rounded w-full mb-1" />
                                <div className="h-4 bg-gray-700 rounded w-5/6" />
                            </div>
                        </div>
                    ))}
                </div>
            ) : events.length === 0 ? (
                <EmptyState
                    icon={Calendar}
                    title="No events yet"
                    description="Start chatting, writing stories, or creating memories to see them here."
                />
            ) : (
                <div className="space-y-8">
                    {Object.entries(groupedEvents).sort((a, b) => b[0].localeCompare(a[0])).map(([date, dayEvents]) => (
                        <div key={date} className="relative">
                            <div className="sticky top-0 z-10 bg-[#0B0E14]/90 backdrop-blur-sm py-2 mb-4">
                                <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                                    <Calendar size={14} className="text-gray-500" />
                                    {date}
                                </h3>
                            </div>
                            <div className="space-y-3 ml-4 border-l-2 border-white/10 pl-6">
                                {dayEvents.map((event) => {
                                    const Icon = EVENT_ICONS[event.type] || MessageSquare;
                                    const colorClass = EVENT_COLORS[event.type] || EVENT_COLORS.message;
                                    const label = EVENT_LABELS[event.type] || event.type;
                                    return (
                                        <motion.div
                                            key={`${event.type}-${event.id}`}
                                            initial={{ opacity: 0, x: -10 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            className="relative"
                                        >
                                            <div className={`absolute -left-[31px] top-3 w-4 h-4 rounded-full border-2 ${colorClass} flex items-center justify-center`}>
                                                <Icon size={10} />
                                            </div>
                                            <div
                                                role="button"
                                                tabIndex={0}
                                                onClick={() => handleEventClick(event)}
                                                onKeyDown={(e) => { if (e.key === 'Enter') handleEventClick(event); }}
                                                title={destinationLabel(event)}
                                                className="p-4 bg-gray-800/40 border border-white/10 rounded-xl hover:border-white/20 hover:cursor-pointer transition-colors"
                                            >
                                                <div className="flex items-center gap-2 mb-1">
                                                    <span className={`text-xs px-2 py-0.5 rounded-full border ${colorClass}`}>
                                                        {label}
                                                    </span>
                                                    <span className="text-xs text-gray-500">
                                                        {event.timestamp?.split('T')[1]?.split('.')[0] || ''}
                                                    </span>
                                                </div>
                                                <h4 className="font-medium text-white text-sm mb-1">{event.title}</h4>
                                                {event.description && (
                                                    <p className="text-xs text-gray-400 line-clamp-2">{event.description}</p>
                                                )}
                                            </div>
                                        </motion.div>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                    {total > 0 && (
                        <div className="flex items-center justify-between mt-6 text-sm text-gray-400">
                            <span>Showing {events.length} of {total} events</span>
                            {events.length < total && limit < 500 && (
                                <button
                                    onClick={() => setLimit(l => Math.min(l + 100, 500))}
                                    className="px-4 py-2 rounded-lg bg-gray-800 text-gray-200 hover:bg-gray-700 transition-colors"
                                >
                                    Load more
                                </button>
                            )}
                        </div>
                    )}
                </div>
            )}
        </RoleplayPageShell>
    );
}
