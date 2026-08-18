import React, { useState, useMemo, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Filter, MessageSquare, BookOpen, Brain, Image as ImageIcon, Calendar } from 'lucide-react';
import { useTimeline } from '../hooks/useTimeline';
import EmptyState from '../components/EmptyState';
import { useSearchParams } from 'react-router-dom';

const EVENT_ICONS = {
    message: MessageSquare,
    chapter: BookOpen,
    memory: Brain,
    image: ImageIcon,
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

export default function WorldTimeline() {
    const [searchParams, setSearchParams] = useSearchParams();
    const [showFilters, setShowFilters] = useState(false);

    const initialFilters = {
        character_id: searchParams.get('character_id') || '',
        story_id: searchParams.get('story_id') || '',
        chat_id: searchParams.get('chat_id') || '',
        location: searchParams.get('location') || '',
    };
    const [filters, setFilters] = useState(initialFilters);

    useEffect(() => {
        const next = {};
        if (filters.character_id) next.character_id = filters.character_id;
        if (filters.story_id) next.story_id = filters.story_id;
        if (filters.chat_id) next.chat_id = filters.chat_id;
        if (filters.location) next.location = filters.location;
        setSearchParams(next, { replace: true });
    }, [filters, setSearchParams]);

    const { data, isLoading } = useTimeline(filters);

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

    return (
        <div className="p-6 max-w-5xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-white mb-1">World Timeline</h1>
                    <p className="text-gray-400 text-sm">Chronological view of all events across your world</p>
                </div>
                <button
                    onClick={() => setShowFilters(!showFilters)}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors ${showFilters ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
                >
                    <Filter size={16} /> Filters
                </button>
            </div>

            {showFilters && (
                <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    className="mb-6 p-4 bg-gray-800/40 border border-white/10 rounded-xl"
                >
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Character ID</label>
                            <input
                                type="text"
                                value={filters.character_id}
                                onChange={(e) => updateFilter('character_id', e.target.value)}
                                placeholder="Filter by character..."
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Story ID</label>
                            <input
                                type="text"
                                value={filters.story_id}
                                onChange={(e) => updateFilter('story_id', e.target.value)}
                                placeholder="Filter by story..."
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Chat ID</label>
                            <input
                                type="text"
                                value={filters.chat_id}
                                onChange={(e) => updateFilter('chat_id', e.target.value)}
                                placeholder="Filter by chat..."
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Location</label>
                            <input
                                type="text"
                                value={filters.location}
                                onChange={(e) => updateFilter('location', e.target.value)}
                                placeholder="Filter by location..."
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                            />
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
                                            <div className="p-4 bg-gray-800/40 border border-white/10 rounded-xl hover:border-white/20 transition-colors">
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
                </div>
            )}
        </div>
    );
}
