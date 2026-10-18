import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    X, ChevronLeft, ChevronRight, Send, Sparkles, Heart,
    Smile, MessageSquare, Volume2, ImageIcon, Tv, User
} from 'lucide-react';
import { getAvatarUrl } from '../../hooks/useWorldVault';
import { assetUrl } from '../../utils/assetUrl';

export default function StageModeView({
    isOpen,
    onClose,
    messages = [],
    activeChat,
    linkedCharacter,
    characters = [],
    chatImages = [],
    activeStreams = [],
    onSendMessage,
    onGenerateTTS,
    ttsEnabled = false,
}) {
    const [historyIndex, setHistoryIndex] = useState(null);
    const [inputValue, setInputValue] = useState('');

    const characterMap = useMemo(() => {
        return new Map(characters.map(c => [c.id, c]));
    }, [characters]);

    // Latest scene image for backdrop
    const backdropImage = useMemo(() => {
        if (chatImages && chatImages.length > 0) {
            const latest = chatImages[0];
            return latest.url || latest.thumbnail_url || (latest.path ? assetUrl(latest.path) : null);
        }
        return null;
    }, [chatImages]);

    // Active streaming message if running
    const streamingStream = useMemo(() => {
        return activeStreams.find(s => s.jobData?.taskType !== 'image' && s.jobData?.type !== 'image');
    }, [activeStreams]);

    // Target message to display
    const currentMessage = useMemo(() => {
        if (streamingStream) {
            return {
                id: 'streaming',
                role: 'char',
                content: streamingStream.jobData?.streamText || streamingStream.jobData?.text || 'Thinking...',
                character_id: streamingStream.jobData?.characterId || activeChat?.character_id,
                isStreaming: true,
            };
        }

        const validMessages = messages.filter(m => m.role === 'char' || m.role === 'user');
        if (validMessages.length === 0) return null;

        if (historyIndex !== null) {
            const idx = Math.max(0, Math.min(validMessages.length - 1, historyIndex));
            return validMessages[idx];
        }

        return validMessages[validMessages.length - 1];
    }, [messages, streamingStream, historyIndex, activeChat]);

    const speaker = useMemo(() => {
        if (!currentMessage) return linkedCharacter;
        if (currentMessage.role === 'user') {
            return { name: activeChat?.persona_name || 'You', isUser: true };
        }
        const char = currentMessage.character_id ? characterMap.get(currentMessage.character_id) : null;
        return char || linkedCharacter;
    }, [currentMessage, characterMap, linkedCharacter, activeChat]);

    const snapshot = activeChat?.state_snapshot || {};
    const mood = snapshot.character_mood || 'curious_attentive';
    const expression = snapshot.character_expression || null;
    const actionChips = snapshot.last_director_decision?.suggested_action_chips || [];

    const handleSend = (text) => {
        const toSend = (text || inputValue).trim();
        if (!toSend) return;
        onSendMessage?.(toSend);
        setInputValue('');
        setHistoryIndex(null); // jump to latest
    };

    if (!isOpen) return null;

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 z-50 flex flex-col bg-black select-none overflow-hidden font-sans"
            >
                {/* Background Art / Scenery */}
                <div className="absolute inset-0 z-0">
                    {backdropImage ? (
                        <div
                            className="w-full h-full bg-cover bg-center filter brightness-75 scale-105 transition-all duration-700"
                            style={{ backgroundImage: `url(${backdropImage})` }}
                        />
                    ) : (
                        <div className="w-full h-full bg-gradient-to-b from-indigo-950 via-gray-900 to-black" />
                    )}
                    {/* Atmospheric Vignette & Gradients */}
                    <div className="absolute inset-0 bg-gradient-to-t from-black via-black/40 to-transparent" />
                    <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-transparent to-transparent" />
                </div>

                {/* Top Stage Control Bar */}
                <div className="relative z-20 flex items-center justify-between px-4 sm:px-6 py-3 bg-gradient-to-b from-black/80 to-transparent">
                    <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-purple-500/20 border border-purple-500/30 text-purple-200 text-xs font-semibold">
                            <Tv size={14} className="text-purple-400" />
                            <span>Visual Novel Stage</span>
                        </div>
                        {activeChat?.story_location && (
                            <span className="hidden sm:inline-block text-xs text-gray-300 px-2 py-0.5 rounded bg-black/40 border border-white/10">
                                📍 {activeChat.story_location}
                            </span>
                        )}
                        {expression && (
                            <span className="hidden sm:inline-block text-xs text-amber-300 px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 capitalize">
                                ✨ {expression}
                            </span>
                        )}
                    </div>

                    <div className="flex items-center gap-2">
                        {/* History navigation */}
                        <div className="flex items-center bg-black/50 border border-white/10 rounded-lg p-0.5 text-xs text-gray-300">
                            <button
                                type="button"
                                onClick={() => {
                                    const validMessages = messages.filter(m => m.role === 'char' || m.role === 'user');
                                    const curr = historyIndex !== null ? historyIndex : validMessages.length - 1;
                                    if (curr > 0) setHistoryIndex(curr - 1);
                                }}
                                className="p-1 hover:text-white hover:bg-white/10 rounded transition-colors"
                                title="Previous dialogue"
                            >
                                <ChevronLeft size={16} />
                            </button>
                            <span className="px-2 font-mono text-3xs text-gray-400">
                                Log
                            </span>
                            <button
                                type="button"
                                onClick={() => {
                                    const validMessages = messages.filter(m => m.role === 'char' || m.role === 'user');
                                    const curr = historyIndex !== null ? historyIndex : validMessages.length - 1;
                                    if (curr < validMessages.length - 1) setHistoryIndex(curr + 1);
                                    else setHistoryIndex(null);
                                }}
                                className="p-1 hover:text-white hover:bg-white/10 rounded transition-colors"
                                title="Next dialogue"
                            >
                                <ChevronRight size={16} />
                            </button>
                        </div>

                        <button
                            type="button"
                            onClick={onClose}
                            className="p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-xl transition-colors"
                            title="Exit Stage Mode"
                        >
                            <X size={20} />
                        </button>
                    </div>
                </div>

                {/* Central Stage: Character Portrait Sprite */}
                <div className="relative z-10 flex-1 flex items-end justify-center pb-2 px-4 pointer-events-none">
                    {speaker && !speaker.isUser && (
                        <motion.div
                            initial={{ y: 30, opacity: 0 }}
                            animate={{ y: 0, opacity: 1 }}
                            transition={{ duration: 0.5, ease: 'easeOut' }}
                            className="relative max-h-[60vh] flex flex-col items-center pointer-events-auto"
                        >
                            {speaker.avatar_path ? (
                                <img
                                    src={getAvatarUrl(speaker.id)}
                                    alt={speaker.name}
                                    className="max-h-[50vh] sm:max-h-[58vh] object-contain drop-shadow-[0_15px_30px_rgba(0,0,0,0.8)] filter brightness-95 rounded-2xl border border-white/10"
                                />
                            ) : (
                                <div className="w-48 h-48 rounded-full bg-gradient-to-tr from-purple-600/40 to-blue-600/40 border border-white/20 flex items-center justify-center shadow-2xl">
                                    <User size={64} className="text-gray-400" />
                                </div>
                            )}
                        </motion.div>
                    )}
                </div>

                {/* Bottom Visual Novel Dialogue Frame */}
                <div className="relative z-20 w-full max-w-4xl mx-auto px-4 pb-4">
                    {/* Suggested In-Stage Action Chips */}
                    {actionChips.length > 0 && (
                        <div className="flex items-center gap-1.5 mb-2 overflow-x-auto custom-scrollbar pb-1">
                            {actionChips.map((chip, idx) => (
                                <button
                                    key={idx}
                                    type="button"
                                    onClick={() => handleSend(chip)}
                                    className="text-xs px-3 py-1 rounded-full bg-black/60 hover:bg-purple-600/30 border border-white/15 hover:border-purple-400/50 text-gray-200 hover:text-purple-100 backdrop-blur-md transition-all shadow-md shrink-0"
                                >
                                    ✨ {chip}
                                </button>
                            ))}
                        </div>
                    )}

                    {/* Dialogue Box */}
                    <div className="relative rounded-2xl border border-white/15 bg-black/85 backdrop-blur-xl p-4 sm:p-5 shadow-2xl space-y-3">
                        {/* Nameplate */}
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <span className="px-3 py-1 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 text-white font-bold text-xs uppercase tracking-wider shadow-sm">
                                    {speaker?.name || 'Character'}
                                </span>
                                {mood && (
                                    <span className="text-3xs text-purple-200/80 px-2 py-0.5 rounded-full bg-white/5 border border-white/10">
                                        {mood.replace(/_/g, ' ')}
                                    </span>
                                )}
                            </div>

                            {ttsEnabled && currentMessage?.role === 'char' && (
                                <button
                                    type="button"
                                    onClick={() => onGenerateTTS?.(currentMessage.id)}
                                    className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                                    title="Read dialogue aloud"
                                >
                                    <Volume2 size={16} />
                                </button>
                            )}
                        </div>

                        {/* Dialogue Prose */}
                        <div className="min-h-[60px] max-h-36 overflow-y-auto custom-scrollbar text-sm sm:text-base text-gray-100 leading-relaxed font-serif">
                            {currentMessage ? (
                                <p className="whitespace-pre-wrap">{currentMessage.content}</p>
                            ) : (
                                <p className="text-gray-500 italic">Dialogue appears here as the story unfolds. Begin below!</p>
                            )}
                        </div>

                        {/* In-Stage Speech Input Bar */}
                        <div className="pt-2 border-t border-white/10 flex items-center gap-2">
                            <input
                                type="text"
                                value={inputValue}
                                onChange={(e) => setInputValue(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        handleSend();
                                    }
                                }}
                                placeholder={`Respond to ${speaker?.name || 'the scene'}...`}
                                className="flex-1 px-3 py-2 bg-gray-900/80 border border-white/10 rounded-xl text-xs sm:text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/60"
                            />
                            <button
                                type="button"
                                onClick={() => handleSend()}
                                disabled={!inputValue.trim()}
                                className="px-4 py-2 rounded-xl bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 text-white font-medium text-xs flex items-center gap-1.5 transition-all disabled:opacity-40 shadow-md"
                            >
                                <Send size={13} />
                                <span className="hidden sm:inline">Reply</span>
                            </button>
                        </div>
                    </div>
                </div>
            </motion.div>
        </AnimatePresence>
    );
}
