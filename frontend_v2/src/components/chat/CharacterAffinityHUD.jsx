import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import clsx from 'clsx';
import {
    Heart, Sparkles, Shield, Eye, Smile, Flame, CloudRain,
    Package, Shirt, ChevronDown, ChevronUp, User,
    Lock, Unlock, Edit3, Check, X
} from 'lucide-react';
import { useChatWorkspace } from '../../contexts/ChatWorkspaceContext';
import { getAvatarUrl } from '../../hooks/useWorldVault';

const MOOD_CONFIG = {
    warm_affectionate: {
        label: 'Warm & Affectionate',
        icon: Heart,
        color: 'text-pink-300 bg-pink-500/15 border-pink-500/30',
        barColor: 'from-pink-500 to-rose-400',
    },
    playful_teasing: {
        label: 'Playful & Teasing',
        icon: Sparkles,
        color: 'text-amber-300 bg-amber-500/15 border-amber-500/30',
        barColor: 'from-amber-400 to-orange-400',
    },
    curious_attentive: {
        label: 'Curious & Attentive',
        icon: Eye,
        color: 'text-cyan-300 bg-cyan-500/15 border-cyan-500/30',
        barColor: 'from-cyan-400 to-blue-500',
    },
    flustered_shy: {
        label: 'Flustered & Shy',
        icon: Smile,
        color: 'text-rose-300 bg-rose-500/15 border-rose-500/30',
        barColor: 'from-rose-400 to-pink-500',
    },
    guarded_watchful: {
        label: 'Guarded & Watchful',
        icon: Shield,
        color: 'text-slate-300 bg-slate-500/15 border-slate-500/30',
        barColor: 'from-slate-500 to-zinc-400',
    },
    irritated_annoyed: {
        label: 'Irritated & Annoyed',
        icon: Flame,
        color: 'text-red-300 bg-red-500/15 border-red-500/30',
        barColor: 'from-red-500 to-orange-600',
    },
    melancholic_vulnerable: {
        label: 'Melancholic & Vulnerable',
        icon: CloudRain,
        color: 'text-indigo-300 bg-indigo-500/15 border-indigo-500/30',
        barColor: 'from-indigo-400 to-purple-500',
    },
};

export default function CharacterAffinityHUD() {
    const { activeChat, linkedCharacter, activeStreams = [], handleChatUpdate } = useChatWorkspace();
    const [expanded, setExpanded] = useState(false);
    const [isEditingRelationship, setIsEditingRelationship] = useState(false);
    const [relationshipDraft, setRelationshipDraft] = useState('');

    const snapshot = activeChat?.state_snapshot || {};

    // Live preview from streaming director decision if in-flight
    const streamingDecision = useMemo(() => {
        const stream = activeStreams.find(s => s.jobData?.directorDecision);
        return stream?.jobData?.directorDecision || null;
    }, [activeStreams]);

    const rawMoodKey = streamingDecision?.character_mood || snapshot.character_mood || 'curious_attentive';
    const moodConfig = MOOD_CONFIG[rawMoodKey] || {
        label: rawMoodKey.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
        icon: Smile,
        color: 'text-blue-300 bg-blue-500/15 border-blue-500/30',
        barColor: 'from-blue-500 to-emerald-400',
    };

    const rawInventory = snapshot.inventory;
    const inventoryItems = Array.isArray(rawInventory)
        ? rawInventory.map(item => typeof item === 'string' ? item : item?.name || item?.label || '').filter(Boolean)
        : [];

    const relationshipStatus = snapshot.relationship_status || snapshot.relationship || 'Developing bond';
    const characterOutfit = snapshot.character_outfit || snapshot.outfit || null;
    const currentActivity = snapshot.current_activity || snapshot.activity || null;
    const expression = snapshot.character_expression || streamingDecision?.character_expression || null;
    const isNeutralExpression = !expression || expression.toLowerCase() === 'neutral' || expression.toLowerCase() === 'normal';

    const lockedFields = snapshot.locked_fields || [];
    const isRelationshipLocked = lockedFields.includes('relationship_status') || lockedFields.includes('relationship');

    const toggleLockRelationship = () => {
        if (!handleChatUpdate) return;
        const nextLocked = isRelationshipLocked
            ? lockedFields.filter(f => f !== 'relationship_status' && f !== 'relationship')
            : [...lockedFields, 'relationship_status', 'relationship'];
        const nextSnapshot = { ...snapshot, locked_fields: nextLocked };
        handleChatUpdate({ state_snapshot: nextSnapshot });
    };

    const saveRelationship = () => {
        if (!relationshipDraft.trim() || !handleChatUpdate) return;
        const nextSnapshot = {
            ...snapshot,
            relationship_status: relationshipDraft.trim(),
            relationship: relationshipDraft.trim()
        };
        handleChatUpdate({ state_snapshot: nextSnapshot });
        setIsEditingRelationship(false);
    };

    if (!activeChat) return null;

    return (
        <div className="relative border-b border-white/5 bg-gradient-to-r from-gray-900/90 via-gray-900/80 to-gray-950/90 backdrop-blur-md px-3 sm:px-4 py-2 text-xs select-none z-10 transition-all">
            <div className="flex flex-wrap items-center justify-between gap-2">
                {/* Left: Character Info, Affinity Bar & Floating Delta */}
                <div className="flex items-center gap-3 min-w-0 flex-1">
                    {/* Character Mini Avatar */}
                    <div className="relative shrink-0">
                        <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-tr from-pink-500/30 via-purple-500/20 to-blue-500/30 border border-white/15 overflow-hidden flex items-center justify-center shadow-inner">
                            {linkedCharacter?.avatar_path ? (
                                <img
                                    src={getAvatarUrl(linkedCharacter.id)}
                                    alt={linkedCharacter.name}
                                    className="w-full h-full object-cover"
                                />
                            ) : (
                                <User size={14} className="text-gray-400" />
                            )}
                        </div>
                        {/* Status dot */}
                        <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-gray-900 bg-pink-400" />
                    </div>

                    {/* Dynamic Relationship Badge */}
                    {isEditingRelationship ? (
                        <div className="flex items-center gap-1 bg-gray-800/90 border border-pink-500/40 rounded-full px-2 py-0.5">
                            <input
                                type="text"
                                value={relationshipDraft}
                                onChange={(e) => setRelationshipDraft(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') saveRelationship();
                                    if (e.key === 'Escape') setIsEditingRelationship(false);
                                }}
                                autoFocus
                                placeholder="Relationship dynamic..."
                                className="bg-transparent text-xs text-pink-200 placeholder-gray-500 focus:outline-none w-36 sm:w-44"
                            />
                            <button onClick={saveRelationship} className="text-emerald-400 hover:text-emerald-300 p-0.5" title="Save dynamic">
                                <Check size={11} />
                            </button>
                            <button onClick={() => setIsEditingRelationship(false)} className="text-gray-400 hover:text-white p-0.5" title="Cancel">
                                <X size={11} />
                            </button>
                        </div>
                    ) : (
                        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-pink-500/10 border border-pink-500/25 text-pink-200 text-3xs font-medium max-w-[240px] shadow-sm">
                            <Heart size={11} className="text-pink-400 shrink-0 fill-pink-500/30" />
                            <span className="font-bold text-pink-300 uppercase tracking-wider shrink-0 hidden xs:inline">Dynamic:</span>
                            <span
                                className="truncate cursor-pointer hover:underline"
                                title={`Relationship: ${relationshipStatus} (Click to edit)`}
                                onClick={() => {
                                    setRelationshipDraft(relationshipStatus);
                                    setIsEditingRelationship(true);
                                }}
                            >
                                {relationshipStatus}
                            </span>
                            <button
                                type="button"
                                onClick={() => {
                                    setRelationshipDraft(relationshipStatus);
                                    setIsEditingRelationship(true);
                                }}
                                className="text-pink-400/60 hover:text-pink-200 p-0.5 rounded transition-colors shrink-0"
                                title="Edit relationship dynamic"
                                aria-label="Edit relationship dynamic"
                            >
                                <Edit3 size={10} />
                            </button>
                            <button
                                type="button"
                                onClick={toggleLockRelationship}
                                className={clsx(
                                    "p-0.5 rounded transition-colors shrink-0",
                                    isRelationshipLocked ? "text-amber-400 hover:text-amber-300" : "text-gray-500 hover:text-gray-300"
                                )}
                                title={isRelationshipLocked ? "Locked: Protected against AI drift" : "Unlocked: Statekeeper can evolve dynamic"}
                                aria-label={isRelationshipLocked ? "Unlock dynamic" : "Lock dynamic"}
                            >
                                {isRelationshipLocked ? <Lock size={10} /> : <Unlock size={10} />}
                            </button>
                        </div>
                    )}

                    {/* Mood Badge */}
                    <div className={clsx(
                        "hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-3xs font-medium shadow-sm shrink-0",
                        moodConfig.color
                    )}>
                        <moodConfig.icon size={11} />
                        <span className="truncate max-w-[130px]">{moodConfig.label}</span>
                    </div>

                    {/* Expression Badge (Neutral/normal suppressed) */}
                    {!isNeutralExpression && expression && (
                        <div className="hidden md:flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300 text-3xs shrink-0">
                            <Sparkles size={10} className="text-amber-400" />
                            <span className="capitalize truncate max-w-[100px]">{expression}</span>
                        </div>
                    )}
                </div>

                {/* Right: Quick Items, Activity & Expand Toggle */}
                <div className="flex items-center gap-2 shrink-0">
                    {/* Inventory Pills */}
                    {inventoryItems.length > 0 && (
                        <div className="hidden lg:flex items-center gap-1 mr-1">
                            <Package size={11} className="text-indigo-400 shrink-0" />
                            <div className="flex items-center gap-1 max-w-[180px] overflow-hidden">
                                {inventoryItems.slice(0, 2).map((item, idx) => (
                                    <span
                                        key={idx}
                                        className="px-2 py-0.5 rounded-md bg-indigo-500/10 border border-indigo-500/20 text-indigo-200 text-3xs truncate"
                                        title={item}
                                    >
                                        {item}
                                    </span>
                                ))}
                                {inventoryItems.length > 2 && (
                                    <span className="text-3xs text-gray-500 font-mono">
                                        +{inventoryItems.length - 2}
                                    </span>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Expand/Collapse details */}
                    <button
                        type="button"
                        onClick={() => setExpanded(v => !v)}
                        className="flex items-center gap-1 px-2 py-1 rounded-lg text-3xs text-gray-400 hover:text-white hover:bg-white/5 border border-white/5 transition-colors"
                        title={expanded ? "Hide character status" : "View character status & inventory"}
                    >
                        <span>{expanded ? "Less" : "Status"}</span>
                        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    </button>
                </div>
            </div>

            {/* Expandable Character Status & Inventory Drawer */}
            <AnimatePresence>
                {expanded && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden pt-2.5 mt-2 border-t border-white/5"
                    >
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 p-3 rounded-xl bg-black/40 border border-white/5 text-3xs">
                            {/* Dynamic Bond & Mood */}
                            <div className="space-y-1.5">
                                <div className="font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1">
                                    <Heart size={11} className="text-pink-400" />
                                    Relationship &amp; Dynamic
                                </div>
                                <div className="text-gray-200 font-medium leading-relaxed">
                                    {relationshipStatus}
                                </div>
                                <div className="text-gray-400 flex items-center gap-1">
                                    <span>Current Mood:</span>
                                    <span className="text-pink-300 font-medium">{moodConfig.label}</span>
                                </div>
                                {snapshot.relationship_summary && (
                                    <div className="text-gray-400 italic pt-1 border-t border-white/5">
                                        &ldquo;{snapshot.relationship_summary}&rdquo;
                                    </div>
                                )}
                            </div>

                            {/* Appearance & Activity */}
                            <div className="space-y-1.5">
                                <div className="font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1">
                                    <Shirt size={11} className="text-purple-400" />
                                    Attire &amp; Activity
                                </div>
                                <div>
                                    <span className="text-gray-500 block">Attire:</span>
                                    <span className="text-gray-200">{characterOutfit || 'Standard attire'}</span>
                                </div>
                                <div>
                                    <span className="text-gray-500 block">Current Action:</span>
                                    <span className="text-gray-200">{currentActivity || 'Engaged in conversation'}</span>
                                </div>
                            </div>

                            {/* Inventory & Possessions */}
                            <div className="space-y-1.5">
                                <div className="font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1">
                                    <Package size={11} className="text-indigo-400" />
                                    Inventory &amp; Artifacts
                                </div>
                                {inventoryItems.length > 0 ? (
                                    <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto custom-scrollbar">
                                        {inventoryItems.map((item, idx) => (
                                            <span
                                                key={idx}
                                                className="px-2 py-0.5 rounded bg-indigo-500/15 border border-indigo-500/25 text-indigo-200 text-3xs font-medium"
                                            >
                                                {item}
                                            </span>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="text-gray-500 italic">No key items carried currently</div>
                                )}
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
