import React, { useState, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import clsx from 'clsx';
import {
    Sparkles, RefreshCw, MessageSquare, Play, Compass,
    Shield, Swords, Eye, Loader2, ChevronRight, Wand2
} from 'lucide-react';

const ACTION_ARCHETYPES = [
    {
        category: 'Action',
        icon: Swords,
        color: 'text-rose-400 bg-rose-500/10 border-rose-500/20 hover:border-rose-400/40 hover:bg-rose-500/20',
        templates: [
            'Confront the disturbance directly and demand answers',
            'Draw a weapon and cautiously inspect the perimeter',
            'Leap forward to protect your companions from harm',
            'Break into a sprint toward the mysterious signal',
            'Brace yourself as the unexpected tension escalates',
        ],
    },
    {
        category: 'Dialogue',
        icon: MessageSquare,
        color: 'text-blue-400 bg-blue-500/10 border-blue-500/20 hover:border-blue-400/40 hover:bg-blue-500/20',
        templates: [
            'Ask in a low, measured voice what they know',
            'Attempt to diffuse the hostility with calm reasoning',
            'Press them firmly for the truth before moving on',
            'Whisper a discreet warning to your closest ally',
            'Reveal a startling secret that shifts the entire dynamic',
        ],
    },
    {
        category: 'Discovery',
        icon: Eye,
        color: 'text-amber-400 bg-amber-500/10 border-amber-500/20 hover:border-amber-400/40 hover:bg-amber-500/20',
        templates: [
            'Search the immediate surroundings for hidden clues or traps',
            'Examine the strange markings glowing faintly nearby',
            'Slip into the shadows and observe without being noticed',
            'Decipher the ancient text etched across the surface',
            'Take a moment to listen closely to the echoing silence',
        ],
    },
];

export default function StoryDirectorDeck({
    activeStory,
    activeChapter,
    editorContent = '',
    onSelectChoice,
    onStartChat,
    isStartingChat = false,
    isStreaming = false,
}) {
    const [rerollSeed, setRerollSeed] = useState(0);

    // Compute 3 smart choices based on recent prose and archetypes
    const choices = useMemo(() => {
        const beats = activeChapter?.beats || [];
        const lastBeatText = beats.length > 0 ? (beats[beats.length - 1]?.content || '') : '';
        const tailText = (editorContent || lastBeatText).trim().slice(-600).toLowerCase();

        return ACTION_ARCHETYPES.map((arch, index) => {
            const pool = arch.templates;
            // Seeded deterministic cycle based on rerollSeed + tail text length
            const pickIndex = (rerollSeed + index + tailText.length) % pool.length;
            const text = pool[pickIndex];
            return {
                category: arch.category,
                icon: arch.icon,
                color: arch.color,
                text,
            };
        });
    }, [activeChapter?.beats, editorContent, rerollSeed]);

    const handleReroll = useCallback(() => {
        setRerollSeed(s => s + 1);
    }, []);

    return (
        <div className="w-full bg-gradient-to-r from-gray-950 via-gray-900/90 to-gray-950 border-t border-white/5 p-3 sm:p-4 backdrop-blur-md space-y-3 select-none">
            {/* Header Deck Bar */}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/30 text-purple-300 text-3xs font-bold uppercase tracking-wider">
                        <Compass size={12} className="text-purple-400" />
                        <span>Director's Deck</span>
                    </span>
                    <span className="text-3xs text-gray-400 hidden sm:inline">
                        Choose next story direction or step in to roleplay live
                    </span>
                </div>

                <div className="flex items-center gap-2">
                    {/* Reroll Choices Button */}
                    <button
                        type="button"
                        onClick={handleReroll}
                        disabled={isStreaming}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white text-3xs border border-white/5 transition-colors disabled:opacity-40"
                        title="Reroll story action suggestions"
                    >
                        <RefreshCw size={11} className={clsx(rerollSeed > 0 && "transition-transform duration-300")} />
                        <span>Reroll Choices</span>
                    </button>

                    {/* Step In & Play Scene (Story -> Chat Bridge) */}
                    <button
                        type="button"
                        onClick={onStartChat}
                        disabled={isStartingChat || !activeStory}
                        className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 hover:from-indigo-500 hover:to-pink-500 text-white font-medium text-3xs shadow-md transition-all disabled:opacity-50"
                        title="Convert this scene's context into a live roleplay session with the characters"
                    >
                        {isStartingChat ? (
                            <Loader2 size={12} className="animate-spin text-white" />
                        ) : (
                            <Play size={12} className="fill-white text-white" />
                        )}
                        <span>Step In &amp; Play Scene</span>
                    </button>
                </div>
            </div>

            {/* 3 Contextual Choice Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-3">
                {choices.map((choice, idx) => (
                    <motion.button
                        key={`${choice.category}-${idx}-${rerollSeed}`}
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.2, delay: idx * 0.05 }}
                        type="button"
                        onClick={() => onSelectChoice?.(choice.text)}
                        disabled={isStreaming}
                        className={clsx(
                            "flex flex-col text-left p-2.5 sm:p-3 rounded-xl border transition-all duration-200 group relative",
                            choice.color,
                            isStreaming && "opacity-40 cursor-not-allowed"
                        )}
                    >
                        <div className="flex items-center justify-between w-full mb-1">
                            <span className="flex items-center gap-1 text-3xs font-bold uppercase tracking-wider opacity-80">
                                <choice.icon size={11} />
                                <span>{choice.category}</span>
                            </span>
                            <ChevronRight size={12} className="opacity-40 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                        </div>
                        <p className="text-xs text-gray-200 font-medium line-clamp-2 leading-relaxed">
                            {choice.text}
                        </p>
                    </motion.button>
                ))}
            </div>
        </div>
    );
}
