import React, { useEffect, useMemo, useState } from 'react';
import {
    Users, Clock, MessageSquare, User, X,
} from 'lucide-react';
import { useCharacters } from '../hooks/useCharacters';
import { useChats } from '../hooks/useChats';
import { api } from '../api/client';
import { parseGalleryDate } from '../utils/dateTime';
import EmptyState from '../components/EmptyState';
import { QueryErrorState } from '../components/common/QueryState';

/**
 * RelationshipTimeline — shows how the relationship between two characters
 * evolved across chats, with messages in chronological order.
 *
 * Reads chats where both characters appear (primary character_id or
 * additional_character_ids), then streams each chat's messages sorted
 * by created_at into a unified timeline.
 */
export default function RelationshipTimeline() {
    const { data: characters = [], isLoading: charsLoading, isError: charsError, error: charsErr, refetch: refetchChars } = useCharacters();
    const { data: chats = [], isLoading: chatsLoading, isError: chatsError, error: chatsErr, refetch: refetchChats } = useChats();

    const [charAId, setCharAId] = useState(null);
    const [charBId, setCharBId] = useState(null);
    const [timeline, setTimeline] = useState([]);
    const [timelineLoading, setTimelineLoading] = useState(false);

    const charA = characters.find((c) => c.id === charAId);
    const charB = characters.find((c) => c.id === charBId);

    // Build timeline when both characters are selected
    useEffect(() => {
        if (!charAId || !charBId) {
            setTimeline([]);
            return;
        }

        const relevantChats = chats.filter((chat) => {
            const ids = new Set([
                chat.character_id,
                ...(Array.isArray(chat.additional_character_ids) ? chat.additional_character_ids : []),
            ]);
            return ids.has(charAId) && ids.has(charBId);
        });

        setTimelineLoading(true);
        // Fetch messages for each relevant chat and merge into one timeline
        const fetchTimeline = async () => {
            try {
                const messagePromises = relevantChats.map(async (chat) => {
                    try {
                        const resp = await api.get(
                            `/api/v2/chats/${chat.id}/messages`,
                            { params: { limit: 200 } }
                        );
                        const msgs = Array.isArray(resp.data) ? resp.data : (resp.data.messages || []);
                        return msgs.map((m) => ({
                            ...m,
                            chat_id: chat.id,
                            chat_name: chat.name || 'Untitled',
                        }));
                    } catch {
                        return [];
                    }
                });
                const allMessages = (await Promise.all(messagePromises)).flat();
                // Sort by created_at ascending
                allMessages.sort((a, b) => {
                    const da = new Date(a.created_at || 0).getTime();
                    const db = new Date(b.created_at || 0).getTime();
                    return da - db;
                });
                setTimeline(allMessages);
            } finally {
                setTimelineLoading(false);
            }
        };
        fetchTimeline();
    }, [charAId, charBId, chats]);

    const charById = useMemo(
        () => new Map(characters.map((c) => [c.id, c])),
        [characters]
    );

    const formatMsgDate = (iso) => {
        const d = parseGalleryDate(iso);
        return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
    };

    if (charsLoading || chatsLoading) {
        return (
            <div className="flex h-full items-center justify-center text-gray-400">
                Loading characters and chats…
            </div>
        );
    }

    if (charsError || chatsError) {
        return (
            <div className="flex h-full items-center justify-center p-8">
                <QueryErrorState noun="characters" error={charsErr || chatsErr} onRetry={() => { refetchChars(); refetchChats(); }} />
            </div>
        );
    }

    if (characters.length === 0) {
        return (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center">
                <EmptyState
                    title="No characters yet"
                    description="Create some characters first, then view their relationship timeline here."
                />
            </div>
        );
    }

    return (
        <div className="flex h-full flex-col bg-gray-900 text-white">
            <header className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-gray-800/50 shrink-0">
                <div className="flex items-center gap-2">
                    <Users size={18} className="text-purple-400" />
                    <h1 className="text-lg font-semibold">Relationship Timeline</h1>
                </div>
                <p className="text-gray-400 text-sm">
                    Watch how two characters&rsquo; relationship evolves across
                    chats, message by message.
                </p>
            </header>

            <div className="flex flex-1 overflow-hidden">
                {/* Character selectors */}
                <aside className="w-72 border-r border-white/5 bg-gray-800/50 shrink-0 flex flex-col overflow-y-auto p-4">
                    <div className="mb-4">
                        <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 block">
                            Character A
                        </label>
                        <select
                            value={charAId || ''}
                            onChange={(e) => setCharAId(e.target.value || null)}
                            className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-gray-200 focus:outline-none focus:border-blue-500/50"
                        >
                            <option value="">Select a character…</option>
                            {characters.map((c) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                        </select>
                    </div>
                    <div className="mb-4">
                        <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 block">
                            Character B
                        </label>
                        <select
                            value={charBId || ''}
                            onChange={(e) => setCharBId(e.target.value || null)}
                            className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-gray-200 focus:outline-none focus:border-blue-500/50"
                        >
                            <option value="">Select a character…</option>
                            {characters.map((c) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                        </select>
                    </div>
                    {charA && charB && (
                        <div className="p-3 rounded-xl border border-purple-500/30 bg-purple-500/10">
                            <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-2">
                                    <User size={14} className="text-purple-400" />
                                    <span className="text-sm font-medium text-white">{charA.name}</span>
                                </div>
                                <div className="text-xs text-gray-400">{charAId}</div>
                            </div>
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <User size={14} className="text-purple-400" />
                                    <span className="text-sm font-medium text-white">{charB.name}</span>
                                </div>
                                <div className="text-xs text-gray-400">{charBId}</div>
                            </div>
                        </div>
                    )}
                    {!charAId || !charBId ? (
                        <div className="mt-auto p-3 rounded-lg bg-gray-800/30 border border-gray-700/30">
                            <p className="text-xs text-gray-400 text-center leading-relaxed">
                            Select two characters to see their shared message
                            timeline — every chat where both appear will be
                            merged chronologically.
                            </p>
                        </div>
                    ) : (
                        <button
                            onClick={() => { setCharAId(null); setCharBId(null); setTimeline([]); }}
                            className="w-full flex items-center justify-center gap-2 text-red-400 hover:text-red-300 text-sm font-medium transition-colors py-2"
                        >
                            <X size={16} /> Clear selection
                        </button>
                    )}
                </aside>

                {/* Timeline */}
                <main className="flex-1 overflow-y-auto relative bg-gray-900/30">
                    {!charAId || !charBId ? (
                        <div className="flex h-full flex-col items-center justify-center p-12 text-center">
                            <Clock size={48} className="text-gray-700 mb-4" />
                            <h2 className="text-xl font-medium text-gray-200 mb-2">Pick two characters</h2>
                            <p className="text-gray-500 text-sm">
                                Their shared conversation history will appear here,
                                ordered chronologically from first meeting to latest exchange.
                            </p>
                        </div>
                    ) : timelineLoading ? (
                        <div className="flex h-full items-center justify-center text-gray-400">
                            Loading shared history…
                        </div>
                    ) : timeline.length === 0 ? (
                        <div className="flex h-full flex-col items-center justify-center p-12 text-center">
                            <MessageSquare size={48} className="text-gray-700 mb-4" />
                            <h2 className="text-xl font-medium text-gray-200 mb-2">No shared history yet</h2>
                            <p className="text-gray-500 text-sm">
                                {charA.name} and {charB.name} haven&rsquo;t appeared in the same
                                chat yet. Start a conversation with both and it will show up here.
                            </p>
                        </div>
                    ) : (
                        <div className="px-4 py-6 space-y-6">
                            <div className="flex items-center gap-2 mb-4">
                                <Clock size={16} className="text-gray-500" />
                                <span className="text-sm font-medium text-gray-300">
                                    {timeline.length} shared messages across {new Set(timeline.map((m) => m.chat_id)).size} chat{new Set(timeline.map((m) => m.chat_id)).size === 1 ? '' : 's'}
                                </span>
                            </div>
                            {timeline.map((msg, idx) => {
                                const speaker = charById.get(msg.character_id) || { name: 'Unknown', id: msg.character_id };
                                const isCharA = msg.character_id === charAId;
                                const isFirstInChat = idx === 0 || timeline[idx - 1]?.chat_id !== msg.chat_id;
                                return (
                                    <div
                                        key={msg.id}
                                        className={`flex gap-4 ${isCharA ? 'items-start' : 'items-end'}`}
                                    >
                                        {/* Timeline connector line */}
                                        <div className="hidden md:flex flex-col items-center">
                                            {isFirstInChat && (
                                                <div className="w-px h-3 bg-purple-500/50 mb-1" />
                                            )}
                                            <div className="w-px h-full bg-white/5" />
                                            {idx === timeline.length - 1 ? (
                                                <div className="w-px h-3 bg-purple-500/50 mt-1" />
                                            ) : null}
                                        </div>
                                        <div className={`flex flex-col gap-1 max-w-[80%] ${isCharA ? 'ml-4' : 'mr-4'}`}>
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className={`text-xs font-bold ${isCharA ? 'text-purple-300' : 'text-blue-300'}`}>
                                                    {speaker.name}
                                                </span>
                                                <span className="text-xs text-gray-500">
                                                    {formatMsgDate(msg.created_at)}
                                                </span>
                                                {isFirstInChat && (
                                                    <span className="text-xs text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">
                                                        {msg.chat_name}
                                                    </span>
                                                )}
                                            </div>
                                            <div
                                                className={`rounded-xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                                                    isCharA
                                                        ? 'bg-purple-500/10 border border-purple-500/20 rounded-tr-none'
                                                        : 'bg-blue-500/10 border border-blue-500/20 rounded-tl-none'
                                                }`}
                                            >
                                                {msg.content}
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </main>
            </div>
        </div>
    );
}
