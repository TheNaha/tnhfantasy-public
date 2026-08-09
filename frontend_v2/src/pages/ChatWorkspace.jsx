import React, { useState, useEffect, useRef, useCallback, memo, useMemo } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
    MessageSquare, Send, Image as ImageIcon, Settings,
    PanelRightClose, PanelRightOpen, PanelLeftClose, PanelLeftOpen, Paperclip, Sparkles,
    Plus, Loader2, Trash2, Edit3, Edit2, BookOpen, Check, Wand2,
    User, X, ChevronRight, ChevronLeft, RotateCcw, Clock, MapPin, Menu,
    Pencil, Undo2, Activity, Brain, Download, Pin, PinOff, Ghost,
    MoreHorizontal, Palette
} from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useLocation } from 'react-router-dom';
import api from '../api/client';
import {
    useMessages, useChats, useSendMessage, useChat,
    useCreateChat, useDeleteChat, useLorebooks, useCharacters,
    useRenameChat, useUpdateChat, getAvatarUrl, useSuggestReply,
    useLLMAvailableModels, useLLMDefaultProvider, useChatSystemPrompt,
    useCharacterCollection, useEditMessage, useRollbackChat,
    useRegenerateReply, useChatJobs, usePatchCharacter,
    useImpersonateMessage, usePinMessage, useSwipeMessage, useChatImages,
    useIllustrateChat
} from '../hooks/useWorldVault';
import { useLLMJobResult } from '../hooks/useLLMJobResult';
import { useVirtualizer } from '@tanstack/react-virtual';
import { filesApi } from '../api/files';
import { useCollections } from '../hooks/useCollections';
import { addImagesToCollection } from '../api/collectionsApi';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useWebSocket, EventTypes } from '../api/websocket';
import {
    useActiveChatStreams,
    setStreamingJob,
    clearStreamingJob,
    getStreamingJob,
} from '../hooks/useStreamingJobs';
import { useQueryClient } from '@tanstack/react-query';
import { useConfirmation } from '../store/confirmationStore';
import { parseTavernMessage } from '../utils/tavernUtils';
import { useSettings } from '../store/settingsStore';
import SceneGallery from '../components/SceneGallery';
import BottomTabBar from '../components/BottomTabBar';


const COMMANDS = [
    { cmd: '/silent', desc: 'Send silently without triggering AI reply', icon: '🤫', argPlaceholder: 'Message text...' },
    { cmd: '/story', desc: 'Insert a narrative event', icon: '📖', argPlaceholder: 'Story text...' },
    { cmd: '/puppet', desc: 'Speak as the character', icon: '🎭', argPlaceholder: 'Character speech...' },
    { cmd: '/time', desc: 'Update story time', icon: '⏰', argPlaceholder: 'e.g. Midnight, +2 hours...' },
    { cmd: '/location', desc: 'Update story location', icon: '📍', argPlaceholder: 'e.g. The Library...' },
    { cmd: '/action', desc: 'Perform an action', icon: '🏃', argPlaceholder: 'Action description...' },
    { cmd: '/suggest', desc: 'Auto-fill a suggested response', icon: '🪄', noArgs: true }
];

// ---------------------------------------------------------------------------
// TavernMessage — renders narrative/dialogue with segment styling
// ---------------------------------------------------------------------------
const TavernMessage = memo(function TavernMessage({ content, alignRight }) {
    const segments = parseTavernMessage(content);
    if (!segments.length) return <span>{content}</span>;
    return (
        <div className={clsx("flex flex-col gap-2.5 w-full", alignRight && "items-end")}>
            {segments.map((seg, i) => {
                if (seg.type === 'action') {
                    return (
                        <div key={i} className="text-gray-400 italic font-medium opacity-90 text-[13px] px-1 py-0.5 leading-relaxed">
                            {seg.content}
                        </div>
                    );
                }
                if (seg.type === 'speech') {
                    return (
                        <div key={i} className={clsx("px-4 py-3 rounded-2xl bg-gray-800 border border-gray-700/50 text-gray-100 font-medium tracking-wide shadow-sm w-fit max-w-full break-words", alignRight ? "rounded-tr-sm" : "rounded-tl-sm")}>
                            "{seg.content}"
                        </div>
                    );
                }
                return (
                    <div key={i} className={clsx("px-4 py-3 rounded-2xl bg-gray-800/40 border border-gray-700/30 text-gray-300 text-sm shadow-sm w-fit max-w-full break-words leading-relaxed", alignRight ? "rounded-tr-sm" : "rounded-tl-sm")}>
                        {seg.content}
                    </div>
                );
            })}
        </div>
    );
});

// ---------------------------------------------------------------------------
// GreetingPickerModal — shown when a character has multiple first messages
// ---------------------------------------------------------------------------
function GreetingPickerModal({ character, onSelect, onClose }) {
    const greetings = [
        character.first_mes,
        ...(character.alternate_greetings || [])
    ].filter(Boolean);

    if (greetings.length <= 1) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
            <motion.div
                initial={{ y: '100%', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: '100%', opacity: 0 }}
                className="w-full max-w-lg bg-gray-900 border border-white/10 rounded-3xl shadow-2xl overflow-hidden"
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
                    <div>
                        <h3 className="font-bold text-gray-100">Choose Opening</h3>
                        <p className="text-xs text-gray-500 mt-0.5">
                            {character.name} has {greetings.length} opening messages. Pick one to start the chat.
                        </p>
                    </div>
                    <button onClick={onClose} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                        <X size={18} />
                    </button>
                </div>
                <div className="p-4 space-y-3 max-h-[50vh] overflow-y-auto custom-scrollbar">
                    {greetings.map((greeting, idx) => (
                        <button
                            key={idx}
                            onClick={() => onSelect(greeting)}
                            className="w-full text-left p-4 rounded-xl bg-gray-800/50 border border-white/5 hover:border-blue-500/40 hover:bg-blue-500/5 transition-all text-sm text-gray-300 group"
                        >
                            <div className="flex items-start gap-3">
                                <span className="text-[10px] font-bold text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded shrink-0 mt-0.5">
                                    {idx === 0 ? 'Default' : `Alt ${idx}`}
                                </span>
                                <p className="line-clamp-3 leading-relaxed">{greeting}</p>
                                <ChevronRight size={16} className="text-gray-600 group-hover:text-blue-400 shrink-0 mt-0.5 transition-colors" />
                            </div>
                        </button>
                    ))}
                </div>
            </motion.div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// NewChatModal — shown to configure character/lorebooks before creating chat
// ---------------------------------------------------------------------------
function NewChatModal({ characters, lorebooks, onCreate, onClose }) {
    const [selectedCharacter, setSelectedCharacter] = useState(null);
    const [selectedLorebooks, setSelectedLorebooks] = useState([]);
    const [chatName, setChatName] = useState('New Chat');
    const [personaName, setPersonaName] = useState('');
    const [storyTime, setStoryTime] = useState('');
    const [storyLocation, setStoryLocation] = useState('');

    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        if (selectedCharacter) {
            setChatName(`Chat with ${selectedCharacter.name}`);
            
            // Basic heuristic to suggest time/location
            const scenario = selectedCharacter.scenario || '';
            
            if (selectedCharacter.default_time) {
                setStoryTime(selectedCharacter.default_time);
            } else if (scenario.toLowerCase().includes('night') || scenario.toLowerCase().includes('evening')) {
                setStoryTime('Night');
            } else if (scenario.toLowerCase().includes('morning') || scenario.toLowerCase().includes('day')) {
                setStoryTime('Morning');
            } else {
                setStoryTime('');
            }
            
            if (selectedCharacter.default_location) {
                setStoryLocation(selectedCharacter.default_location);
            } else if (scenario.toLowerCase().includes('tavern')) {
                setStoryLocation('Tavern');
            } else if (scenario.toLowerCase().includes('castle')) {
                setStoryLocation('Castle');
            } else if (scenario.toLowerCase().includes('forest')) {
                setStoryLocation('Forest');
            } else if (scenario.toLowerCase().includes('city')) {
                setStoryLocation('City');
            } else {
                setStoryLocation('');
            }
        } else {
            setChatName('New Chat');
            setStoryTime('');
            setStoryLocation('');
        }
    }, [selectedCharacter]);
    /* eslint-enable react-hooks/set-state-in-effect */

    const toggleLorebook = (id) => {
        if (selectedLorebooks.includes(id)) {
            setSelectedLorebooks(selectedLorebooks.filter(l => l !== id));
        } else {
            setSelectedLorebooks([...selectedLorebooks, id]);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
            <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="w-full max-w-lg bg-gray-900 border border-white/10 rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                    <h3 className="font-bold text-gray-100">Create New Chat</h3>
                    <button onClick={onClose} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                        <X size={18} />
                    </button>
                </div>
                
                <div className="p-6 space-y-6 overflow-y-auto custom-scrollbar">
                    {/* Chat Name */}
                    <div className="space-y-2">
                        <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Chat Name</label>
                        <input
                            type="text"
                            value={chatName}
                            onChange={(e) => setChatName(e.target.value)}
                            className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-colors"
                            placeholder="e.g. Tavern Encounter"
                        />
                    </div>
                    
                    {/* Persona Name */}
                    <div className="space-y-2">
                        <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Your Persona (Optional)</label>
                        <input
                            type="text"
                            value={personaName}
                            onChange={(e) => setPersonaName(e.target.value)}
                            className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-colors"
                            placeholder="e.g. Wanderer"
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Character (Optional)</label>
                        <select
                            value={selectedCharacter?.id || ''}
                            onChange={(e) => setSelectedCharacter(characters.find(c => c.id === e.target.value) || null)}
                            className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:border-blue-500/50 transition-colors appearance-none"
                        >
                            <option value="">No Character</option>
                            {characters.map(c => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                        </select>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-3">
                         <div className="space-y-2">
                            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Time</label>
                            <input type="text" value={storyTime} onChange={(e) => setStoryTime(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200" placeholder="e.g. Day" />
                         </div>
                         <div className="space-y-2">
                            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Location</label>
                            <input type="text" value={storyLocation} onChange={(e) => setStoryLocation(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200" placeholder="e.g. Tavern" />
                         </div>
                    </div>

                    {lorebooks.length > 0 && (
                        <div className="space-y-2">
                            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Context Lorebooks</label>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {lorebooks.map(lb => {
                                    const isActive = selectedLorebooks.includes(lb.id);
                                    return (
                                        <button
                                            key={lb.id}
                                            onClick={() => toggleLorebook(lb.id)}
                                            className={`text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors border ${isActive ? "bg-blue-500/20 text-blue-300 border-blue-500/30" : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border-transparent"}`}
                                        >
                                            {isActive ? <Check size={14} className="text-blue-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}
                                            <span className="truncate">{lb.name}</span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>

                <div className="p-4 border-t border-white/5 bg-gray-900/60 shrink-0 flex justify-end gap-3">
                    <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-400 hover:text-white transition-colors">
                        Cancel
                    </button>
                    <button 
                        onClick={() => onCreate({ chatName: chatName.trim() || 'New Chat', characterId: selectedCharacter?.id || null, personaName: personaName.trim() || null, storyTime, storyLocation, selectedLorebooks })}
                        className="px-5 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white rounded-xl transition-all shadow-lg"
                    >
                        Create
                    </button>
                </div>
            </motion.div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// ContextField — inline editable generic field in the context panel
// ---------------------------------------------------------------------------
function ContextField({ label, icon: Icon, value, placeholder, onSave }) {
    const [editing, setEditing] = useState(false);
    const [localValue, setLocalValue] = useState(value || '');
    const inputRef = useRef(null);

    // eslint-disable-next-line react-hooks/set-state-in-effect
    useEffect(() => { setLocalValue(value || ''); }, [value]);

    const commit = () => {
        setEditing(false);
        const trimmed = localValue.trim();
        if (trimmed !== (value || '')) {
            onSave(trimmed || null);
        } else {
            setLocalValue(value || '');
        }
    };

    return (
        <div className="glass-panel p-4 rounded-xl border border-white/5">
            <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                <Icon size={12} /> {label}
            </h4>
            {editing ? (
                <input
                    ref={inputRef}
                    type="text"
                    value={localValue}
                    onChange={e => setLocalValue(e.target.value)}
                    onBlur={commit}
                    onKeyDown={e => {
                        if (e.key === 'Enter') commit();
                        if (e.key === 'Escape') {
                            setLocalValue(value || '');
                            setEditing(false);
                        }
                    }}
                    className="w-full bg-gray-950/50 border border-blue-500/50 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500/50"
                />
            ) : (
                <div
                    onClick={() => { setEditing(true); setTimeout(() => inputRef.current?.focus(), 0); }}
                    className="group cursor-pointer rounded-lg px-3 py-1.5 -mx-3 hover:bg-white/5 transition-colors flex items-center justify-between"
                >
                    <span className={clsx("text-sm truncate", value ? "text-gray-200" : "text-gray-500 italic")}>
                        {value || placeholder}
                    </span>
                    <Edit2 size={12} className="text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// CharacterDetailsModal — shows character description/persona in chat
// ---------------------------------------------------------------------------
function CharacterDetailsModal({ character, onClose }) {
    if (!character) return null;
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
            <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="w-full max-w-2xl bg-gray-900 border border-white/10 rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                    <h3 className="font-bold text-gray-100 flex items-center gap-2">
                        <User size={16} className="text-blue-400" />
                        {character.name}
                    </h3>
                    <button onClick={onClose} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                        <X size={18} />
                    </button>
                </div>
                
                <div className="p-6 overflow-y-auto custom-scrollbar space-y-6">
                    {character.description && (
                        <div>
                            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Description</h4>
                            <div className="bg-gray-800/50 rounded-xl p-4 text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                {character.description}
                            </div>
                        </div>
                    )}
                    {character.personality && (
                        <div>
                            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Personality</h4>
                            <div className="bg-gray-800/50 rounded-xl p-4 text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                {character.personality}
                            </div>
                        </div>
                    )}
                    {character.scenario && (
                        <div>
                            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Scenario</h4>
                            <div className="bg-gray-800/50 rounded-xl p-4 text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                {character.scenario}
                            </div>
                        </div>
                    )}
                    {(!character.description && !character.personality && !character.scenario) && (
                        <p className="text-gray-500 italic text-center py-4">No detailed information available.</p>
                    )}
                </div>
            </motion.div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Memoized Message Item
// ---------------------------------------------------------------------------
const MessageItem = memo(function MessageItem({ msg, linkedCharacter, activeChat, canRegenerate, onEdit, onRegenerate, onRollback, onPin, onSwipe, onAvatarClick }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(msg.content);

    const meta = msg.message_metadata || {};
    const isNarrator = msg.kind === 'narrator' || meta.source === 'narrator';
    const alternates = meta.alternates || null;
    const activeIndex = meta.active_index ?? 0;
    const altCount = alternates ? alternates.length : 0;
    if (meta.source === 'world_state') {
        return (
            <div className="flex items-center gap-3 w-full max-w-full self-center my-1.5 select-none">
                <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-600/50 to-transparent" />
                <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-gray-800/70 border border-gray-700/50 text-[10px] text-gray-400 tracking-wide whitespace-nowrap">
                    {meta.location && (
                        <span className="flex items-center gap-1.5">
                            <MapPin size={10} className="text-amber-400" />
                            {meta.old_location && <span className="opacity-50">{meta.old_location} →</span>}
                            <span className="font-medium text-amber-100/90">{meta.location}</span>
                        </span>
                    )}
                    {meta.location && meta.time && <span className="opacity-40">·</span>}
                    {meta.time && (
                        <span className="flex items-center gap-1.5">
                            <Clock size={10} className="text-sky-400" />
                            {meta.old_time && <span className="opacity-50">{meta.old_time} →</span>}
                            <span className="font-medium text-sky-100/90">{meta.time}</span>
                        </span>
                    )}
                </div>
                <div className="flex-1 h-px bg-gradient-to-r from-gray-600/50 via-transparent to-transparent" />
            </div>
        );
    }

    const saveEdit = () => {
        const trimmed = draft.trim();
        if (!trimmed) return;
        onEdit?.(msg.id, trimmed);
        setEditing(false);
    };

    return (
        <div className={clsx(
            "flex gap-2 sm:gap-3 max-w-[90%] sm:max-w-[85%] group/message",
            msg.role === 'user' ? "self-end flex-row-reverse" : "self-start flex-row"
        )}>
            {msg.role !== 'user' && msg.role !== 'system' && (
                <button 
                    type="button"
                    onClick={() => linkedCharacter?.avatar_path && onAvatarClick?.(getAvatarUrl(linkedCharacter.id))}
                    className={clsx(
                        "w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden self-end",
                        linkedCharacter?.avatar_path && "cursor-pointer hover:border-blue-500/50 transition-colors"
                    )}
                >
                    {linkedCharacter?.avatar_path
                        ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                        : <MessageSquare className="text-blue-400" size={12} />
                    }
                </button>
            )}
            <div className="flex flex-col max-w-full">
                <div className={clsx("text-[10px] mb-1", msg.role === 'user' ? "text-gray-500 text-right" : "text-gray-400")}>
                    {msg.role === 'user'
                        ? (activeChat?.persona_name || 'You')
                        : isNarrator
                            ? '✦ Narrator'
                        : msg.role === 'system'
                            ? '✦ System'
                        : (linkedCharacter?.name || 'AI')}
                    {msg.kind === 'image' && msg.image_path && (
                        <span className="ml-1.5 text-pink-400/80">· 🖼️ Image</span>
                    )}
                </div>
                {editing ? (
                    <div className="flex flex-col gap-2">
                        <textarea
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            rows={3}
                            className="px-3 py-2 rounded-2xl text-sm bg-gray-900/80 border border-blue-500/40 text-gray-200 focus:outline-none resize-none"
                        />
                        <div className="flex gap-2 justify-end">
                            <button onClick={() => setEditing(false)} className="px-3 py-1.5 rounded-xl text-xs text-gray-400 hover:bg-white/5 transition-colors">Cancel</button>
                            <button onClick={saveEdit} className="px-3 py-1.5 rounded-xl text-xs bg-blue-600/30 text-blue-300 border border-blue-500/30 hover:bg-blue-600/50 transition-colors flex items-center gap-1">
                                <Check size={12} /> Save
                            </button>
                        </div>
                    </div>
                ) : (
                    <>
                        {(msg.role === 'char' || msg.role === 'assistant') ? (
                            <div className="flex flex-col gap-1.5 w-full">
                                {msg.content && <TavernMessage content={msg.content} />}
                                {msg.tool_calls?.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5">
                                        {msg.tool_calls.map((tc, idx) => {
                                            const fn = tc.function || {};
                                            let argsPreview = '';
                                            try {
                                                const args = typeof fn.arguments === 'string'
                                                    ? JSON.parse(fn.arguments)
                                                    : (fn.arguments || {});
                                                argsPreview = Object.values(args)
                                                    .filter(Boolean).map(String).join(' · ').slice(0, 80);
                                            } catch {
                                                argsPreview = '';
                                            }
                                            return (
                                                <span
                                                    key={tc.id || idx}
                                                    title="Agentic tool call"
                                                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-purple-500/10 border border-purple-500/25 text-[10px] text-purple-300 font-mono"
                                                >
                                                    <Activity size={9} />
                                                    {fn.name || 'tool'}
                                                    {argsPreview ? `: ${argsPreview}` : ''}
                                                </span>
                                            );
                                        })}
                                    </div>
                                )}
                                {msg.image_path && (
                                    <div className="mt-1">
                                        <img src={`/api/thumbnail/medium/${msg.image_path}`} alt="Attachment" loading="lazy" decoding="async" className="rounded-2xl max-w-full h-auto border border-white/10 shadow-lg" />
                                    </div>
                                )}
                                {/* Swipe controls — only shown when alternates exist */}
                                {altCount > 1 && (
                                    <div className="flex items-center gap-1.5 mt-0.5 select-none">
                                        <button
                                            onClick={() => onSwipe?.(msg.id, 'left')}
                                            className="p-0.5 rounded text-gray-600 hover:text-blue-400 transition-colors"
                                            title="Previous reply"
                                        >
                                            <ChevronLeft size={14} />
                                        </button>
                                        <span className="text-[10px] text-gray-600 font-mono tabular-nums">
                                            {activeIndex + 1}/{altCount}
                                        </span>
                                        <button
                                            onClick={() => onSwipe?.(msg.id, 'right')}
                                            className="p-0.5 rounded text-gray-600 hover:text-blue-400 transition-colors"
                                            title="Next reply"
                                        >
                                            <ChevronRight size={14} />
                                        </button>
                                    </div>
                                )}
                            </div>
                        ) : msg.role === 'user' ? (
                            <div className="text-sm leading-relaxed break-words text-gray-100">
                                <TavernMessage content={msg.content} alignRight />
                                {msg.image_path && (
                                    <div className="mt-3">
                                        <img src={`/api/thumbnail/medium/${msg.image_path}`} alt="Attachment" loading="lazy" decoding="async" className="rounded-xl max-w-full h-auto border border-white/10 shadow-lg" />
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className={clsx("px-3 sm:px-4 py-3 rounded-2xl text-sm leading-relaxed break-words", isNarrator ? "bg-purple-500/10 text-purple-100/90 border border-purple-500/20 rounded-tl-sm italic" : "bg-yellow-500/10 text-yellow-200/80 border border-yellow-500/15 rounded-tl-sm text-xs italic")}>
                                <span className="whitespace-pre-wrap">{msg.content}</span>
                                {msg.image_path && (
                                    <div className="mt-3">
                                        <img src={`/api/thumbnail/medium/${msg.image_path}`} alt="Attachment" loading="lazy" decoding="async" className="rounded-xl max-w-full h-auto border border-white/10 shadow-lg" />
                                    </div>
                                )}
                            </div>
                        )}
                        <div className="flex items-center gap-1 opacity-0 group-hover/message:opacity-100 transition-opacity mt-0.5">
                            {(msg.role === 'user' || msg.role === 'char') && (
                                <button
                                    onClick={() => { setDraft(msg.content); setEditing(true); }}
                                    className="p-1 rounded-md text-gray-500 hover:text-blue-400 hover:bg-white/5 transition-colors"
                                    title="Edit message"
                                >
                                    <Pencil size={11} />
                                </button>
                            )}
                            {(canRegenerate || msg.role === 'user') && (
                                <button
                                    onClick={() => onRegenerate?.(msg.id)}
                                    className="p-1 rounded-md text-gray-500 hover:text-green-400 hover:bg-white/5 transition-colors"
                                    title="Regenerate from here"
                                >
                                    <RotateCcw size={11} />
                                </button>
                            )}
                            <button
                                onClick={() => onRollback?.(msg.id)}
                                className="p-1 rounded-md text-gray-500 hover:text-red-400 hover:bg-white/5 transition-colors"
                                title="Rollback chat to here"
                            >
                                <Undo2 size={11} />
                            </button>
                            <button
                                onClick={() => onPin?.(msg.id, !!msg.pinned)}
                                className={clsx(
                                    "p-1 rounded-md hover:bg-white/5 transition-colors",
                                    msg.pinned ? "text-amber-400 hover:text-amber-300" : "text-gray-500 hover:text-amber-400"
                                )}
                                title={msg.pinned ? "Unpin message" : "Pin message (preserved in context)"}
                            >
                                {msg.pinned ? <Pin size={11} /> : <PinOff size={11} />}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
});

// ---------------------------------------------------------------------------
// SystemPromptPanel — full tiered system-prompt editor in the context panel
// ---------------------------------------------------------------------------
const SOURCE_DOT = {
    override:    'bg-orange-400',
    character:   'bg-blue-400',
    char_append: 'bg-sky-400',
    chat_append: 'bg-teal-400',
    config:      'bg-emerald-400',
    lorebook:    'bg-violet-400',
    world_state: 'bg-amber-400',
};

function SectionPreview({ sec }) {
    const [expanded, setExpanded] = useState(false);
    return (
        <div className="rounded-lg bg-gray-900/50 border border-white/5 overflow-hidden">
            <button
                type="button"
                onClick={() => setExpanded(v => !v)}
                className="w-full text-left text-[9px] font-semibold text-gray-500 px-2.5 py-1.5 bg-gray-800/30 uppercase tracking-wider border-b border-white/5 flex items-center gap-1.5 hover:bg-gray-800/60 transition-colors"
            >
                <span className={clsx('w-1.5 h-1.5 rounded-full shrink-0', SOURCE_DOT[sec.source] ?? 'bg-gray-500')} />
                <span className="flex-1 truncate">{sec.label}</span>
                <span className="text-gray-600 ml-1">{expanded ? '▲' : '▼'}</span>
            </button>
            {expanded && (
                <div className="max-h-40 overflow-y-auto px-2.5 py-2 text-[10px] leading-relaxed text-gray-300 whitespace-pre-wrap custom-scrollbar">
                    {sec.content || '—'}
                </div>
            )}
        </div>
    );
}

function SystemPromptPanel({ activeChat, linkedCharacter, systemPromptData, onChatUpdate, onCharacterPatch }) {
    const [activeTab, setActiveTab] = useState('preview'); // 'preview' | 'override' | 'append'

    // Controlled textarea values — reset when active chat changes
    const chatKey = activeChat?.id || 'none';
    const [overrideVal, setOverrideVal] = useState(activeChat?.system_prompt_override || '');
    const [chatAppendVal, setChatAppendVal] = useState(activeChat?.append_system_prompt || '');
    const [charAppendVal, setCharAppendVal] = useState(linkedCharacter?.append_system_prompt || '');

    useEffect(() => {
        setOverrideVal(activeChat?.system_prompt_override || '');
        setChatAppendVal(activeChat?.append_system_prompt || '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [chatKey]);

    useEffect(() => {
        setCharAppendVal(linkedCharacter?.append_system_prompt || '');
    }, [linkedCharacter?.id, linkedCharacter?.append_system_prompt]);

    const hasOverride = Boolean(activeChat?.system_prompt_override);
    const hasChatAppend = Boolean(activeChat?.append_system_prompt);
    const hasCharAppend = Boolean(linkedCharacter?.append_system_prompt);

    const saveOverride = () => {
        const val = overrideVal.trim() || null;
        if (val !== (activeChat?.system_prompt_override || null)) {
            onChatUpdate({ system_prompt_override: val });
        }
    };
    const saveChatAppend = () => {
        const val = chatAppendVal.trim() || null;
        if (val !== (activeChat?.append_system_prompt || null)) {
            onChatUpdate({ append_system_prompt: val });
        }
    };
    const saveCharAppend = () => {
        if (!linkedCharacter) return;
        const val = charAppendVal.trim() || null;
        if (val !== (linkedCharacter?.append_system_prompt || null)) {
            onCharacterPatch({ append_system_prompt: val });
        }
    };

    const TABS = [
        { id: 'preview', label: 'Preview' },
        { id: 'override', label: 'Chat Prompt', badge: hasOverride },
        { id: 'append',  label: 'Character Extra',   badge: hasChatAppend || hasCharAppend },
    ];

    return (
        <div className="glass-panel p-4 rounded-xl border border-white/5 space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between">
                <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                    <Brain size={12} /> System Prompt
                </h4>
                {hasOverride && (
                    <button
                        onClick={() => { setOverrideVal(''); onChatUpdate({ system_prompt_override: null }); }}
                        className="text-[9px] text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded bg-red-500/10 hover:bg-red-500/20 transition-colors"
                    >
                        Clear override
                    </button>
                )}
            </div>

            {/* Tab bar */}
            <div className="flex gap-1 p-1 bg-black/30 rounded-lg">
                {TABS.map(t => (
                    <button
                        key={t.id}
                        type="button"
                        onClick={() => setActiveTab(t.id)}
                        className={clsx(
                            'flex-1 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-all relative',
                            activeTab === t.id
                                ? 'bg-gray-700 text-white shadow'
                                : 'text-gray-500 hover:text-gray-300'
                        )}
                    >
                        {t.label}
                        {t.badge && (
                            <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-teal-400" />
                        )}
                    </button>
                ))}
            </div>

            {/* Preview tab — collapsible section list */}
            {activeTab === 'preview' && (
                <div className="space-y-1.5">
                    {systemPromptData?.sections?.length ? (
                        systemPromptData.sections.map((sec, i) => (
                            <SectionPreview key={i} sec={sec} />
                        ))
                    ) : (
                        <p className="text-[10px] text-gray-600 text-center py-3">
                            {activeChat ? 'No system prompt sections assembled yet.' : 'Select a chat to preview.'}
                        </p>
                    )}
                    {systemPromptData && (
                        <p className="text-[9px] text-gray-600 pt-1 text-right">
                            ~{systemPromptData.context_tokens ?? '?'} tokens · {systemPromptData.message_count ?? 0} messages in context
                        </p>
                    )}
                </div>
            )}

            {activeTab === 'override' && (
                <div className="space-y-2">
                    <p className="text-[10px] text-gray-500 leading-relaxed">
                        <span className="text-orange-400 font-semibold">Chat System Prompt</span> is applied only to this chat.
                        It is appended after the character's core instructions.
                    </p>
                    <textarea
                        value={overrideVal}
                        onChange={e => setOverrideVal(e.target.value)}
                        onBlur={saveOverride}
                        placeholder="Override everything — write a complete system prompt…"
                        rows={5}
                        className="w-full bg-gray-800/60 border border-orange-500/20 focus:border-orange-500/50 text-xs rounded-lg px-3 py-2 text-gray-300 placeholder-gray-600 focus:outline-none resize-y min-h-[80px]"
                    />
                    <button
                        type="button"
                        onClick={saveOverride}
                        className="w-full py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-lg bg-orange-500/10 text-orange-300 hover:bg-orange-500/20 border border-orange-500/20 transition-colors"
                    >
                        Save override
                    </button>
                </div>
            )}

            {/* Append tab — non-destructive extra instructions at two levels */}
            {activeTab === 'append' && (
                <div className="space-y-4">
                    {/* Per-chat append */}
                    <div className="space-y-2">
                        <div className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-teal-400 shrink-0" />
                            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                                This chat
                            </p>
                            {hasChatAppend && (
                                <button
                                    type="button"
                                    onClick={() => { setChatAppendVal(''); onChatUpdate({ append_system_prompt: null }); }}
                                    className="ml-auto text-[9px] text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded bg-red-500/10 hover:bg-red-500/20 transition-colors"
                                >
                                    Clear
                                </button>
                            )}
                        </div>
                        <p className="text-[10px] text-gray-600 leading-relaxed">
                            Appended after the character card, before global instructions. Only affects this chat.
                        </p>
                        <textarea
                            value={chatAppendVal}
                            onChange={e => setChatAppendVal(e.target.value)}
                            onBlur={saveChatAppend}
                            placeholder="e.g. Always speak in riddles. Today is {user}'s birthday…"
                            rows={3}
                            className="w-full bg-gray-800/60 border border-teal-500/20 focus:border-teal-500/50 text-xs rounded-lg px-3 py-2 text-gray-300 placeholder-gray-600 focus:outline-none resize-y min-h-[60px]"
                        />
                        <button
                            type="button"
                            onClick={saveChatAppend}
                            className="w-full py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-lg bg-teal-500/10 text-teal-300 hover:bg-teal-500/20 border border-teal-500/20 transition-colors"
                        >
                            Save chat append
                        </button>
                    </div>

                    {/* Per-character append */}
                    <div className="space-y-2 pt-2 border-t border-white/5">
                        <div className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0" />
                            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                                {linkedCharacter ? linkedCharacter.name : 'Character'} (all chats)
                            </p>
                            {hasCharAppend && (
                                <button
                                    type="button"
                                    onClick={() => { setCharAppendVal(''); onCharacterPatch({ append_system_prompt: null }); }}
                                    className="ml-auto text-[9px] text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded bg-red-500/10 hover:bg-red-500/20 transition-colors"
                                >
                                    Clear
                                </button>
                            )}
                        </div>
                        {linkedCharacter ? (
                            <>
                                <p className="text-[10px] text-gray-600 leading-relaxed">
                                    Appended after the character card in <em>every</em> chat that uses {linkedCharacter.name}. Use this for permanent personality tweaks.
                                </p>
                                <textarea
                                    value={charAppendVal}
                                    onChange={e => setCharAppendVal(e.target.value)}
                                    onBlur={saveCharAppend}
                                    placeholder={`e.g. ${linkedCharacter.name} always ends sentences with a soft laugh…`}
                                    rows={3}
                                    className="w-full bg-gray-800/60 border border-sky-500/20 focus:border-sky-500/50 text-xs rounded-lg px-3 py-2 text-gray-300 placeholder-gray-600 focus:outline-none resize-y min-h-[60px]"
                                />
                                <button
                                    type="button"
                                    onClick={saveCharAppend}
                                    className="w-full py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-lg bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 border border-sky-500/20 transition-colors"
                                >
                                    Save character append
                                </button>
                            </>
                        ) : (
                            <p className="text-[10px] text-gray-600 text-center py-2 border border-dashed border-gray-700/50 rounded-lg">
                                Assign a character to edit their append block.
                            </p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
function ContextSlider({ activeChat, onChange }) {
    const serverVal = activeChat?.max_context_tokens || 4096;
    const [localVal, setLocalVal] = useState(serverVal);
    const [prevServerVal, setPrevServerVal] = useState(serverVal);

    // Sync when the server value changes (e.g. different chat selected) without useEffect
    if (serverVal !== prevServerVal) {
        setPrevServerVal(serverVal);
        setLocalVal(serverVal);
    }
    
    return (
        <input
            type="range"
            min="2048"
            max="131072"
            step="2048"
            value={localVal}
            onChange={(e) => setLocalVal(parseInt(e.target.value))}
            onMouseUp={() => onChange(localVal)}
            onTouchEnd={() => onChange(localVal)}
            onKeyUp={(e) => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') onChange(localVal); }}
            className="w-full accent-blue-500"
            title="Max tokens sent to the LLM. Higher = remembers more but costs more."
        />
    );
}

export default function ChatWorkspace() {
    const [mobileTab, setMobileTab] = useState('chat'); // 'chats', 'chat', 'context'
    const [chatsCollapsed, setChatsCollapsed] = useState(() => {
        try { return localStorage.getItem('cw.chatsCollapsed') === '1'; } catch { return false; }
    });
    const [contextCollapsed, setContextCollapsed] = useState(() => {
        try { return localStorage.getItem('cw.contextCollapsed') === '1'; } catch { return false; }
    });
    useEffect(() => {
        try { localStorage.setItem('cw.chatsCollapsed', chatsCollapsed ? '1' : '0'); } catch { /* ignore */ }
    }, [chatsCollapsed]);
    useEffect(() => {
        try { localStorage.setItem('cw.contextCollapsed', contextCollapsed ? '1' : '0'); } catch { /* ignore */ }
    }, [contextCollapsed]);
    const [message, setMessage] = useState('');
    const [renamingChatId, setRenamingChatId] = useState(null);
    const [renameValue, setRenameValue] = useState('');
    const hasCreatedChatRef = useRef(false);
    const [isGeneratingScene, setIsGeneratingScene] = useState(false);
    const [sceneJobId, setSceneJobId] = useState(null);
    const [pendingAttachment, setPendingAttachment] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [agenticMode, setAgenticMode] = useState(true);
    const [narrateMode, setNarrateMode] = useState(false);
    const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);
    const [greetingModal, setGreetingModal] = useState(null);
    const [showNewChatModal, setShowNewChatModal] = useState(false);
    const [showCharacterDetails, setShowCharacterDetails] = useState(false);
    const [showScenesModal, setShowScenesModal] = useState(false);
    const [sceneTab, setSceneTab] = useState('chat');
    const [showMoreTools, setShowMoreTools] = useState(false);
    const [avatarModalSrc, setAvatarModalSrc] = useState(null);
    const handleAvatarClick = useCallback((url) => setAvatarModalSrc(url), []);
    const fileInputRef = useRef(null);
    const messagesEndRef = useRef(null);
    const listContainerRef = useRef(null);
    const textareaRef = useRef(null);
    const location = useLocation();

    const settings = useSettings();
    
    const queryClient = useQueryClient();
    const activeChatId = useWorldVaultStore(state => state.activeChatId);
    const setActiveChatId = useWorldVaultStore(state => state.setActiveChat);

    const activeStreamEntries = useActiveChatStreams(activeChatId);
    const activeStreams = useMemo(
        () => activeStreamEntries
            .filter(item => item.jobData?.status === 'running')
            .map(item => ({ _key: `stream-${item.jobId}`, jobId: item.jobId, jobData: item.jobData })),
        [activeStreamEntries]
    );
    
    const suggestReplyMutation = useSuggestReply();
    const [suggestJobId, setSuggestJobId] = useState(null);
    const suggestJobIdRef = useRef(null);
    const suggestSafetyTimerRef = useRef(null);
    const titlePollCancelledRef = useRef(false);
    
    useEffect(() => {
        return () => {
            if (suggestSafetyTimerRef.current) {
                clearTimeout(suggestSafetyTimerRef.current);
                suggestSafetyTimerRef.current = null;
            }
        };
    }, []);
    
    const [activeCommand, setActiveCommand] = useState(null);
    
    useEffect(() => {
        suggestJobIdRef.current = suggestJobId;
    }, [suggestJobId]);

    useEffect(() => {
        // Cancel any in-flight title-generation poll when switching chats.
        // triggerAutoTitle resets the flag to false at the start of a new run.
        titlePollCancelledRef.current = true;
        setIsGeneratingTitle(false);
    }, [activeChatId]);

    const { data: chats, isLoading: isChatsLoading } = useChats();
    const { data: activeChat } = useChat(activeChatId);
    const { data: messages = [] } = useMessages(activeChatId);
    const { data: lorebooks = [] } = useLorebooks();
    const { data: characters = [] } = useCharacters();
    const { data: availableModels = [] } = useLLMAvailableModels();
    const { data: defaultLlmConfig } = useLLMDefaultProvider();
    const { data: systemPromptData } = useChatSystemPrompt(activeChatId);
    const { data: chatCollection } = useCharacterCollection(activeChat?.character_id);
    const { data: chatImages = [] } = useChatImages(activeChatId);
    const { data: collectionsMap = {} } = useCollections('chat');
    const collectionsList = useMemo(
        () => Object.values(collectionsMap).sort((a, b) => (a.name || '').localeCompare(b.name || '')),
        [collectionsMap]
    );

    // Combine messages + active streaming jobs for virtualized list.
    // `activeStreams` is sourced from the React-Query-backed hook above.
    const listItems = useMemo(
        () => [
            ...messages.map(msg => ({ _key: msg.id || `msg-${messages.indexOf(msg)}`, item: msg })),
            ...activeStreams,
        ],
        [messages, activeStreams]
    );

    const rowVirtualizer = useVirtualizer({
        count: listItems.length,
        getScrollElement: () => listContainerRef.current,
        estimateSize: () => 120,
        overscan: 8,
    });

    // Use activeChat's lorebooks instead of the store's global state
    const emptyLorebooks = useMemo(() => [], []);
    const selectedLorebooks = activeChat?.active_lorebook_ids || emptyLorebooks;

    const sendMessageMutation = useSendMessage();
    const createChatMutation = useCreateChat();
    const deleteChatMutation = useDeleteChat();
    const renameChatMutation = useRenameChat();
    const updateChatMutation = useUpdateChat();
    const editMessageMutation = useEditMessage();
    const rollbackMutation = useRollbackChat();
    const regenerateMutation = useRegenerateReply();
    const patchCharacterMutation = usePatchCharacter();
    const impersonateMutation = useImpersonateMessage();
    const pinMessageMutation = usePinMessage();
    const swipeMessageMutation = useSwipeMessage();
    const illustrateMutation = useIllustrateChat();
    const { data: chatJobs = [] } = useChatJobs(activeChatId);

    const { subscribe } = useWebSocket();
    const runLLMJob = useLLMJobResult();
    const { confirm } = useConfirmation();

    useEffect(() => {
        const characterId = location.state?.characterId;
        if (characterId && !activeChatId && !hasCreatedChatRef.current) {
            hasCreatedChatRef.current = true;
            const character = characters.find(c => c.id === characterId);
            const hasMultipleGreetings = character && 
                (character.alternate_greetings?.length > 0);
            
            if (hasMultipleGreetings) {
                setGreetingModal({
                    character,
                    onCreate: async (selectedGreeting) => {
                        setGreetingModal(null);
                        const chat = await createChatMutation.mutateAsync({ 
                            name: 'New Chat', 
                            character_id: characterId,
                            override_greeting: selectedGreeting 
                        });
                        setActiveChatId(chat.id);
                        window.history.replaceState({}, document.title);
                    }
                });
            } else {
                createChatMutation.mutate(
                    { name: 'New Chat', character_id: characterId },
                    {
                        onSuccess: (chat) => {
                            setActiveChatId(chat.id);
                            window.history.replaceState({}, document.title);
                        },
                        onError: () => { hasCreatedChatRef.current = false; }
                    }
                );
            }
        }
    }, [location.state?.characterId, characters, activeChatId, createChatMutation, setActiveChatId]);

    useEffect(() => {
        if (chats?.length > 0 && !activeChatId) {
            setActiveChatId(chats[0].id);
        }
    }, [chats, activeChatId, setActiveChatId]);

    useEffect(() => {
        // Helper: extract job data from the WS envelope.
        // Backend emits: { type, data: { job: {...} }, timestamp, sequence_number }
        const getJob = (event) => event?.data?.job || {};

        // Throttle streaming updates to ~10Hz. The backend streams one
        // JOB_PROGRESS per token and each payload carries the FULL accumulated
        // text, so keeping only the latest per job is lossless while avoiding
        // a full page re-render per token (the root cause of hot mobile devices).
        const pendingStream = new Map();
        let flushTimer = null;

        const applyStreamUpdate = (job) => {
            const streamText = job.text ?? job.message ?? null;
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;

            // is_suggestion: check job_id ref first (more reliable), then metadata flag
            const isSuggestion = eventId === suggestJobIdRef.current || !!meta.is_suggestion;
            if (isSuggestion) {
                if (streamText) setMessage(streamText);
                return;
            }

            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;
            if (streamText && eventChatId) {
                setStreamingJob(queryClient, eventId, {
                    text: streamText,
                    status: 'running',
                    chatId: eventChatId,
                    type: meta.workspace,
                    taskType: job.task_type ?? null,
                    progress: job.overall_progress ?? job.progress ?? null
                });
            }
        };

        const throttleProgress = (job) => {
            const eventId = job.id ?? null;
            if (!eventId) { applyStreamUpdate(job); return; }
            pendingStream.set(eventId, job);
            if (flushTimer) return;
            flushTimer = setTimeout(() => {
                flushTimer = null;
                for (const [, pendingJob] of pendingStream) applyStreamUpdate(pendingJob);
                pendingStream.clear();
            }, 100);
        };

        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            throttleProgress(getJob(event));
        });

        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;

            // Drop any buffered progress chunks for this job — a late flush
            // would resurrect the streaming bubble after it was cleared.
            if (eventId) pendingStream.delete(eventId);

            const isSuggestion = eventId === suggestJobIdRef.current || !!meta.is_suggestion;
            if (isSuggestion) {
                // Grab final text from outputs if streaming missed it
                const outputText = job.outputs?.[0]?.content ?? null;
                if (outputText) setMessage(outputText);
                setSuggestJobId(null);
                return;
            }

            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', eventChatId] });
                // Story time/location may have changed via update_world_state — refresh chat.
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', eventChatId] });
                if (job.task_type === 'image') {
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'chat', 'images', eventChatId] });
                }
            }

            if (eventChatId === activeChatId) {
                const jobType = meta.workspace || job.task_type;
                if (jobType === 'image' || meta.image_context) {
                    toast.success('Image generated!', { icon: '🖼️' });
                }
            }

            // Clear scene generation state when the scene job completes
            if (eventId === sceneJobId) {
                setSceneJobId(null);
                setIsGeneratingScene(false);
            }
        });

        const unsubError = subscribe(EventTypes.JOB_FAILED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;
            if (eventId) pendingStream.delete(eventId);
            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId === suggestJobIdRef.current) setSuggestJobId(null);
            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId === activeChatId) {
                toast.error('AI response failed. Please try again.');
            }

            // Clear scene generation state when the scene job fails
            if (eventId === sceneJobId) {
                setSceneJobId(null);
                setIsGeneratingScene(false);
            }
        });

        // JOB_CANCELLED unhandled before: left a stuck 'thinking…' bubble and
        // a permanently disabled Suggest button. Clear the stream state here.
        const unsubCancelled = subscribe(EventTypes.JOB_CANCELLED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;
            if (eventId) pendingStream.delete(eventId);
            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId === suggestJobIdRef.current) setSuggestJobId(null);
            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId === activeChatId) {
                toast('AI response cancelled', { icon: '🛑' });
            }
        });

        return () => {
            if (flushTimer) clearTimeout(flushTimer);
            pendingStream.clear();
            unsubProgress(); unsubCompleted(); unsubError(); unsubCancelled();
        };
    }, [subscribe, activeChatId, queryClient]);

    useEffect(() => {
        // During streaming, use instant (non-smooth) scrolling — smooth
        // scrolling per token triggers repeated layout + animation on mobile.
        const hasStreaming = activeStreamEntries.length > 0;
        messagesEndRef.current?.scrollIntoView({ behavior: hasStreaming ? 'auto' : 'smooth', block: 'end' });
    }, [messages, activeStreamEntries]);

    useEffect(() => {
        // Debounced resize — avoids layout thrashing on mobile with every keystroke
        const timer = setTimeout(() => {
            if (textareaRef.current) {
                textareaRef.current.style.height = 'auto';
                textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
            }
        }, 150);
        return () => clearTimeout(timer);
    }, [message]);

    const handleSendMessage = useCallback(async () => {
        const msgContentRaw = message.trim();
        if (!msgContentRaw && !pendingAttachment && !activeCommand?.noArgs) return;

        let chatIdToUse = activeChatId;
        if (!chatIdToUse) {
            try {
                const newChat = await createChatMutation.mutateAsync({ name: 'New Chat' });
                chatIdToUse = newChat.id;
                setActiveChatId(newChat.id);
            } catch {
                toast.error('Failed to create chat');
                return;
            }
        }

        setMessage('');
        const attachmentFilename = pendingAttachment?.filename || null;
        setPendingAttachment(null);
        
        const currentCommand = activeCommand;
        setActiveCommand(null);
        
        let msgContent = msgContentRaw;
        let role = 'user';
        let noReply = false;
        
        if (currentCommand) {
            const cmd = currentCommand.cmd;
            const arg = msgContentRaw;
            
            if (cmd === '/silent') {
                noReply = true;
                msgContent = arg;
                if (!msgContent && !attachmentFilename) { toast.error("Provide message text"); return; }
            } else if (cmd === '/story') {
                noReply = true;
                role = 'story';
                msgContent = arg;
                if (!msgContent && !attachmentFilename) { toast.error("Provide story text"); return; }
            } else if (cmd === '/puppet' || cmd === '/impersonate') {
                noReply = true;
                role = 'char';
                msgContent = arg;
                if (!msgContent && !attachmentFilename) { toast.error("Provide character text"); return; }
            } else if (cmd === '/time' || cmd === '/fastforward') {
                if (!arg) { toast.error("Provide a time"); return; }
                try {
                    await updateChatMutation.mutateAsync({ chatId: chatIdToUse, story_time: arg });
                } catch { toast.error("Failed to update time"); }
                return;
            } else if (cmd === '/location') {
                if (!arg) { toast.error("Provide a location"); return; }
                try {
                    await updateChatMutation.mutateAsync({ chatId: chatIdToUse, story_location: arg });
                } catch { toast.error("Failed to update location"); }
                return;
            } else if (cmd === '/me' || cmd === '/action') {
                msgContent = `*${arg}*`;
                if (!arg && !attachmentFilename) { toast.error("Provide action text"); return; }
            } else if (cmd === '/suggest') {
                try {
                    const res = await suggestReplyMutation.mutateAsync({ chatId: chatIdToUse, draft: arg || undefined });
                    if (res.job_id) { setSuggestJobId(res.job_id); }
                } catch { toast.error("Failed to generate suggestion"); }
                return;
            }
        }

        try {
            const res = await sendMessageMutation.mutateAsync({
                chatId: chatIdToUse,
                message: { 
                    role: role, 
                    content: msgContent, 
                    lorebook_ids: selectedLorebooks, 
                    image_path: attachmentFilename, 
                    agentic: agenticMode,
                    narrate: narrateMode,
                    generator_checkpoint: settings.generator?.defaultCheckpoint || null,
                    no_reply: noReply
                }
            });
            if (res.job_id) {
                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: chatIdToUse });
            }
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', chatIdToUse] });
        } catch {
            toast.error('Failed to send message');
        }
    }, [message, pendingAttachment, activeChatId, selectedLorebooks, agenticMode, narrateMode, createChatMutation, sendMessageMutation, queryClient, setActiveChatId, settings, updateChatMutation, suggestReplyMutation, activeCommand]);

    const handleSuggestClick = useCallback(async () => {
        if (!activeChatId) return;
        try {
            const draft = message.trim();
            setMessage('');
            const res = await suggestReplyMutation.mutateAsync({ chatId: activeChatId, draft: draft || undefined });
            if (res.job_id) {
                setSuggestJobId(res.job_id);
                // Safety net: if the completion event is missed (reconnect gap),
                // don't leave the Suggest button disabled forever.
                suggestSafetyTimerRef.current = window.setTimeout(() => {
                    setSuggestJobId((current) => (current === res.job_id ? null : current));
                }, 120000);
            }
        } catch {
            toast.error("Failed to generate suggestion");
        }
    }, [activeChatId, message, suggestReplyMutation]);

    const handleTextChange = (e) => {
        const val = e.target.value;
        if (!activeCommand && val.startsWith('/')) {
            const spaceIdx = val.indexOf(' ');
            if (spaceIdx !== -1) {
                const cmdString = val.substring(0, spaceIdx).toLowerCase();
                const matchedCmd = COMMANDS.find(c => c.cmd === cmdString);
                if (matchedCmd && !matchedCmd.noArgs) {
                    setActiveCommand(matchedCmd);
                    setMessage(val.substring(spaceIdx + 1));
                    return;
                }
            }
        }
        setMessage(val);
    };

    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Backspace' && message === '' && activeCommand) {
            setMessage(activeCommand.cmd + ' ');
            setActiveCommand(null);
            e.preventDefault();
            return;
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    }, [handleSendMessage, message, activeCommand]);

    const canSend = (message.trim() || pendingAttachment || activeCommand?.noArgs) && !sendMessageMutation.isPending;

    const handleGenerateScene = async () => {
        if (!activeChatId) return;
        setIsGeneratingScene(true);
        toast.success('Generating scene...', { icon: '📸' });
        try {
            const data = await api.post(`/api/v2/chats/${activeChatId}/scene`, {});
            if (data.job_id) {
                setSceneJobId(data.job_id);
                setStreamingJob(queryClient, data.job_id, { text: 'Generating scene image...', status: 'running', chatId: activeChatId, type: 'roleplay', taskType: 'llm' });
            }
        } catch {
            toast.error('Failed to generate scene');
            setIsGeneratingScene(false);
        }
    };

    const handleIllustrate = async () => {
        if (!activeChatId || illustrateMutation.isPending) return;
        const prompt = message.trim();
        try {
            await illustrateMutation.mutateAsync({ chatId: activeChatId, imagePrompt: prompt });
            if (prompt) setMessage('');
            toast.success('Illustration queued...', { icon: '🖼️' });
        } catch {
            toast.error('Failed to start illustration');
        }
    };

    const handleSaveImageToCollection = useCallback(async (collectionId, path) => {
        if (!collectionId || !path) return;
        try {
            await addImagesToCollection(collectionId, [path]);
            queryClient.invalidateQueries({ queryKey: ['collections'] });
            if (activeChat?.character_id) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', activeChat.character_id, 'collection'] });
            }
            toast.success('Image saved to collection');
        } catch {
            toast.error('Failed to save image');
        }
    }, [queryClient, activeChat?.character_id]);

    const triggerAutoTitle = async () => {
        if (!activeChatId) return;
        titlePollCancelledRef.current = false;
        setIsGeneratingTitle(true);
        toast('Generating title...', { icon: '🤖' });
        try {
            const chatHistory = messages.slice(-5).map(m => `${m.role}: ${m.content}`).join('\n');
            const { text, cancelled } = await runLLMJob({
                workflow: {
                    model: activeChat?.llm_model || defaultLlmConfig?.model_id || null,
                    messages: [
                        { role: 'system', content: 'Generate a short, catchy title (max 5 words) for the following chat. Output ONLY the title, no quotes.' },
                        { role: 'user', content: chatHistory || 'A new conversation.' }
                    ]
                },
                isCancelled: () => titlePollCancelledRef.current,
            });
            if (cancelled) return;
            if (!text) {
                toast.error('Title generation failed');
                return;
            }
            const newTitle = text.replace(/["']/g, '');
            await renameChatMutation.mutateAsync({ chatId: activeChatId, name: newTitle });
            toast.success('Title generated!');
        } catch {
            toast.error('Failed to generate title');
        } finally {
            setIsGeneratingTitle(false);
        }
    };

    const handleCreateChat = () => {
        setShowNewChatModal(true);
    };

    const confirmCreateChat = (config) => {
        if (createChatMutation.isPending) return;
        setShowNewChatModal(false);
        const { chatName, characterId, personaName, storyTime, storyLocation, selectedLorebooks: newSelectedLorebooks } = config;
        
        const character = characterId ? characters.find(c => c.id === characterId) : null;
        const hasMultipleGreetings = character && (character.alternate_greetings?.length > 0);

        const payload = { 
            name: chatName, 
            character_id: characterId, 
            persona_name: personaName, 
            story_time: storyTime, 
            story_location: storyLocation,
            active_lorebook_ids: newSelectedLorebooks
        };

        if (hasMultipleGreetings) {
            setGreetingModal({
                character,
                onCreate: async (selectedGreeting) => {
                    setGreetingModal(null);
                    const chat = await createChatMutation.mutateAsync({ 
                        ...payload,
                        override_greeting: selectedGreeting 
                    });
                    setActiveChatId(chat.id);
                    setMobileTab('chat');
                    toast.success('New chat created');
                }
            });
        } else {
            createChatMutation.mutate(
                payload,
                {
                    onSuccess: (chat) => {
                        setActiveChatId(chat.id);
                        setMobileTab('chat');
                        toast.success('New chat created');
                    },
                    onError: () => toast.error('Failed to create chat')
                }
            );
        }
    };

    const handleAttachmentChange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        e.target.value = '';
        if (file.size > 20 * 1024 * 1024) { toast.error('File too large (max 20MB)'); return; }
        setIsUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);
            const res = await filesApi.uploadChatAttachment(formData);
            setPendingAttachment({ filename: res.filename, name: file.name });
            toast.success('Image attached');
        } catch {
            toast.error('Failed to upload image');
        } finally {
            setIsUploading(false);
        }
    };

    const handleDeleteChat = async (chat) => {
        const ok = await confirm({
            title: 'Delete Chat',
            message: `Are you sure you want to delete "${chat.name || 'this chat'}"? All messages will be permanently lost.`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteChatMutation.mutateAsync(chat.id);
            if (activeChatId === chat.id) {
                const remaining = chats?.filter(c => c.id !== chat.id);
                setActiveChatId(remaining?.[0]?.id || null);
            }
            toast.success('Chat deleted');
        } catch {
            toast.error('Failed to delete chat');
        }
    };

    const startRename = (chat) => { setRenamingChatId(chat.id); setRenameValue(chat.name || ''); };
    const finishRename = async () => {
        if (renamingChatId && renameValue.trim()) {
            try {
                await renameChatMutation.mutateAsync({ chatId: renamingChatId, name: renameValue.trim() });
            } catch { toast.error('Failed to rename'); }
        }
        setRenamingChatId(null);
    };

    const handleChatUpdate = useCallback((updates) => {
        if (!activeChatId) return;
        updateChatMutation.mutate({ chatId: activeChatId, ...updates });
    }, [activeChatId, updateChatMutation]);

    const handleEditMessage = useCallback(async (msgId, content) => {
        if (!content.trim()) return;
        try {
            await editMessageMutation.mutateAsync({ chatId: activeChatId, msgId, content });
            toast.success('Message updated');
        } catch { toast.error('Failed to update message'); }
    }, [activeChatId, editMessageMutation]);

    const handleRollback = useCallback(async (msgId) => {
        const ok = await confirm({
            title: 'Rollback chat',
            message: 'This will delete this message and everything after it. The LLM reply will regenerate from the remaining message.',
            confirmText: 'Rollback',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await rollbackMutation.mutateAsync({ chatId: activeChatId, messageId: msgId });
            toast.success('Chat rolled back');
        } catch { toast.error('Failed to rollback'); }
    }, [activeChatId, confirm, rollbackMutation]);

    const handleRegenerate = useCallback(async (msgId) => {
        try {
            const res = await regenerateMutation.mutateAsync({ chatId: activeChatId, messageId: msgId });
            if (res?.job_id) setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'llm' });
        } catch { toast.error('Failed to regenerate'); }
    }, [activeChatId, regenerateMutation]);

    const handleImpersonate = useCallback(async (hint = '') => {
        if (!activeChatId) return;
        try {
            const res = await impersonateMutation.mutateAsync({ chatId: activeChatId, hint });
            if (res?.job_id) {
                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'impersonation' });
                toast('Impersonating...', { icon: '👤' });
            }
        } catch { toast.error('Impersonation failed'); }
    }, [activeChatId, impersonateMutation]);

    const handlePinMessage = useCallback(async (msgId, currentlyPinned) => {
        try {
            await pinMessageMutation.mutateAsync({ chatId: activeChatId, msgId, pinned: !currentlyPinned });
            toast.success(currentlyPinned ? 'Message unpinned' : 'Message pinned — won\'t be pruned from context');
        } catch { toast.error('Failed to pin message'); }
    }, [activeChatId, pinMessageMutation]);

    const handleSwipe = useCallback(async (msgId, direction, index) => {
        try {
            await swipeMessageMutation.mutateAsync({ chatId: activeChatId, msgId, direction, index });
        } catch { toast.error('Swipe failed'); }
    }, [activeChatId, swipeMessageMutation]);

    const handleExportChat = () => {
        if (!messages.length) { toast.error('No messages to export'); return; }
        const charName = linkedCharacter?.name || 'AI';
        const userName = activeChat?.persona_name || 'You';
        const chatName = activeChat?.name || 'Chat';

        const ROLE_LABEL = {
            user:   userName,
            char:   charName,
            system: '✦ System',
        };

        const lines = [
            `# ${chatName}`,
            linkedCharacter ? `**Character:** ${charName}` : null,
            `**Exported:** ${new Date().toLocaleString()}`,
            '',
            '---',
            '',
        ].filter(Boolean);

        for (const msg of messages) {
            const meta = msg.message_metadata || {};
            // Skip world-state UI dividers in the export
            if (meta.source === 'world_state') {
                const parts = [];
                if (meta.location) parts.push(`📍 ${meta.location}`);
                if (meta.time)     parts.push(`🕐 ${meta.time}`);
                if (parts.length)  lines.push(`\n*— ${parts.join(' · ')} —*\n`);
                continue;
            }
            const label = ROLE_LABEL[msg.role] ?? '✦ System';
            lines.push(`**${label}:**`);
            lines.push(msg.content);
            if (msg.image_path) lines.push(`*[Image: ${msg.image_path}]*`);
            lines.push('');
        }

        const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `${chatName.replace(/[^a-z0-9_\- ]/gi, '_')}.md`;
        a.click();
        URL.revokeObjectURL(url);
        toast.success('Chat exported as Markdown');
    };

    const linkedCharacter = characters.find(c => c.id === activeChat?.character_id);

    const renderRow = (item) => {
        if (item.item) {
            const msg = item.item;
            const idx = messages.findIndex(m => (m.id || m._idx) === (msg.id || msg._idx));
            return (
                <MessageItem
                    msg={msg}
                    linkedCharacter={linkedCharacter}
                    activeChat={activeChat}
                    canRegenerate={idx === messages.length - 1}
                    onEdit={handleEditMessage}
                    onRegenerate={handleRegenerate}
                    onRollback={handleRollback}
                    onPin={handlePinMessage}
                    onSwipe={handleSwipe}
                    onAvatarClick={handleAvatarClick}
                />
            );
        }
        const { jobId, jobData } = item;
        if (jobData.taskType === 'image' || jobData.type === 'image') {
            return (
                <div className="self-start w-full max-w-[85%] sm:max-w-md">
                    <div className="text-[10px] text-green-400 ml-1 flex items-center gap-1.5 mb-1">
                        <ImageIcon size={10} /> Generating scene image
                    </div>
                    <div className="rounded-2xl border border-gray-700/40 bg-gray-900/60 p-3 overflow-hidden shadow-inner">
                        <div className="flex gap-3">
                            <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-xl bg-gray-800 animate-pulse shimmer" />
                            <div className="flex-1 space-y-2 py-1">
                                <div className="h-2.5 w-3/4 rounded bg-gray-800 animate-pulse" />
                                <div className="h-2.5 w-1/2 rounded bg-gray-800 animate-pulse" />
                                <div className="h-2.5 w-2/3 rounded bg-gray-800 animate-pulse" />
                                {jobData.progress != null ? (
                                    <div className="pt-2">
                                        <div className="h-1.5 w-full rounded-full bg-gray-800 overflow-hidden">
                                            <div className="h-full bg-gradient-to-r from-green-500 to-emerald-400 rounded-full transition-all" style={{ width: `${jobData.progress}%` }} />
                                        </div>
                                        <div className="text-[10px] text-green-400/80 mt-1 flex items-center gap-1">
                                            <Loader2 size={10} className="animate-spin" />
                                            Rendering {jobData.progress}%
                                        </div>
                                    </div>
                                ) : (
                                    <div className="pt-2 text-[10px] text-purple-400 flex items-center gap-1">
                                        <Wand2 size={10} className="animate-pulse" />
                                        Preparing generation...
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            );
        }
        return (
            <div key={jobId} className="flex gap-2 sm:gap-3 max-w-[90%] sm:max-w-[85%] self-start flex-row">
                <button
                    type="button"
                    onClick={() => linkedCharacter?.avatar_path && handleAvatarClick(getAvatarUrl(linkedCharacter.id))}
                    className={clsx(
                        "w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden self-end",
                        linkedCharacter?.avatar_path && "cursor-pointer hover:border-blue-500/50 transition-colors"
                    )}
                >
                    {linkedCharacter?.avatar_path
                        ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                        : <MessageSquare className="text-blue-400" size={12} />
                    }
                </button>
                <div className="flex flex-col max-w-full">
                    <div className="text-[10px] mb-1 text-gray-400 flex items-center gap-1.5">
                        <span>{linkedCharacter?.name || 'AI'}</span>
                        <span className="inline-flex items-center gap-0.5 text-blue-400/70">
                            <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                            <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                            <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                        </span>
                    </div>
                    <div className="px-4 py-3 rounded-2xl rounded-tl-sm text-sm bg-gray-800/50 text-gray-200 border border-gray-700/40 leading-relaxed">
                        {jobData.text ? (
                            <TavernMessage content={jobData.text + '\u25CD'} />
                        ) : (
                            <span className="flex items-center gap-2 text-gray-400 text-sm italic">
                                *{linkedCharacter?.name || 'AI'} is thinking...*
                            </span>
                        )}
                    </div>
                </div>
            </div>
        );
    };

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col h-full relative overflow-hidden bg-gray-900"
        >
            {/* === THREE-COLUMN ROW (fills remaining height above mobile tab bar) === */}
            <div className="flex flex-1 flex-row min-h-0 overflow-hidden">
            <div className={clsx(
                "flex-col shrink-0 border-b lg:border-r border-white/5 bg-gray-900 flex-1 lg:flex-none overflow-hidden min-w-0",
                "w-full",
                chatsCollapsed ? "lg:w-0 lg:border-r-0" : "lg:w-72",
                mobileTab === 'chats' ? "flex" : "hidden lg:flex"
            )}>
                <div className="h-12 lg:h-16 flex items-center justify-between px-4 border-b border-white/5 shrink-0">
                    <h3 className="font-semibold text-gray-200 tracking-wide">Chats</h3>
                    <button
                        onClick={() => handleCreateChat()}
                        className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                        title="New chat"
                    >
                        <Plus size={18} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1 custom-scrollbar">
                    {isChatsLoading ? (
                        <div className="flex justify-center p-4"><Loader2 className="animate-spin text-gray-500" size={20} /></div>
                    ) : chats?.length === 0 ? (
                        <div className="text-center py-8 text-gray-600 text-sm px-4">
                            <MessageSquare size={28} className="mx-auto mb-2 opacity-40" />
                            <p>No chats yet</p>
                            <p className="text-xs mt-1">Click + to create one</p>
                        </div>
                    ) : chats?.map(chat => (
                        <div key={chat.id} className="relative group">
                            {renamingChatId === chat.id ? (
                                <div className="flex items-center gap-1 px-1">
                                    <input
                                        autoFocus
                                        value={renameValue}
                                        onChange={e => setRenameValue(e.target.value)}
                                        onKeyDown={e => { if (e.key === 'Enter') finishRename(); if (e.key === 'Escape') setRenamingChatId(null); }}
                                        onBlur={finishRename}
                                        className="flex-1 bg-gray-800 border border-blue-500/50 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none"
                                    />
                                </div>
                            ) : (
                                <div
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => { setActiveChatId(chat.id); setMobileTab('chat'); }}
                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveChatId(chat.id); setMobileTab('chat'); } }}
                                    className={clsx(
                                        "w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all flex items-center gap-2.5 cursor-pointer",
                                        activeChatId === chat.id
                                            ? "bg-blue-500/20 text-blue-300 border border-blue-500/20"
                                            : "text-gray-400 hover:bg-white/5 border border-transparent"
                                    )}
                                >
                                    {(() => {
                                        const c = characters.find(ch => ch.id === chat.character_id);
                                        return (
                                            <div className="w-6 h-6 rounded-full bg-gray-700/60 flex items-center justify-center shrink-0 overflow-hidden border border-white/5">
                                                {c?.avatar_path
                                                    ? <img src={getAvatarUrl(c.id)} alt="" className="w-full h-full object-cover" />
                                                    : <MessageSquare size={10} className="text-gray-500" />
                                                }
                                            </div>
                                        );
                                    })()}
                                    <span className="truncate flex-1">{chat.name || 'Unnamed Chat'}</span>
                                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                                        <button onClick={e => { e.stopPropagation(); startRename(chat); }} className="p-1 hover:text-white text-gray-500 rounded"><Edit3 size={11} /></button>
                                        <button onClick={e => { e.stopPropagation(); handleDeleteChat(chat); }} className="p-1 hover:text-red-400 text-gray-500 rounded"><Trash2 size={11} /></button>
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            <div className={clsx(
                "flex-col min-w-0 bg-[#0B0E14] relative flex-1 lg:flex-auto",
                mobileTab === 'chat' ? "flex" : "hidden lg:flex"
            )}>
                <div className="h-12 lg:h-16 border-b border-white/5 flex items-center justify-between px-3 sm:px-4 shrink-0 bg-gray-900/40 backdrop-blur-md z-10 gap-2">
                    <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
                        <button
                            type="button"
                            onClick={() => setChatsCollapsed(c => !c)}
                            className="hidden lg:flex p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors shrink-0"
                            title={chatsCollapsed ? 'Show chats panel' : 'Hide chats panel'}
                        >
                            {chatsCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
                        </button>
                        <button 
                            type="button"
                            onClick={() => linkedCharacter?.avatar_path && handleAvatarClick(getAvatarUrl(linkedCharacter.id))}
                            className={clsx(
                                "w-9 h-9 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden",
                                linkedCharacter?.avatar_path && "cursor-pointer hover:border-blue-500/50 transition-colors"
                            )}
                        >
                            {linkedCharacter?.avatar_path
                                ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                                : <MessageSquare className="text-blue-400" size={16} />
                            }
                        </button>
                        <div className="min-w-0 flex-1">
                            <h2 className="font-semibold text-gray-100 flex items-center gap-2 text-sm sm:text-base">
                                <span className="truncate">{activeChat?.name || 'Roleplay Session'}</span>
                                <button
                                    onClick={triggerAutoTitle}
                                    disabled={isGeneratingTitle}
                                    className="text-[9px] bg-blue-500/10 text-blue-400 px-1.5 py-0.5 rounded hover:bg-blue-500/20 transition-colors flex items-center gap-1 disabled:opacity-50 shrink-0"
                                >
                                    {isGeneratingTitle ? <Loader2 size={9} className="animate-spin" /> : <Sparkles size={9} />}
                                    <span className="hidden sm:inline">Title</span>
                                </button>
                            </h2>
                            <p className="text-[10px] text-gray-500 truncate">
                                {linkedCharacter ? `${linkedCharacter.name}` : (activeChatId ? 'No character' : 'Select a chat')}
                                {activeChat?.persona_name && ` · as ${activeChat.persona_name}`}
                            </p>
                        </div>
                    </div>
                    
                    <div className="hidden md:flex items-center gap-2 mr-1 shrink-0">
                        {activeChat?.story_time && (
                            <div className="px-2.5 py-1 bg-gray-800/50 border border-white/5 rounded text-[11px] font-medium text-gray-300 flex items-center gap-1.5 shadow-sm" title="Story Time">
                                <Clock size={12} className="text-indigo-400/70" /> 
                                <span className="max-w-[120px] truncate">{activeChat.story_time}</span>
                            </div>
                        )}
                        {activeChat?.story_location && (
                            <div className="px-2.5 py-1 bg-gray-800/50 border border-white/5 rounded text-[11px] font-medium text-gray-300 flex items-center gap-1.5 shadow-sm" title="Story Location">
                                <MapPin size={12} className="text-rose-400/70" /> 
                                <span className="max-w-[160px] truncate">{activeChat.story_location}</span>
                            </div>
                        )}
                    </div>
                    <button
                        onClick={handleExportChat}
                        disabled={!activeChatId || !messages.length}
                        className="p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors disabled:opacity-30 disabled:cursor-not-allowed hidden lg:block"
                        title="Export chat as Markdown"
                    >
                        <Download size={18} />
                    </button>
                    {contextCollapsed && (
                        <button
                            onClick={() => setContextCollapsed(false)}
                            className="hidden lg:flex p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors shrink-0"
                            title="Show Context & Settings panel"
                        >
                            <PanelRightOpen size={18} />
                        </button>
                    )}
                </div>
                <div className="flex-1 overflow-y-auto p-3 sm:p-4 lg:p-6 custom-scrollbar" ref={listContainerRef}>
                    {!activeChatId && messages.length === 0 ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-center opacity-50 gap-3">
                            <Sparkles className="w-10 h-10 text-blue-500 opacity-50" />
                            <div>
                                <h3 className="text-base font-medium text-gray-300">Chat Workspace</h3>
                                <p className="text-sm text-gray-500 max-w-xs mt-1">
                                    Select a chat or create a new one to begin your roleplay.
                                </p>
                            </div>
                        </div>
                    ) : (
                        <>
                            <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: 'relative', width: '100%' }}>
                                {rowVirtualizer.getVirtualItems().map(virtualItem => (
                                    <div
                                        key={listItems[virtualItem.index]._key || virtualItem.index}
                                        data-index={virtualItem.index}
                                        ref={rowVirtualizer.measureElement}
                                        className="mb-4 flex flex-col"
                                        style={{
                                            position: 'absolute',
                                            top: 0,
                                            left: 0,
                                            width: '100%',
                                            transform: `translateY(${virtualItem.start}px)`,
                                        }}
                                    >
                                        {renderRow(listItems[virtualItem.index])}
                                    </div>
                                ))}
                            </div>
                            <div ref={messagesEndRef} />
                        </>
                    )}
                </div>

                <div className="px-3 sm:px-4 lg:px-6 py-3 sm:py-4 pb-4 border-t border-white/5 bg-gray-900/40 backdrop-blur-md shrink-0">
                    <div className="max-w-4xl mx-auto">
                        {pendingAttachment && (
                            <div className="mb-2 flex items-center gap-2 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-xl text-sm text-blue-300">
                                <ImageIcon size={13} className="shrink-0" />
                                <span className="truncate flex-1 text-xs">{pendingAttachment.name}</span>
                                <button onClick={() => setPendingAttachment(null)} className="p-1 hover:text-red-400 transition-colors shrink-0">
                                    <X size={13} />
                                </button>
                            </div>
                        )}
                        <div className="relative">
                            {message.startsWith('/') && (
                                <div className="absolute bottom-full left-0 mb-2 w-full max-w-sm bg-gray-900/95 backdrop-blur-xl border border-gray-700/60 rounded-2xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-2">
                                    <div className="px-3 py-2 text-xs font-semibold text-gray-400 bg-gray-800/40 uppercase tracking-wider border-b border-gray-700/50">Commands</div>
                                    <div className="flex flex-col max-h-60 overflow-y-auto p-1">
                                        {COMMANDS.filter(c => !activeCommand && c.cmd.startsWith(message.split(' ')[0].toLowerCase())).map((c) => (
                                            <button
                                                key={c.cmd}
                                                onClick={() => {
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
                                                className="flex items-center gap-3 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left group"
                                            >
                                                <span className="text-lg opacity-80 group-hover:opacity-100 transition-opacity">{c.icon}</span>
                                                <div className="flex flex-col">
                                                    <span className="text-sm font-medium text-gray-200">{c.cmd}</span>
                                                    <span className="text-xs text-gray-400">{c.desc}</span>
                                                </div>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <input ref={fileInputRef} type="file" accept="image/*" onChange={handleAttachmentChange} className="hidden" />
                            
                            {/* Input Container */}
                            <div className="flex items-center w-full bg-gray-900/80 border border-gray-700/50 rounded-2xl pl-10 sm:pl-12 pr-24 sm:pr-44 py-3.5 sm:py-4 transition-all shadow-inner focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/30">
                                
                                {activeCommand && (
                                    <div className="flex items-center gap-1.5 px-2 py-1 bg-blue-500/20 text-blue-300 rounded-lg text-sm font-medium mr-2 whitespace-nowrap select-none ml-2">
                                        <span>{activeCommand.icon}</span>
                                        {activeCommand.cmd}
                                        <button onClick={() => { setActiveCommand(null); setMessage(activeCommand.cmd + ' ' + message); }} className="hover:text-white ml-1 opacity-60 hover:opacity-100 transition-opacity"><X size={14} /></button>
                                    </div>
                                )}
                                
                                <textarea
                                    ref={textareaRef}
                                    value={message}
                                    onChange={handleTextChange}
                                    onKeyDown={handleKeyDown}
                                    placeholder={activeCommand ? activeCommand.argPlaceholder : (activeChatId ? 'Type a message...' : 'Select a chat to start...')}
                                    className="flex-1 bg-transparent text-gray-200 placeholder-gray-500 focus:outline-none resize-none text-sm self-center min-h-[20px] max-h-[200px]"
                                    rows={1}
                                    disabled={sendMessageMutation.isPending || !activeChatId}
                                    style={{ overflowY: (textareaRef.current?.scrollHeight > 200) ? 'auto' : 'hidden' }}
                                />
                            </div>

                            {/* Left Button */}
                            <button
                                onClick={() => fileInputRef.current?.click()}
                                disabled={isUploading}
                                className="absolute left-2 sm:left-3 bottom-2.5 sm:bottom-3 p-1.5 sm:p-2 text-gray-400 hover:text-blue-400 transition-colors rounded-xl hover:bg-blue-500/10 disabled:opacity-50"
                                title="Attach image"
                            >
                                {isUploading ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
                            </button>

                            {/* Right Buttons Group */}
                            <div className="absolute right-2 sm:right-3 bottom-2.5 sm:bottom-3 flex items-center gap-1">
                                {/* Mobile overflow menu — keeps the 5 secondary tools
                                    reachable without letting 6 touch-sized buttons
                                    (~284px) cover the whole textarea on phones. */}
                                <button
                                    onClick={() => setShowMoreTools(v => !v)}
                                    className="sm:hidden p-1.5 text-gray-400 hover:text-white transition-colors rounded-xl hover:bg-white/10"
                                    title="More tools"
                                    aria-label="More tools"
                                >
                                    <MoreHorizontal size={18} />
                                </button>

                                {showMoreTools && (
                                    <div className="absolute bottom-full right-0 mb-2 w-48 bg-gray-900/95 backdrop-blur-xl border border-gray-700/60 rounded-2xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-2">
                                        <div className="px-3 py-2 text-xs font-semibold text-gray-400 bg-gray-800/40 uppercase tracking-wider border-b border-gray-700/50">Tools</div>
                                        <div className="flex flex-col p-1">
                                            <button
                                                onClick={() => { setShowMoreTools(false); handleGenerateScene(); }}
                                                disabled={isGeneratingScene || !activeChatId}
                                                className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm text-gray-200 disabled:opacity-50"
                                            >
                                                <ImageIcon size={16} className="text-green-400" />
                                                {isGeneratingScene ? 'Generating...' : 'Generate scene'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); handleIllustrate(); }}
                                                disabled={illustrateMutation.isPending || !activeChatId}
                                                className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm text-gray-200 disabled:opacity-50"
                                            >
                                                <Palette size={16} className="text-pink-400" />
                                                {illustrateMutation.isPending ? 'Illustrating...' : 'Illustrate moment'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); setAgenticMode(!agenticMode); }}
                                                className={clsx("flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm", agenticMode ? "text-purple-400" : "text-gray-200")}
                                            >
                                                <Wand2 size={16} className="text-purple-400" />
                                                Agentic {agenticMode ? 'ON' : 'OFF'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); setNarrateMode(!narrateMode); }}
                                                className={clsx("flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm", narrateMode ? "text-purple-400" : "text-gray-200")}
                                            >
                                                <BookOpen size={16} className="text-purple-400" />
                                                Narrate {narrateMode ? 'ON' : 'OFF'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); handleImpersonate(); }}
                                                disabled={!activeChatId || impersonateMutation.isPending}
                                                className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm text-gray-200 disabled:opacity-50"
                                            >
                                                <Ghost size={16} className="text-purple-400" />
                                                {impersonateMutation.isPending ? 'Impersonating...' : 'Impersonate'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); handleSuggestClick(); }}
                                                disabled={!activeChatId || suggestReplyMutation.isPending || suggestJobId}
                                                className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm text-gray-200 disabled:opacity-50"
                                            >
                                                <Sparkles size={16} className="text-blue-400" />
                                                {(suggestReplyMutation.isPending || suggestJobId) ? 'Suggesting...' : 'Suggest reply'}
                                            </button>
                                        </div>
                                    </div>
                                )}

                                {/* Secondary tools — inline on sm+ screens only */}
                                <div className="hidden sm:flex items-center gap-1">
                                {/* Generate scene */}
                                <button
                                    onClick={handleGenerateScene}
                                    disabled={isGeneratingScene || !activeChatId}
                                    className="p-1.5 sm:p-2 text-gray-400 hover:text-green-400 transition-colors rounded-xl hover:bg-green-500/10 disabled:opacity-50"
                                    title="Generate Scene"
                                >
                                    {isGeneratingScene ? <Loader2 size={18} className="animate-spin" /> : <ImageIcon size={18} />}
                                </button>
                                {/* Illustrate moment — direct image job from draft or last reply */}
                                <button
                                    onClick={handleIllustrate}
                                    disabled={illustrateMutation.isPending || !activeChatId}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-colors rounded-xl",
                                        illustrateMutation.isPending
                                            ? "text-pink-400 bg-pink-500/10 cursor-not-allowed"
                                            : (activeChatId ? "text-gray-400 hover:text-pink-400 hover:bg-pink-500/10" : "text-gray-600 cursor-not-allowed")
                                    )}
                                    title="Illustrate moment — generates an image from your draft or the latest reply"
                                >
                                    {illustrateMutation.isPending ? <Loader2 size={18} className="animate-spin" /> : <Palette size={18} />}
                                </button>
                                {/* Agentic mode */}
                                <button
                                    onClick={() => setAgenticMode(!agenticMode)}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-colors rounded-xl",
                                        agenticMode
                                            ? "text-purple-400 hover:text-purple-300 hover:bg-purple-500/10"
                                            : "text-gray-500 hover:text-gray-400 hover:bg-white/5"
                                    )}
                                    title={agenticMode ? "Agentic ON" : "Agentic OFF"}
                                >
                                    <Wand2 size={18} />
                                </button>
                                {/* Narrate mode */}
                                <button
                                    onClick={() => setNarrateMode(!narrateMode)}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-colors rounded-xl",
                                        narrateMode
                                            ? "text-purple-400 hover:text-purple-300 hover:bg-purple-500/10"
                                            : "text-gray-500 hover:text-gray-400 hover:bg-white/5"
                                    )}
                                    title={narrateMode ? "Narrate ON — next message triggers the narrator" : "Narrate OFF"}
                                >
                                    <BookOpen size={18} />
                                </button>
                                {/* Impersonate */}
                                <button
                                    onClick={() => handleImpersonate()}
                                    disabled={!activeChatId || impersonateMutation.isPending}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-all rounded-xl",
                                        impersonateMutation.isPending
                                            ? "text-purple-400 bg-purple-500/10 cursor-not-allowed"
                                            : (activeChatId ? "text-gray-400 hover:text-purple-400 hover:bg-purple-500/10" : "text-gray-600 cursor-not-allowed")
                                    )}
                                    title="Impersonate — AI writes your next message then triggers a reply"
                                >
                                    {impersonateMutation.isPending
                                        ? <Loader2 size={16} className="animate-spin" />
                                        : <Ghost size={16} />}
                                </button>
                                {/* Suggest */}
                                <button
                                    onClick={handleSuggestClick}
                                    disabled={!activeChatId || suggestReplyMutation.isPending || suggestJobId}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-all rounded-xl",
                                        (suggestReplyMutation.isPending || suggestJobId)
                                            ? "text-blue-400 bg-blue-500/10 cursor-not-allowed"
                                            : (activeChatId ? "text-blue-400 hover:text-white hover:bg-blue-600/50" : "text-gray-600 cursor-not-allowed")
                                    )}
                                    title="Auto-suggest reply"
                                >
                                    {(suggestReplyMutation.isPending || suggestJobId) 
                                        ? <Loader2 size={16} className="animate-spin" />
                                        : <Sparkles size={16} />}
                                </button>
                                </div>
                                {/* Send */}
                                <button
                                    onClick={handleSendMessage}
                                    disabled={!canSend}
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
                            </div>
                        </div>
                        <div className="mt-1.5 hidden sm:flex items-center justify-between px-1 text-[10px] text-gray-600">
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
            </div>

            {/* === CONTEXT PANEL (Right) === */}
            <div className={clsx(
                "flex-col shrink-0 border-l border-white/5 bg-gray-900 lg:bg-gray-900/70 flex-1 lg:flex-none overflow-hidden min-w-0",
                "w-full",
                contextCollapsed ? "lg:w-0 lg:border-l-0" : "lg:w-72",
                mobileTab === 'context' ? "flex" : "hidden lg:flex"
            )}>
                <div className="h-12 lg:h-16 border-b border-white/5 flex items-center justify-between px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                    <h3 className="font-semibold text-gray-200 flex items-center gap-2 text-sm">
                        <Settings size={14} className="text-gray-400" />
                        Context &amp; Settings
                    </h3>
                    <button
                        onClick={() => setMobileTab('chat')}
                        className="lg:hidden p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors"
                    >
                        <X size={16} />
                    </button>
                    <button
                        onClick={() => setContextCollapsed(c => !c)}
                        className="hidden lg:flex p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors"
                        title="Hide context panel"
                    >
                        <PanelRightClose size={18} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
                    {/* Persona Name */}
                    <div className="glass-panel p-4 rounded-xl border border-white/5">
                        <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                            <User size={12} /> Your Persona
                        </h4>
                        <ContextField
                            label="Your Persona"
                            icon={User}
                            value={activeChat?.persona_name}
                            placeholder="Default (User)"
                            onSave={val => handleChatUpdate({ persona_name: val })}
                        />
                        {/* Persona description */}
                        <div className="mt-3">
                            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">
                                Description
                            </label>
                            <textarea
                                key={`persona-desc-${activeChatId}`}
                                defaultValue={activeChat?.persona_description || ''}
                                onBlur={(e) => {
                                    const val = e.target.value.trim() || null;
                                    if (val !== (activeChat?.persona_description || null)) {
                                        handleChatUpdate({ persona_description: val });
                                    }
                                }}
                                placeholder={
                                    linkedCharacter?.suggested_persona
                                        ? `Suggested: ${linkedCharacter.suggested_persona.slice(0, 60)}…`
                                        : 'Describe your character — who you are in this roleplay…'
                                }
                                rows={2}
                                className="w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg px-2.5 py-2 text-gray-300 placeholder-gray-600 focus:outline-none focus:border-blue-500/40 resize-none"
                            />
                            {linkedCharacter?.suggested_persona && !activeChat?.persona_description && (
                                <button
                                    type="button"
                                    onClick={() => handleChatUpdate({ persona_description: linkedCharacter.suggested_persona })}
                                    className="mt-1 text-[9px] text-blue-400 hover:text-blue-300 transition-colors"
                                >
                                    Use {linkedCharacter.name}'s suggestion
                                </button>
                            )}
                        </div>
                        <p className="text-[10px] text-gray-600 mt-2 px-1">
                            Sets <code className="text-gray-500">{'{{user}}'}</code> and injects a persona block into the system prompt.
                        </p>
                    </div>
                    
                    {/* World State */}
                    <ContextField
                        label="Story Time"
                        icon={Clock}
                        value={activeChat?.story_time}
                        placeholder="Not set"
                        onSave={val => handleChatUpdate({ story_time: val })}
                    />
                    
                    <ContextField
                        label="Location"
                        icon={MapPin}
                        value={activeChat?.story_location}
                        placeholder="Not set"
                        onSave={val => handleChatUpdate({ story_location: val })}
                    />

                    {/* Chat Jobs (LLM + image progress for this chat) */}
                    <div className="glass-panel p-4 rounded-xl border border-white/5">
                        <div className="flex items-center justify-between mb-2">
                            <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                                <Activity size={12} /> Jobs
                            </h4>
                            <span className="text-[9px] text-gray-600">{chatJobs?.length || 0} total</span>
                        </div>
                        {!chatJobs?.length ? (
                            <p className="text-xs text-gray-600">No jobs tracked for this chat yet.</p>
                        ) : (
                            <div className="space-y-1.5 max-h-48 overflow-y-auto custom-scrollbar">
                                {chatJobs.slice(0, 10).map((job) => {
                                    const isRunning = job.status === 'generating' || job.status === 'pre_generation' || job.status === 'post_processing';
                                    const isImage = job.task_type === 'image' || job.type === 'image' || job.type === 'agentic_image';
                                    const isFailed = job.status === 'failed';
                                    const isComplete = job.status === 'completed';
                                    return (
                                        <div key={job.id} className={clsx(
                                            "flex items-center gap-2 px-2.5 py-2 rounded-lg text-[10px] border",
                                            isFailed ? "bg-red-500/5 border-red-500/15 text-red-300" :
                                            isComplete ? (isImage ? "bg-emerald-500/5 border-emerald-500/15 text-emerald-300" : "bg-blue-500/5 border-blue-500/15 text-blue-300") :
                                            isRunning ? "bg-amber-500/5 border-amber-500/15 text-amber-300" : "bg-gray-800/30 border-gray-700/30 text-gray-400"
                                        )}>
                                            <span className={clsx("w-1.5 h-1.5 rounded-full shrink-0", isFailed ? "bg-red-400" : isComplete ? (isImage ? "bg-emerald-400" : "bg-blue-400") : isRunning ? "bg-amber-400 animate-pulse" : "bg-gray-600")} />
                                            <span className="truncate flex-1 font-medium">{isImage ? (job.type === 'agentic_image' ? 'Image generation' : 'Image job') : 'LLM reply'}</span>
                                            <span className="text-[9px] text-gray-500 shrink-0">{isFailed ? 'Failed' : isComplete ? 'Done' : isRunning ? 'Active' : job.status}</span>
                                            {isRunning && job.overall_progress != null && (
                                                <span className="text-[9px] text-amber-300/80 shrink-0">{Math.round(job.overall_progress)}%</span>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    {/* Character */}
                    <div className="glass-panel p-4 rounded-xl border border-white/5">
                        <div className="flex items-center justify-between mb-3">
                            <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                                <User size={12} /> Character
                            </h4>
                            {/* Constrained width + native truncation so long names don't overflow */}
                            <select
                                value={activeChat?.character_id || ''}
                                onChange={(e) => handleChatUpdate({ character_id: e.target.value || null })}
                                className="bg-gray-800 border border-gray-700 text-xs rounded px-2 py-1 text-gray-300 focus:outline-none max-w-[140px] truncate"
                            >
                                <option value="">None</option>
                                {characters.map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </select>
                        </div>
                        {linkedCharacter ? (
                            <div 
                                className="flex items-center gap-3 p-2 bg-gray-800/30 hover:bg-gray-800/60 rounded-lg cursor-pointer transition-colors group"
                                onClick={() => setShowCharacterDetails(true)}
                                title="View character details"
                            >
                                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center shrink-0 overflow-hidden border border-white/10 group-hover:border-blue-500/30 transition-colors">
                                    {linkedCharacter.avatar_path
                                        ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                                        : <MessageSquare size={14} className="text-blue-400" />
                                    }
                                </div>
                                <div className="min-w-0 flex-1">
                                    <p className="text-sm text-gray-200 truncate font-medium group-hover:text-blue-100 transition-colors">{linkedCharacter.name}</p>
                                    <p className="text-[10px] text-blue-400 mt-0.5 opacity-80 group-hover:opacity-100">View details</p>
                                </div>
                            </div>
                        ) : (
                            <p className="text-sm text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">
                                No character assigned
                            </p>
                        )}
                    </div>

                    {/* AI Model + Image generation */}
                    <div className="glass-panel p-4 rounded-xl border border-white/5 space-y-3">
                        <div>
                            <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 mb-2">
                                <Sparkles size={12} /> AI Model
                            </h4>
                            <select
                                value={activeChat?.llm_model || ''}
                                onChange={(e) => handleChatUpdate({ llm_model: e.target.value || null })}
                                className="w-full bg-gray-800 border border-gray-700 text-xs rounded px-2 py-1.5 text-gray-300 focus:outline-none"
                                title="Per-chat model override (falls back to the global default)"
                            >
                                <option value="">Default ({defaultLlmConfig?.model_id || 'default'})</option>
                                {availableModels.map(m => (
                                    <option key={m.id} value={m.id}>{m.name}</option>
                                ))}
                            </select>
                        </div>

                        {/* Context window size */}
                        <div>
                            <div className="flex items-center justify-between mb-1.5">
                                <p className="text-xs text-gray-300 font-medium">Context Window</p>
                                <span className="text-[10px] text-gray-500 font-mono">
                                    {activeChat?.max_context_tokens
                                        ? `${(activeChat.max_context_tokens / 1024).toFixed(0)}k tokens`
                                        : 'Global default'}
                                </span>
                            </div>
                            <ContextSlider
                                activeChat={activeChat}
                                onChange={(val) => handleChatUpdate({ max_context_tokens: val })}
                            />
                            <div className="flex justify-between text-[9px] text-gray-600 mt-0.5">
                                <span>2k</span><span>32k</span><span>64k</span><span>128k</span>
                            </div>
                            {activeChat?.max_context_tokens && (
                                <button
                                    onClick={() => handleChatUpdate({ max_context_tokens: null })}
                                    className="mt-1 text-[9px] text-gray-500 hover:text-red-400 transition-colors"
                                >
                                    Reset to global default
                                </button>
                            )}
                        </div>
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-xs text-gray-300 font-medium">Allow image generation</p>
                                <p className="text-[10px] text-gray-600 mt-0.5">
                                    Lets the LLM call the <code className="text-gray-500">generate_image</code> tool in agentic mode.
                                </p>
                            </div>
                            <button
                                role="switch"
                                aria-checked={activeChat?.allow_image_generation !== false}
                                onClick={() => handleChatUpdate({ allow_image_generation: activeChat?.allow_image_generation === false })}
                                className={clsx(
                                    "relative w-10 h-5 rounded-full transition-colors shrink-0",
                                    activeChat?.allow_image_generation !== false ? "bg-purple-500" : "bg-gray-700"
                                )}
                            >
                                <span className={clsx(
                                    "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all",
                                    activeChat?.allow_image_generation !== false ? "left-5.5" : "left-0.5"
                                )} />
                            </button>
                        </div>
                        <div className="flex items-center justify-between">
                            <div>
                                <p className="text-xs text-gray-300 font-medium">Allow narration</p>
                                <p className="text-[10px] text-gray-600 mt-0.5">
                                    Lets the LLM call the <code className="text-gray-500">narrate_scene</code> tool when the story calls for it.
                                </p>
                            </div>
                            <button
                                role="switch"
                                aria-checked={activeChat?.allow_narration !== false}
                                onClick={() => handleChatUpdate({ allow_narration: activeChat?.allow_narration === false })}
                                className={clsx(
                                    "relative w-10 h-5 rounded-full transition-colors shrink-0",
                                    activeChat?.allow_narration !== false ? "bg-purple-500" : "bg-gray-700"
                                )}
                            >
                                <span className={clsx(
                                    "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all",
                                    activeChat?.allow_narration !== false ? "left-5.5" : "left-0.5"
                                )} />
                            </button>
                        </div>
                    </div>

                    {/* System prompt */}
                    <SystemPromptPanel
                        activeChat={activeChat}
                        linkedCharacter={linkedCharacter}
                        systemPromptData={systemPromptData}
                        onChatUpdate={handleChatUpdate}
                        onCharacterPatch={(updates) => {
                            if (!linkedCharacter) return;
                            patchCharacterMutation.mutate({ id: linkedCharacter.id, ...updates });
                        }}
                    />

                    {/* Scenes */}
                    <div className="glass-panel p-4 rounded-xl border border-white/5">
                        <div className="flex items-center justify-between mb-3">
                            <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                                <ImageIcon size={12} /> Scenes
                            </h4>
                            {(() => {
                                const sceneStream = activeStreamEntries.find(
                                    (item) => item.jobId && item.jobData?.chatId === activeChatId && (item.jobData?.type === 'image' || item.jobData?.taskType === 'image')
                                );
                                return sceneStream ? (
                                    <span className="text-[10px] text-green-400 flex items-center gap-1">
                                        <Loader2 size={10} className="animate-spin" />
                                        {Math.round(sceneStream.jobData?.progress ?? 0)}%
                                    </span>
                                ) : (
                                    <span className="text-[10px] text-gray-600">
                                        {chatCollection?.image_count || 0} image{(chatCollection?.image_count || 0) !== 1 ? 's' : ''}
                                    </span>
                                );
                            })()}
                        </div>
                        {sceneJobId && (
                            <div className="mb-2">
                                <div className="flex items-center gap-2 text-[10px] text-purple-400 mb-1">
                                    <Loader2 size={12} className="animate-spin" />
                                    Generating scene image...
                                </div>
                                <div className="h-1.5 w-full rounded-full bg-gray-800 overflow-hidden">
                                    <div className="h-full bg-gradient-to-r from-purple-500 to-indigo-400 rounded-full transition-all animate-pulse" style={{ width: '60%' }} />
                                </div>
                            </div>
                        )}
                        {activeChat?.character_id ? (
                            <button
                                onClick={() => setShowScenesModal(true)}
                                disabled={!!sceneJobId}
                                className="w-full mt-3 py-2 text-xs font-medium bg-gray-800/50 hover:bg-gray-800 border border-white/5 hover:border-white/10 rounded-lg transition-colors text-gray-300 disabled:opacity-50"
                            >
                                View Scenes Gallery
                            </button>
                        ) : (
                            <p className="mt-3 text-xs text-gray-500 text-center py-2 border border-dashed border-gray-700/50 rounded-lg">
                                Assign a character to see their scenes
                            </p>
                        )}
                    </div>

                    {/* Lorebooks */}
                    <div className="glass-panel p-4 rounded-xl border border-white/5">
                        <div className="flex items-center justify-between mb-3">
                            <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                                <BookOpen size={12} /> Lorebooks
                            </h4>
                            <a href="/characters" className="text-[9px] text-blue-400 hover:text-blue-300 font-medium px-1.5 py-0.5 rounded bg-blue-500/10 hover:bg-blue-500/20 transition-colors">
                                Manage
                            </a>
                        </div>
                        {lorebooks.length === 0 ? (
                            <p className="text-xs text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">
                                No lorebooks available
                            </p>
                        ) : (
                            <div className="space-y-1.5">
                                {lorebooks.map(lb => {
                                    const isActive = selectedLorebooks.includes(lb.id);
                                    return (
                                        <button
                                            key={lb.id}
                                            onClick={() => {
                                                const newLorebooks = isActive 
                                                    ? selectedLorebooks.filter(id => id !== lb.id)
                                                    : [...selectedLorebooks, lb.id];
                                                handleChatUpdate({ active_lorebook_ids: newLorebooks });
                                            }}
                                            className={clsx(
                                                "w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all",
                                                isActive
                                                    ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                                                    : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                            )}
                                        >
                                            {isActive
                                                ? <Check size={13} className="text-indigo-400 shrink-0" />
                                                : <div className="w-3 h-3 rounded border border-gray-600 shrink-0" />
                                            }
                                            <span className="truncate font-medium text-xs">{lb.name}</span>
                                        </button>
                                    );
                                })}
                            </div>
                        )}
                        {selectedLorebooks.length > 0 && (
                            <p className="text-[10px] text-gray-500 mt-2 px-1">
                                {selectedLorebooks.length} lorebook{selectedLorebooks.length !== 1 ? 's' : ''} active
                            </p>
                        )}
                    </div>
                </div>
            </div>
            </div>{/* === END THREE-COLUMN ROW === */}

            {/* === MODALS === */}
            <AnimatePresence>
                {showNewChatModal && (
                    <NewChatModal
                        characters={characters}
                        lorebooks={lorebooks}
                        onCreate={confirmCreateChat}
                        onClose={() => setShowNewChatModal(false)}
                    />
                )}
                {showCharacterDetails && (
                    <CharacterDetailsModal
                        character={linkedCharacter}
                        onClose={() => setShowCharacterDetails(false)}
                    />
                )}
                {greetingModal && (
                    <GreetingPickerModal
                        character={greetingModal.character}
                        onSelect={greetingModal.onCreate}
                        onClose={() => { setGreetingModal(null); hasCreatedChatRef.current = false; }}
                    />
                )}
            </AnimatePresence>

            {showScenesModal && (
                <div className="fixed inset-0 z-[60] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
                    <motion.div
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        className="w-full max-w-5xl bg-gray-900 border border-white/10 rounded-3xl shadow-2xl flex flex-col h-[85vh]"
                    >
                        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                            <h3 className="font-bold text-gray-100 flex items-center gap-2">
                                <ImageIcon size={16} className="text-purple-400" />
                                {linkedCharacter?.name || 'Character'} Scenes
                            </h3>
                            <button onClick={() => setShowScenesModal(false)} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                                <X size={18} />
                            </button>
                        </div>
                        <div className="flex gap-2 px-6 pt-4 shrink-0">
                            <button
                                onClick={() => setSceneTab('chat')}
                                className={clsx('px-4 py-1.5 rounded-xl text-xs font-medium transition-colors', sceneTab === 'chat' ? 'bg-purple-500/20 text-purple-300' : 'bg-gray-800/60 text-gray-400 hover:text-gray-200')}
                            >
                                This chat ({chatImages.length})
                            </button>
                            <button
                                onClick={() => setSceneTab('collection')}
                                className={clsx('px-4 py-1.5 rounded-xl text-xs font-medium transition-colors', sceneTab === 'collection' ? 'bg-purple-500/20 text-purple-300' : 'bg-gray-800/60 text-gray-400 hover:text-gray-200')}
                            >
                                Character collection ({chatCollection?.image_count || 0})
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                            {sceneTab === 'chat' ? (
                                <SceneGallery
                                    title={`${linkedCharacter?.name || 'Character'} chat scenes`}
                                    images={chatImages.map(img => img.path)}
                                    lightboxAction={(path) => (
                                        <select
                                            value=""
                                            onChange={(e) => {
                                                if (e.target.value) {
                                                    handleSaveImageToCollection(e.target.value, path);
                                                    e.target.value = '';
                                                }
                                            }}
                                            className="bg-gray-800 border border-white/10 rounded-lg text-xs text-gray-200 px-2 py-1.5 cursor-pointer hover:border-blue-500/40 transition-colors"
                                            title="Save to collection"
                                        >
                                            <option value="">Save to…</option>
                                            {collectionsList.map(c => (
                                                <option key={c.id} value={c.id}>{c.name}</option>
                                            ))}
                                        </select>
                                    )}
                                />
                            ) : (
                                <SceneGallery
                                    title={`${linkedCharacter?.name || 'Character'} scenes`}
                                    images={chatCollection?.images || []}
                                />
                            )}
                        </div>
                    </motion.div>
                </div>
            )}
            {avatarModalSrc && (
                <div className="fixed inset-0 z-[100] bg-black/85 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setAvatarModalSrc(null)}>
                    <div className="flex items-center justify-between w-full absolute top-0 left-0 right-0 px-4 py-3">
                        <span className="text-xs text-gray-400">{linkedCharacter?.name || 'Avatar'}</span>
                        <button className="p-2 text-gray-300 hover:text-white rounded-xl hover:bg-white/10 transition-colors" onClick={() => setAvatarModalSrc(null)}>
                            <X size={18} />
                        </button>
                    </div>
                    <img
                        src={avatarModalSrc}
                        alt="Avatar"
                        className="max-h-[85vh] max-w-full rounded-xl shadow-2xl object-contain"
                        onClick={(e) => e.stopPropagation()}
                    />
                </div>
            )}
            {/* Shared mobile bottom tab bar (replaces the inline tab strip — issue #1/#1.2) */}
            <BottomTabBar
                inline
                tabs={[
                    { id: 'chats', label: 'Chats', icon: MessageSquare, color: 'text-blue-400' },
                    { id: 'chat', label: 'Roleplay', icon: Activity, color: 'text-purple-400' },
                    { id: 'context', label: 'Context', icon: Settings, color: 'text-amber-400' },
                ]}
                value={mobileTab}
                onChange={setMobileTab}
                label="Chat workspace navigation"
            />
        </motion.div>
    );
}
