import React, { useState, useCallback, useEffect } from 'react';
import {
    X, ImageIcon, Loader2, Paperclip, Palette, Wand2,
    BookOpen, Ghost, Sparkles, Send, Square, Dices, MapPin, Clock,
    Shirt, Smile, Heart, Shield, Activity, ChevronRight, Target, Check
} from 'lucide-react';
import clsx from 'clsx';
import CommandPalette from './CommandPalette';
import StreamingInput from './StreamingInput';
import TokenMeter from './TokenMeter';
import MentionPicker from '../story/MentionPicker';

export default function ChatInputContainer({
    pendingAttachment, setPendingAttachment, activeChat, targetCharacterId,
    setTargetCharacterId, characters, message, activeCommand, setActiveCommand,
    setMessage, handleSuggestClick, fileInputRef, handleAttachmentChange,
    textareaRef, handleTextChange, handleKeyDown, activeChatId,
    sendMessageMutation, isUploading, showMoreTools, setShowMoreTools,
    handleGenerateScene, isGeneratingScene, handleIllustrate, illustrateMutation,
    agenticMode, setAgenticMode, narrateMode, setNarrateMode,
    handleImpersonate, impersonateMutation, suggestReplyMutation, suggestJobId,
    handleSendMessage, canSend,
    isGeneratingReply, handleCancelStreaming,
    turnDirective, setTurnDirective
}) {
    const handleSelectMention = useCallback((item, startIndex, endIndex) => {
        const textBefore = message.slice(0, startIndex);
        const textAfter = message.slice(endIndex);
        const mentionText = `@${item.name} `;
        setMessage(textBefore + mentionText + textAfter);

        if (item._type === 'character' && setTargetCharacterId && characters?.some(c => c.id === item.id)) {
            setTargetCharacterId(item.id);
        }

        setTimeout(() => {
            const textarea = textareaRef.current;
            if (!textarea) return;
            textarea.focus();
            textarea.selectionStart = textarea.selectionEnd = startIndex + mentionText.length;
        }, 0);
    }, [message, setMessage, setTargetCharacterId, characters, textareaRef]);

    const [showFateMenu, setShowFateMenu] = useState(false);
    const [fateDifficulty, setFateDifficulty] = useState(13);
    const [fateSkill, setFateSkill] = useState('Persuasion');
    const [showStateDetails, setShowStateDetails] = useState(false);
    const [showSteerBar, setShowSteerBar] = useState(false);
    const [steerDraft, setSteerDraft] = useState('');

    const STEERING_PRESETS = [
        { label: '⚡ Escalate Drama', directive: 'Escalate emotional drama and heighten the stakes' },
        { label: '💖 Flustered & Shy', directive: 'Act noticeably flustered, shy, and stammering' },
        { label: '🚪 Sudden Twist', directive: 'Introduce an unexpected plot twist or interruption' },
        { label: '🔍 Sensory Detail', directive: 'Describe vivid sensory details, whispers, and ambiance' },
        { label: '⚔️ Tense Stand-off', directive: 'Shift into a tense, cautious stand-off with sharp dialogue' },
    ];

    const snapshot = activeChat?.state_snapshot || {};
    const actionChips = snapshot.last_director_decision?.suggested_action_chips || [];
    const hasState = Boolean(snapshot.location || snapshot.story_location || snapshot.time_of_day || snapshot.story_time || snapshot.mood || snapshot.character_mood || snapshot.outfit || snapshot.character_outfit || snapshot.relationship || snapshot.relationship_status);

    const handleRollFate = useCallback(() => {
        const roll = Math.floor(Math.random() * 20) + 1;
        let outcome = 'Failure';
        if (roll === 20) outcome = 'Critical Success!';
        else if (roll === 1) outcome = 'Critical Failure!';
        else if (roll >= fateDifficulty) outcome = 'Success!';
        else outcome = 'Failure';

        const fateText = `*Attempts a [${fateSkill}] check (DC ${fateDifficulty}) — Rolled ${roll} → ${outcome}* `;
        setMessage((prev) => (prev ? `${prev.trim()}\n${fateText}` : fateText));
        setShowFateMenu(false);
        setTimeout(() => textareaRef.current?.focus(), 10);
    }, [fateDifficulty, fateSkill, setMessage, textareaRef]);

    const handleInsertFateGate = useCallback(() => {
        const gateText = `[Fate Check Gate: Require ${fateSkill} (DC ${fateDifficulty})] `;
        setMessage((prev) => (prev ? `${prev.trim()}\n${gateText}` : gateText));
        setShowFateMenu(false);
        setTimeout(() => textareaRef.current?.focus(), 10);
    }, [fateDifficulty, fateSkill, setMessage, textareaRef]);

    useEffect(() => {
        const handleKeyDownEsc = (e) => {
            if (e.key === 'Escape') {
                if (showMoreTools) setShowMoreTools(false);
                if (showFateMenu) setShowFateMenu(false);
                if (showSteerBar) setShowSteerBar(false);
                if (showStateDetails) setShowStateDetails(false);
            }
        };
        window.addEventListener('keydown', handleKeyDownEsc);
        return () => window.removeEventListener('keydown', handleKeyDownEsc);
    }, [showMoreTools, showFateMenu, showSteerBar, showStateDetails, setShowMoreTools]);

    return (
        <div className="px-3 sm:px-4 lg:px-6 py-3 sm:py-4 pb-4 border-t border-white/5 bg-gray-900/40 backdrop-blur-md shrink-0">
            <div className="max-w-4xl mx-auto">
                {pendingAttachment && (
                    <div className="mb-2 flex items-center gap-2 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-xl text-sm text-blue-300">
                        <ImageIcon size={13} className="shrink-0" />
                        <span className="truncate flex-1 text-xs">{pendingAttachment.name}</span>
                        <button onClick={() => setPendingAttachment(null)} aria-label={`Remove attachment ${pendingAttachment.name}`} className="p-1 min-w-6 min-h-6 inline-flex items-center justify-center hover:text-red-400 transition-colors shrink-0">
                            <X size={13} />
                        </button>
                    </div>
                )}

                {/* Statekeeper Quick Bar */}
                {hasState && (
                    <div className="flex items-center gap-1.5 mb-2 text-3xs text-gray-400 overflow-x-auto custom-scrollbar py-0.5">
                        <button
                            type="button"
                            onClick={() => setShowStateDetails(v => !v)}
                            className="text-gray-400 hover:text-white font-semibold uppercase tracking-wider shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/5 border border-white/10 hover:bg-white/10 transition-colors"
                            title="Toggle Statekeeper details"
                        >
                            <Activity size={10} className="text-purple-400" />
                            <span>State</span>
                            <ChevronRight size={10} className={clsx("transition-transform", showStateDetails && "rotate-90")} />
                        </button>
                        {snapshot.location && (
                            <span className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-300">
                                <MapPin size={9} /> {snapshot.location}
                            </span>
                        )}
                        {snapshot.time_of_day && (
                            <span className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300">
                                <Clock size={9} /> {snapshot.time_of_day}
                            </span>
                        )}
                        {snapshot.outfit && (
                            <span className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300">
                                <Shirt size={9} /> {snapshot.outfit}
                            </span>
                        )}
                        {snapshot.mood && (
                            <span className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-300">
                                <Smile size={9} /> {snapshot.mood}
                            </span>
                        )}
                        {(snapshot.relationship_status || snapshot.relationship) && (
                            <span className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/20 text-rose-300">
                                <Heart size={9} /> {snapshot.relationship_status || snapshot.relationship}
                            </span>
                        )}
                    </div>
                )}

                {/* Statekeeper Details Popover */}
                {showStateDetails && hasState && (
                    <div className="mb-2 p-3 rounded-xl border border-purple-500/20 bg-gray-900/95 backdrop-blur-md text-xs text-gray-300 space-y-2 animate-in fade-in slide-in-from-top-1 shadow-xl">
                        <div className="font-semibold text-purple-300 text-3xs uppercase tracking-wider flex items-center justify-between pb-1.5 border-b border-white/5">
                            <span className="flex items-center gap-1.5">
                                <Shield size={11} className="text-purple-400" />
                                Active Statekeeper Snapshot
                            </span>
                            <button
                                type="button"
                                onClick={() => setShowStateDetails(false)}
                                className="text-gray-500 hover:text-white px-1"
                            >
                                ✕
                            </button>
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-3xs">
                            <div><strong className="text-gray-500 block">Location</strong><span className="text-gray-200">{snapshot.story_location || snapshot.location || '—'}</span></div>
                            <div><strong className="text-gray-500 block">Time of Day</strong><span className="text-gray-200">{snapshot.story_time || snapshot.time_of_day || '—'}</span></div>
                            <div><strong className="text-gray-500 block">Outfit</strong><span className="text-gray-200">{snapshot.character_outfit || snapshot.outfit || '—'}</span></div>
                            <div><strong className="text-gray-500 block">Mood</strong><span className="text-gray-200">{snapshot.character_mood || snapshot.mood || '—'}</span></div>
                            <div><strong className="text-gray-500 block">Relationship</strong><span className="text-gray-200">{snapshot.relationship_status || snapshot.relationship || '—'}</span></div>
                            {snapshot.inventory?.length > 0 && (
                                <div><strong className="text-gray-500 block">Key Items</strong><span className="text-gray-200">{snapshot.inventory.map(i => i.name).join(', ')}</span></div>
                            )}
                        </div>
                    </div>
                )}

                {/* In-Chat Suggested Action Chips */}
                {actionChips.length > 0 && (
                    <div className="flex items-center gap-1.5 mb-2 overflow-x-auto custom-scrollbar pb-1">
                        <span className="text-3xs text-gray-500 uppercase font-semibold shrink-0 flex items-center gap-1">
                            <Sparkles size={10} className="text-blue-400" /> Suggested:
                        </span>
                        {actionChips.map((chip, idx) => (
                            <button
                                key={idx}
                                type="button"
                                onClick={() => {
                                    setMessage(prev => (prev ? `${prev.trim()} ${chip}` : chip));
                                    setTimeout(() => textareaRef.current?.focus(), 10);
                                }}
                                className="shrink-0 text-xs px-2.5 py-1 rounded-full bg-gray-800/80 hover:bg-blue-600/20 border border-gray-700/60 hover:border-blue-500/40 text-gray-300 hover:text-blue-200 transition-colors"
                            >
                                {chip}
                            </button>
                        ))}
                    </div>
                )}

                {/* Staged Turn Directive Banner */}
                {turnDirective && (
                    <div className="mb-2 flex items-center justify-between gap-2 px-3 py-1.5 bg-purple-500/15 border border-purple-500/30 rounded-xl text-xs text-purple-200 animate-in fade-in">
                        <div className="flex items-center gap-1.5 truncate">
                            <Target size={13} className="text-purple-400 shrink-0" />
                            <span className="font-semibold text-3xs uppercase tracking-wider text-purple-300 shrink-0">Turn Directive:</span>
                            <span className="truncate italic text-purple-100">&ldquo;{turnDirective}&rdquo;</span>
                        </div>
                        <button
                            type="button"
                            onClick={() => setTurnDirective('')}
                            className="p-1 text-purple-300 hover:text-white hover:bg-white/10 rounded-lg transition-colors shrink-0"
                            title="Clear turn directive"
                            aria-label="Clear turn directive"
                        >
                            <X size={13} />
                        </button>
                    </div>
                )}

                {/* Steer Next Turn Bar */}
                {showSteerBar && (
                    <div className="mb-2 p-2.5 rounded-xl border border-purple-500/30 bg-gray-900/95 backdrop-blur-md space-y-2 text-xs shadow-xl animate-in fade-in slide-in-from-bottom-2">
                        <div className="flex items-center justify-between text-3xs font-semibold uppercase tracking-wider text-purple-300">
                            <span className="flex items-center gap-1.5">
                                <Target size={12} className="text-purple-400" />
                                Steer Next Turn (One-Shot Directive)
                            </span>
                            <button
                                type="button"
                                onClick={() => setShowSteerBar(false)}
                                className="text-gray-500 hover:text-white p-0.5"
                            >
                                ✕
                            </button>
                        </div>
                        <div className="flex items-center gap-1.5 overflow-x-auto custom-scrollbar pb-1">
                            {STEERING_PRESETS.map((preset, idx) => (
                                <button
                                    key={idx}
                                    type="button"
                                    onClick={() => {
                                        setTurnDirective(preset.directive);
                                        setShowSteerBar(false);
                                    }}
                                    className="shrink-0 px-2.5 py-1 rounded-full text-3xs font-medium bg-purple-500/15 hover:bg-purple-500/30 border border-purple-500/30 text-purple-200 transition-colors"
                                >
                                    {preset.label}
                                </button>
                            ))}
                        </div>
                        <div className="flex items-center gap-2">
                            <input
                                type="text"
                                value={steerDraft}
                                onChange={(e) => setSteerDraft(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        e.preventDefault();
                                        if (steerDraft.trim()) {
                                            setTurnDirective(steerDraft.trim());
                                            setSteerDraft('');
                                            setShowSteerBar(false);
                                        }
                                    }
                                }}
                                placeholder="Custom directive: e.g. speak with quiet fury, sudden knock on door..."
                                className="flex-1 bg-gray-800/90 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500"
                            />
                            <button
                                type="button"
                                onClick={() => {
                                    if (steerDraft.trim()) {
                                        setTurnDirective(steerDraft.trim());
                                        setSteerDraft('');
                                        setShowSteerBar(false);
                                    }
                                }}
                                disabled={!steerDraft.trim()}
                                className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white rounded-lg text-xs font-semibold transition-colors shrink-0"
                            >
                                Set Directive
                            </button>
                        </div>
                    </div>
                )}

                <div className="relative">
                    {activeChat?.additional_character_ids?.length > 0 && (
                        <div className="absolute -top-10 right-0 flex items-center gap-2 bg-gray-900/80 backdrop-blur border border-gray-700 rounded-lg px-2 py-1 shadow-xl">
                            <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Reply as:</span>
                            <select
                                value={targetCharacterId}
                                onChange={(e) => setTargetCharacterId(e.target.value)}
                                className="bg-transparent text-xs text-blue-300 font-medium focus:outline-none appearance-none cursor-pointer"
                            >
                                <option value="">{activeChat.character_id ? characters.find(c => c.id === activeChat.character_id)?.name || 'Default' : 'Default'}</option>
                                {activeChat.additional_character_ids.map(id => {
                                    const c = characters.find(char => char.id === id);
                                    return c ? <option key={c.id} value={c.id}>{c.name}</option> : null;
                                })}
                            </select>
                            <div className="pointer-events-none text-gray-500">
                                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                            </div>
                        </div>
                    )}
                    <CommandPalette
                        message={message}
                        activeCommand={activeCommand}
                        onSelect={(c) => {
                            if (c.noArgs) {
                                setMessage('');
                                textareaRef.current?.blur();
                                if (c.cmd === '/suggest') handleSuggestClick();
                            } else {
                                setActiveCommand(c);
                                setMessage('');
                                textareaRef.current?.focus();
                            }
                        }}
                    />
                    <MentionPicker
                        textareaRef={textareaRef}
                        editorContent={message}
                        onSelect={handleSelectMention}
                        placement="top"
                    />
                    <input ref={fileInputRef} type="file" aria-label="Attach image" accept="image/*" onChange={handleAttachmentChange} className="sr-only" />
                    
                    <StreamingInput
                        textareaRef={textareaRef}
                        value={message}
                        onChange={handleTextChange}
                        onKeyDown={handleKeyDown}
                        placeholder={isGeneratingReply ? 'AI is generating a reply...' : (activeCommand ? activeCommand.argPlaceholder : (activeChatId ? 'Type a message...' : 'Select a chat to start...'))}
                        disabled={isGeneratingReply || sendMessageMutation.isPending || !activeChatId}
                        activeCommand={activeCommand}
                        onClearCommand={() => { setActiveCommand(null); setMessage(activeCommand.cmd + ' ' + message); }}
                    />

                    {/* Left Button */}
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isUploading}
                        className="absolute left-2 sm:left-3 bottom-2.5 sm:bottom-3 p-1.5 sm:p-2 text-gray-400 hover:text-blue-400 transition-colors rounded-xl hover:bg-blue-500/10 disabled:opacity-50"
                        title="Attach image"
                    >
                        {isUploading ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
                    </button>

                    {/* Right Buttons Group: Streamlined Quick Suggest + Story Tools Menu + TokenMeter + Send */}
                    <div className="absolute right-2 sm:right-3 bottom-2.5 sm:bottom-3 flex items-center gap-1">
                        {/* Quick Action: Auto-Suggest Reply */}
                        <button
                            type="button"
                            onClick={handleSuggestClick}
                            disabled={!activeChatId || suggestReplyMutation.isPending || suggestJobId}
                            className={clsx(
                                "p-1.5 sm:p-2 transition-all rounded-xl",
                                (suggestReplyMutation.isPending || suggestJobId)
                                    ? "text-blue-400 bg-blue-500/10 cursor-not-allowed"
                                    : (activeChatId ? "text-blue-400 hover:text-white hover:bg-blue-600/50" : "text-gray-600 cursor-not-allowed")
                            )}
                            title="Auto-suggest reply"
                            aria-label="Auto-suggest reply"
                        >
                            {(suggestReplyMutation.isPending || suggestJobId) 
                                ? <Loader2 size={16} className="animate-spin" />
                                : <Sparkles size={16} />}
                        </button>

                        {/* Unified Story & Roleplay Tools Menu Trigger */}
                        <button
                            type="button"
                            onClick={() => setShowMoreTools(v => !v)}
                            className={clsx(
                                "relative p-1.5 sm:p-2 transition-all rounded-xl",
                                (showMoreTools || turnDirective || showSteerBar || showFateMenu)
                                    ? "text-purple-300 bg-purple-500/20 shadow-[0_0_10px_rgba(168,85,247,0.25)] border border-purple-500/30"
                                    : (agenticMode || narrateMode)
                                        ? "text-purple-400 hover:text-purple-300 hover:bg-purple-500/10"
                                        : "text-gray-400 hover:text-white hover:bg-white/10"
                            )}
                            title="Story & Roleplay Tools"
                            aria-label="Story & Roleplay Tools"
                        >
                            <Wand2 size={16} />
                            {(turnDirective || agenticMode || narrateMode) && (
                                <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
                            )}
                        </button>

                        {/* Unified Categorized Action Menu Popover */}
                        {showMoreTools && (
                            <>
                                <div
                                    className="fixed inset-0 z-40"
                                    onClick={() => setShowMoreTools(false)}
                                    aria-hidden="true"
                                />
                                <div className="absolute bottom-full right-0 mb-2.5 w-72 sm:w-80 bg-gray-900/95 backdrop-blur-xl border border-gray-700/60 rounded-2xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-2 text-xs">
                                    <div className="flex items-center justify-between px-3.5 py-2.5 bg-gray-800/40 border-b border-gray-700/50">
                                        <span className="font-semibold text-gray-300 text-3xs uppercase tracking-wider flex items-center gap-1.5">
                                            <Wand2 size={12} className="text-purple-400" />
                                            Story & Roleplay Tools
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => setShowMoreTools(false)}
                                            className="text-gray-500 hover:text-white p-0.5 rounded transition-colors"
                                            aria-label="Close tools menu"
                                        >
                                            <X size={13} />
                                        </button>
                                    </div>

                                    <div className="p-2 space-y-2.5 max-h-[75vh] overflow-y-auto custom-scrollbar">
                                        {/* Section 1: Visuals & Media */}
                                        <div>
                                            <div className="px-2 py-0.5 text-3xs font-bold text-gray-500 uppercase tracking-wider">
                                                Visuals & Media
                                            </div>
                                            <div className="grid grid-cols-2 gap-1.5 mt-1">
                                                <button
                                                    type="button"
                                                    onClick={() => { setShowMoreTools(false); handleGenerateScene(); }}
                                                    disabled={isGeneratingScene || !activeChatId}
                                                    className="flex items-center gap-2 p-2 rounded-xl bg-white/5 hover:bg-green-500/10 border border-transparent hover:border-green-500/20 text-gray-200 hover:text-green-300 transition-colors disabled:opacity-50 text-left"
                                                >
                                                    {isGeneratingScene ? <Loader2 size={15} className="text-green-400 animate-spin shrink-0" /> : <ImageIcon size={15} className="text-green-400 shrink-0" />}
                                                    <div className="min-w-0">
                                                        <div className="text-xs font-medium truncate">Scene</div>
                                                        <div className="text-3xs text-gray-500 truncate">Backdrop image</div>
                                                    </div>
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => { setShowMoreTools(false); handleIllustrate(); }}
                                                    disabled={illustrateMutation.isPending || !activeChatId}
                                                    className="flex items-center gap-2 p-2 rounded-xl bg-white/5 hover:bg-pink-500/10 border border-transparent hover:border-pink-500/20 text-gray-200 hover:text-pink-300 transition-colors disabled:opacity-50 text-left"
                                                >
                                                    {illustrateMutation.isPending ? <Loader2 size={15} className="text-pink-400 animate-spin shrink-0" /> : <Palette size={15} className="text-pink-400 shrink-0" />}
                                                    <div className="min-w-0">
                                                        <div className="text-xs font-medium truncate">Illustrate</div>
                                                        <div className="text-3xs text-gray-500 truncate">Draw moment</div>
                                                    </div>
                                                </button>
                                            </div>
                                        </div>

                                        {/* Section 2: Director & Roleplay Mechanics */}
                                        <div>
                                            <div className="px-2 py-0.5 text-3xs font-bold text-gray-500 uppercase tracking-wider">
                                                Director & Mechanics
                                            </div>
                                            <div className="grid grid-cols-2 gap-1.5 mt-1">
                                                <button
                                                    type="button"
                                                    onClick={() => { setShowMoreTools(false); setShowSteerBar(true); }}
                                                    className={clsx(
                                                        "flex items-center gap-2 p-2 rounded-xl border text-left transition-colors",
                                                        turnDirective || showSteerBar
                                                            ? "bg-purple-500/15 border-purple-500/30 text-purple-200"
                                                            : "bg-white/5 border-transparent hover:bg-purple-500/10 hover:border-purple-500/20 text-gray-200 hover:text-purple-300"
                                                    )}
                                                >
                                                    <Target size={15} className="text-purple-400 shrink-0" />
                                                    <div className="min-w-0">
                                                        <div className="text-xs font-medium truncate flex items-center justify-between">
                                                            <span>Steer Turn</span>
                                                            {turnDirective && <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />}
                                                        </div>
                                                        <div className="text-3xs text-gray-500 truncate">Inject directive</div>
                                                    </div>
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => { setShowMoreTools(false); setShowFateMenu(true); }}
                                                    className={clsx(
                                                        "flex items-center gap-2 p-2 rounded-xl border text-left transition-colors",
                                                        showFateMenu
                                                            ? "bg-amber-500/15 border-amber-500/30 text-amber-200"
                                                            : "bg-white/5 border-transparent hover:bg-amber-500/10 hover:border-amber-500/20 text-gray-200 hover:text-amber-300"
                                                    )}
                                                >
                                                    <Dices size={15} className="text-amber-400 shrink-0" />
                                                    <div className="min-w-0">
                                                        <div className="text-xs font-medium truncate">Fate / D20</div>
                                                        <div className="text-3xs text-gray-500 truncate">Skill & DC check</div>
                                                    </div>
                                                </button>
                                            </div>
                                        </div>

                                        {/* Section 3: Player Co-Pilot */}
                                        <div>
                                            <div className="px-2 py-0.5 text-3xs font-bold text-gray-500 uppercase tracking-wider">
                                                Player Co-Pilot
                                            </div>
                                            <div className="grid grid-cols-2 gap-1.5 mt-1">
                                                <button
                                                    type="button"
                                                    onClick={() => { setShowMoreTools(false); handleSuggestClick(); }}
                                                    disabled={!activeChatId || suggestReplyMutation.isPending || suggestJobId}
                                                    className="flex items-center gap-2 p-2 rounded-xl bg-white/5 hover:bg-blue-500/10 border border-transparent hover:border-blue-500/20 text-gray-200 hover:text-blue-300 transition-colors disabled:opacity-50 text-left"
                                                >
                                                    {(suggestReplyMutation.isPending || suggestJobId)
                                                        ? <Loader2 size={15} className="text-blue-400 animate-spin shrink-0" />
                                                        : <Sparkles size={15} className="text-blue-400 shrink-0" />}
                                                    <div className="min-w-0">
                                                        <div className="text-xs font-medium truncate">Suggest</div>
                                                        <div className="text-3xs text-gray-500 truncate">AI reply draft</div>
                                                    </div>
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => { setShowMoreTools(false); handleImpersonate(); }}
                                                    disabled={!activeChatId || impersonateMutation.isPending}
                                                    className="flex items-center gap-2 p-2 rounded-xl bg-white/5 hover:bg-purple-500/10 border border-transparent hover:border-purple-500/20 text-gray-200 hover:text-purple-300 transition-colors disabled:opacity-50 text-left"
                                                >
                                                    {impersonateMutation.isPending
                                                        ? <Loader2 size={15} className="text-purple-400 animate-spin shrink-0" />
                                                        : <Ghost size={15} className="text-purple-400 shrink-0" />}
                                                    <div className="min-w-0">
                                                        <div className="text-xs font-medium truncate">Impersonate</div>
                                                        <div className="text-3xs text-gray-500 truncate">Speak as you</div>
                                                    </div>
                                                </button>
                                            </div>
                                        </div>

                                        {/* Section 4: Engine Modes */}
                                        <div className="pt-1.5 border-t border-white/5">
                                            <div className="px-2 py-0.5 text-3xs font-bold text-gray-500 uppercase tracking-wider">
                                                Engine Modes
                                            </div>
                                            <div className="space-y-1.5 mt-1">
                                                <button
                                                    type="button"
                                                    onClick={() => setAgenticMode(!agenticMode)}
                                                    className={clsx(
                                                        "w-full flex items-center justify-between p-2 rounded-xl border text-left transition-colors",
                                                        agenticMode
                                                            ? "bg-purple-500/15 border-purple-500/30 text-purple-200"
                                                            : "bg-white/5 border-transparent hover:bg-white/10 text-gray-300"
                                                    )}
                                                >
                                                    <div className="flex items-center gap-2">
                                                        <Wand2 size={14} className={agenticMode ? "text-purple-400" : "text-gray-500"} />
                                                        <div>
                                                            <div className="text-xs font-medium">Autonomous Agentic</div>
                                                            <div className="text-3xs text-gray-500">Autonomous tool chaining & visual generation</div>
                                                        </div>
                                                    </div>
                                                    <span className={clsx(
                                                        "px-1.5 py-0.5 rounded text-3xs font-bold uppercase tracking-wider",
                                                        agenticMode ? "bg-purple-500/30 text-purple-300" : "bg-white/5 text-gray-500"
                                                    )}>
                                                        {agenticMode ? 'ON' : 'OFF'}
                                                    </span>
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => setNarrateMode(!narrateMode)}
                                                    className={clsx(
                                                        "w-full flex items-center justify-between p-2 rounded-xl border text-left transition-colors",
                                                        narrateMode
                                                            ? "bg-purple-500/15 border-purple-500/30 text-purple-200"
                                                            : "bg-white/5 border-transparent hover:bg-white/10 text-gray-300"
                                                    )}
                                                >
                                                    <div className="flex items-center gap-2">
                                                        <BookOpen size={14} className={narrateMode ? "text-purple-400" : "text-gray-500"} />
                                                        <div>
                                                            <div className="text-xs font-medium">Scene Narrator</div>
                                                            <div className="text-3xs text-gray-500">Enforce 3rd-person story narration</div>
                                                        </div>
                                                    </div>
                                                    <span className={clsx(
                                                        "px-1.5 py-0.5 rounded text-3xs font-bold uppercase tracking-wider",
                                                        narrateMode ? "bg-purple-500/30 text-purple-300" : "bg-white/5 text-gray-500"
                                                    )}>
                                                        {narrateMode ? 'ON' : 'OFF'}
                                                    </span>
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </>
                        )}

                        {/* Fate / Skill Check Gate Popover */}
                        {showFateMenu && (
                            <>
                                <div
                                    className="fixed inset-0 z-40"
                                    onClick={() => setShowFateMenu(false)}
                                    aria-hidden="true"
                                />
                                <div className="absolute bottom-full right-0 mb-3 w-80 bg-gray-900/95 backdrop-blur-xl border border-amber-500/30 rounded-2xl shadow-2xl p-3 z-50 animate-in fade-in slide-in-from-bottom-2 text-xs">
                                    <div className="flex items-center justify-between pb-2 border-b border-white/10 mb-2">
                                        <span className="font-bold text-amber-300 flex items-center gap-1.5 uppercase tracking-wider text-3xs">
                                            <Dices size={14} className="text-amber-400" />
                                            Fate / Skill Check Gate
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => setShowFateMenu(false)}
                                            className="text-gray-500 hover:text-white p-0.5 rounded"
                                        >
                                            ✕
                                        </button>
                                    </div>
                                    <div className="space-y-2.5">
                                        <div>
                                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                                Tested Skill / Attribute
                                            </label>
                                            <select
                                                value={fateSkill}
                                                onChange={(e) => setFateSkill(e.target.value)}
                                                className="w-full bg-gray-800 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-amber-500"
                                            >
                                                {['Persuasion', 'Athletics', 'Stealth', 'Arcana', 'Perception', 'Deception', 'Insight', 'Survival', 'Luck / Fate'].map(s => (
                                                    <option key={s} value={s}>{s}</option>
                                                ))}
                                            </select>
                                        </div>
                                        <div>
                                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                                Difficulty Class (DC): <span className="text-amber-300 font-bold">{fateDifficulty}</span>
                                            </label>
                                            <div className="grid grid-cols-5 gap-1">
                                                {[
                                                    { dc: 10, label: '10 Easy' },
                                                    { dc: 13, label: '13 Med' },
                                                    { dc: 15, label: '15 Hard' },
                                                    { dc: 18, label: '18 V.Hard' },
                                                    { dc: 20, label: '20 Ext' },
                                                ].map(({ dc, label }) => (
                                                    <button
                                                        key={dc}
                                                        type="button"
                                                        onClick={() => setFateDifficulty(dc)}
                                                        className={clsx(
                                                            "py-1 px-0.5 rounded text-3xs font-semibold border transition-colors text-center",
                                                            fateDifficulty === dc
                                                                ? "bg-amber-500/20 border-amber-500/40 text-amber-300"
                                                                : "bg-gray-800/60 border-white/5 text-gray-400 hover:text-white"
                                                        )}
                                                    >
                                                        {label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                        <div className="pt-2 border-t border-white/5 grid grid-cols-2 gap-2">
                                            <button
                                                type="button"
                                                onClick={handleRollFate}
                                                className="flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 font-semibold text-xs transition-colors"
                                                title="Roll d20 now and insert outcome into your message"
                                            >
                                                <Dices size={14} />
                                                <span>Roll d20 Now</span>
                                            </button>
                                            <button
                                                type="button"
                                                onClick={handleInsertFateGate}
                                                className="flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-200 font-semibold text-xs transition-colors"
                                                title="Enforce a Fate Check for AI on next response"
                                            >
                                                <Shield size={14} />
                                                <span>Set Gate</span>
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </>
                        )}
                        
                        <div className="flex items-center">
                            <TokenMeter text={message} />
                            {isGeneratingReply ? (
                                <button
                                    onClick={handleCancelStreaming}
                                    aria-label="Stop generation"
                                    title="Stop generation"
                                    className="p-1.5 sm:p-2 transition-all rounded-xl bg-red-600/80 hover:bg-red-500 text-white shadow-[0_0_12px_rgba(239,68,68,0.4)] hover:scale-105 flex items-center justify-center animate-pulse"
                                >
                                    <Square size={16} fill="currentColor" />
                                </button>
                            ) : (
                                <button
                                    onClick={handleSendMessage}
                                    disabled={!canSend}
                                    aria-label="Send message"
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-all rounded-xl",
                                        canSend
                                            ? "bg-blue-600 text-white shadow-[0_0_12px_rgba(37,99,235,0.4)] hover:bg-blue-500 hover:scale-105"
                                            : "bg-gray-800 text-gray-500 cursor-not-allowed"
                                    )}
                                >
                                    {sendMessageMutation.isPending
                                        ? <Loader2 size={16} className="animate-spin" />
                                        : <Send size={16} className={canSend ? "translate-x-0.5 -translate-y-0.5" : ""} />
                                    }
                                </button>
                            )}
                        </div>
                    </div>
                </div>
                <div className="mt-1.5 hidden sm:flex items-center justify-between px-1 text-xs text-gray-600">
                    <span><kbd className="font-mono bg-gray-800 px-1 py-0.5 rounded border border-gray-700 text-gray-500">Enter</kbd> to send · <kbd className="font-mono bg-gray-800 px-1 py-0.5 rounded border border-gray-700 text-gray-500">Shift+Enter</kbd> for newline</span>
                    <span className="flex items-center gap-2">
                        {narrateMode && (
                            <span className="text-purple-400">📖 Narrate</span>
                        )}
                        <span className={clsx("transition-colors", agenticMode ? "text-purple-400" : "text-gray-600")}>
                            {agenticMode ? '⚡ Agentic' : 'Standard'}
                        </span>
                    </span>
                </div>
            </div>
        </div>
    );
}
