import React, { useState, useEffect, useRef, useCallback, memo } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
    MessageSquare, Send, Image as ImageIcon, Settings,
    PanelRightClose, PanelRightOpen, Paperclip, Sparkles,
    Plus, Loader2, Trash2, Edit3, Edit2, BookOpen, Check, Wand2,
    User, X, ChevronRight, RotateCcw, Clock, MapPin
} from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useLocation } from 'react-router-dom';
import api from '../api/client';
import {
    useMessages, useChats, useSendMessage, useChat,
    useCreateChat, useDeleteChat, useLorebooks, useCharacters,
    useRenameChat, useUpdateChat, getAvatarUrl
} from '../hooks/useWorldVault';
import worldVaultApi from '../api/worldVault';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useWebSocket, EventTypes } from '../api/websocket';
import { useQueryClient } from '@tanstack/react-query';
import ConfirmationModal from '../components/ConfirmationModal';
import { parseTavernMessage } from '../utils/tavernUtils';
import { useSettings } from '../store/settingsStore';

// ---------------------------------------------------------------------------
// TavernMessage — renders narrative/dialogue with segment styling
// ---------------------------------------------------------------------------
const TavernMessage = memo(function TavernMessage({ content }) {
    const segments = parseTavernMessage(content);
    if (!segments.length) return <span>{content}</span>;
    return (
        <div className="flex flex-col gap-2.5 w-full">
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
                        <div key={i} className="px-4 py-3 rounded-2xl rounded-tl-sm bg-gray-800 border border-gray-700/50 text-gray-100 font-medium tracking-wide shadow-sm w-fit max-w-full break-words">
                            "{seg.content}"
                        </div>
                    );
                }
                return (
                    <div key={i} className="px-4 py-3 rounded-2xl rounded-tl-sm bg-gray-800/40 border border-gray-700/30 text-gray-300 text-sm shadow-sm w-fit max-w-full break-words leading-relaxed">
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
// Main Component
// ---------------------------------------------------------------------------
export default function ChatWorkspace() {
    const [mobileTab, setMobileTab] = useState('chat');
    const [message, setMessage] = useState('');
    const [renamingChatId, setRenamingChatId] = useState(null);
    const [renameValue, setRenameValue] = useState('');
    const [deleteTarget, setDeleteTarget] = useState(null);
    const hasCreatedChatRef = useRef(false);
    const [isGeneratingScene, setIsGeneratingScene] = useState(false);
    const [pendingAttachment, setPendingAttachment] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [agenticMode, setAgenticMode] = useState(true);
    const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);
    const [greetingModal, setGreetingModal] = useState(null);
    const [showNewChatModal, setShowNewChatModal] = useState(false);
    const [showCharacterDetails, setShowCharacterDetails] = useState(false);
    const fileInputRef = useRef(null);
    const messagesEndRef = useRef(null);
    const textareaRef = useRef(null);
    const location = useLocation();
    
    const settings = useSettings();

    const queryClient = useQueryClient();
    const activeChatId = useWorldVaultStore(state => state.activeChatId);
    const setActiveChatId = useWorldVaultStore(state => state.setActiveChat);
    const updateStreamingJob = useWorldVaultStore(state => state.updateStreamingJob);
    const clearStreamingJob = useWorldVaultStore(state => state.clearStreamingJob);
    const streamingJobs = useWorldVaultStore(state => state.streamingJobs);
    const selectedLorebooks = useWorldVaultStore(state => state.contextBuilder.selectedLorebooks);
    const toggleLorebook = useWorldVaultStore(state => state.toggleLorebook);

    const { data: chats, isLoading: isChatsLoading } = useChats();
    const { data: activeChat } = useChat(activeChatId);
    const { data: messages = [] } = useMessages(activeChatId);
    const { data: lorebooks = [] } = useLorebooks();
    const { data: characters = [] } = useCharacters();

    const sendMessageMutation = useSendMessage();
    const createChatMutation = useCreateChat();
    const deleteChatMutation = useDeleteChat();
    const renameChatMutation = useRenameChat();
    const updateChatMutation = useUpdateChat();

    const { subscribe } = useWebSocket();

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
                            _override_greeting: selectedGreeting 
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
    }, [location.state?.characterId, characters]);

    useEffect(() => {
        if (chats?.length > 0 && !activeChatId) {
            setActiveChatId(chats[0].id);
        }
    }, [chats, activeChatId, setActiveChatId]);

    useEffect(() => {
        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            const meta = event.metadata_ || event.metadata || {};
            const existingJob = useWorldVaultStore.getState().streamingJobs[event.id];
            const eventChatId = meta.chat_id || event.chat_id || existingJob?.chatId;
            const streamText = event.text || event.data?.text;
            if (streamText && eventChatId) {
                updateStreamingJob(event.id, { text: streamText, status: 'running', chatId: eventChatId });
            }
        });

        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, (event) => {
            const meta = event.metadata_ || event.metadata || {};
            const existingJob = useWorldVaultStore.getState().streamingJobs[event.id];
            const eventChatId = meta.chat_id || event.chat_id || existingJob?.chatId;
            
            if (event.id) {
                clearStreamingJob(event.id);
            }
            
            if (eventChatId) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', eventChatId] });
            }
            
            if (eventChatId === activeChatId) {
                const eventType = event.type || meta.type;
                if (eventType === 'chat_image') {
                    toast.success('Image generated!', { icon: '🖼️' });
                }
            }
        });

        const unsubError = subscribe(EventTypes.JOB_FAILED, (event) => {
            const meta = event.metadata_ || event.metadata || {};
            const existingJob = useWorldVaultStore.getState().streamingJobs[event.id];
            const eventChatId = meta.chat_id || event.chat_id || existingJob?.chatId;
            
            if (event.id) {
                clearStreamingJob(event.id);
            }
            
            if (eventChatId === activeChatId) {
                toast.error('AI response failed. Please try again.');
            }
        });

        return () => { unsubProgress(); unsubCompleted(); unsubError(); };
    }, [subscribe, activeChatId, updateStreamingJob, clearStreamingJob, queryClient]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, streamingJobs]);

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
        }
    }, [message]);

    const handleSendMessage = useCallback(async () => {
        if (!message.trim() && !pendingAttachment) return;

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

        const msgContent = message.trim();
        setMessage('');
        const attachmentFilename = pendingAttachment?.filename || null;
        setPendingAttachment(null);

        try {
            const res = await sendMessageMutation.mutateAsync({
                chatId: chatIdToUse,
                message: { 
                    role: 'user', 
                    content: msgContent, 
                    lorebook_ids: selectedLorebooks, 
                    image_path: attachmentFilename, 
                    agentic: agenticMode,
                    generator_checkpoint: settings.generator?.defaultCheckpoint || null
                }
            });
            if (res.job_id) {
                updateStreamingJob(res.job_id, { text: '', status: 'running', chatId: chatIdToUse });
            }
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', chatIdToUse] });
        } catch {
            toast.error('Failed to send message');
        }
    }, [message, pendingAttachment, activeChatId, selectedLorebooks, agenticMode, createChatMutation, sendMessageMutation, updateStreamingJob, queryClient, setActiveChatId, settings]);

    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    }, [handleSendMessage]);

    const canSend = (message.trim() || pendingAttachment) && !sendMessageMutation.isPending;

    const handleGenerateScene = async () => {
        if (!activeChatId) return;
        setIsGeneratingScene(true);
        toast.success('Generating scene...', { icon: '📸' });
        try {
            const res = await fetch(`/api/world_vault/chats/${activeChatId}/scene`, { method: 'POST' });
            if (!res.ok) throw new Error('Failed');
            const data = await res.json();
            if (data.job_id) {
                updateStreamingJob(data.job_id, { text: 'Generating scene image...', status: 'running', chatId: activeChatId });
            }
        } catch {
            toast.error('Failed to generate scene');
        } finally {
            setIsGeneratingScene(false);
        }
    };

    const triggerAutoTitle = async () => {
        if (!activeChatId) return;
        setIsGeneratingTitle(true);
        toast('Generating title...', { icon: '🤖' });
        try {
            const chatHistory = messages.slice(-5).map(m => `${m.role}: ${m.content}`).join('\n');
            const resJob = await api.post('/api/jobs', {
                task_type: 'llm',
                workflow: {
                    messages: [
                        { role: 'system', content: 'Generate a short, catchy title (max 5 words) for the following chat. Output ONLY the title, no quotes.' },
                        { role: 'user', content: chatHistory || 'A new conversation.' }
                    ]
                }
            });
            const poll = async (jobId) => {
                for (let i = 0; i < 30; i++) {
                    const s = await api.get(`/api/jobs/${jobId}`);
                    if (s.status === 'completed' && s.outputs?.length > 0) {
                        const newTitle = s.outputs[0].content.replace(/["']/g, '');
                        await renameChatMutation.mutateAsync({ chatId: activeChatId, name: newTitle });
                        toast.success('Title generated!');
                        setIsGeneratingTitle(false);
                        return;
                    }
                    if (s.status === 'failed') break;
                    await new Promise(r => setTimeout(r, 1000));
                }
                toast.error('Title generation failed');
                setIsGeneratingTitle(false);
            };
            if (resJob.id) poll(resJob.id);
            else setIsGeneratingTitle(false);
        } catch {
            toast.error('Failed to generate title');
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
            story_location: storyLocation 
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
                    for (const lb of newSelectedLorebooks) {
                        if (!selectedLorebooks.includes(lb)) toggleLorebook(lb);
                    }
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
                        for (const lb of newSelectedLorebooks) {
                            if (!selectedLorebooks.includes(lb)) toggleLorebook(lb);
                        }
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
            const res = await worldVaultApi.upload.chatAttachment(formData);
            setPendingAttachment({ filename: res.filename, name: file.name });
            toast.success('Image attached');
        } catch {
            toast.error('Failed to upload image');
        } finally {
            setIsUploading(false);
        }
    };

    const handleDeleteChat = async () => {
        if (!deleteTarget) return;
        try {
            await deleteChatMutation.mutateAsync(deleteTarget.id);
            if (activeChatId === deleteTarget.id) {
                const remaining = chats?.filter(c => c.id !== deleteTarget.id);
                setActiveChatId(remaining?.[0]?.id || null);
            }
            toast.success('Chat deleted');
        } catch {
            toast.error('Failed to delete chat');
        }
        setDeleteTarget(null);
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

    const handleChatUpdate = (updates) => {
        if (!activeChatId) return;
        updateChatMutation.mutate({ chatId: activeChatId, data: updates });
    };

    const linkedCharacter = characters.find(c => c.id === activeChat?.character_id);

    const chatsSidebarVisible = mobileTab === 'chats';
    const contextPanelVisible = mobileTab === 'context';
    const chatVisible = mobileTab === 'chat';

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex h-[calc(100vh-8rem)] lg:h-[calc(100vh-4rem)] -mx-2 sm:-mx-4 lg:-mx-8 -my-3 sm:-my-4 lg:-my-8 relative"
        >
            <div className={clsx(
                "flex flex-col shrink-0 border-r border-white/5 bg-gray-900/70 transition-all duration-300",
                "lg:w-64 lg:flex lg:static lg:translate-x-0",
                chatsSidebarVisible
                    ? "absolute inset-0 z-30 w-full flex"
                    : "hidden lg:flex"
            )}>
                <div className="h-16 flex items-center justify-between px-4 border-b border-white/5 shrink-0">
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
                                <button
                                    onClick={() => { setActiveChatId(chat.id); setMobileTab('chat'); }}
                                    className={clsx(
                                        "w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all flex items-center gap-2.5",
                                        activeChatId === chat.id
                                            ? "bg-blue-500/20 text-blue-300 border border-blue-500/20"
                                            : "text-gray-400 hover:bg-white/5 border border-transparent"
                                    )}
                                >
                                    {(() => {
                                        const c = characters.find(ch => ch.id === chat.character_id);
                                        return (
                                            <div className="w-6 h-6 rounded-full bg-gray-700/60 flex items-center justify-center shrink-0 overflow-hidden border border-white/5">
                                                {c?.has_avatar
                                                    ? <img src={getAvatarUrl(c.id)} alt="" className="w-full h-full object-cover" />
                                                    : <MessageSquare size={10} className="text-gray-500" />
                                                }
                                            </div>
                                        );
                                    })()}
                                    <span className="truncate flex-1">{chat.name || 'Unnamed Chat'}</span>
                                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                                        <button onClick={e => { e.stopPropagation(); startRename(chat); }} className="p-1 hover:text-white text-gray-500 rounded"><Edit3 size={11} /></button>
                                        <button onClick={e => { e.stopPropagation(); setDeleteTarget(chat); }} className="p-1 hover:text-red-400 text-gray-500 rounded"><Trash2 size={11} /></button>
                                    </div>
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            <div className={clsx(
                "flex-1 flex flex-col min-w-0 bg-[#0B0E14] relative",
                !chatVisible && "hidden lg:flex"
            )}>
                <div className="h-16 border-b border-white/5 flex items-center justify-between px-3 sm:px-4 shrink-0 bg-gray-900/40 backdrop-blur-md z-10 gap-2">
                    <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
                        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden">
                            {linkedCharacter?.has_avatar
                                ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                                : <MessageSquare className="text-blue-400" size={16} />
                            }
                        </div>
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
                        onClick={() => setMobileTab(mobileTab === 'context' ? 'chat' : 'context')}
                        className="p-2 text-gray-400 hover:text-gray-200 hover:bg-white/5 rounded-lg transition-colors hidden lg:flex"
                        title="Toggle Context Panel"
                    >
                        <Settings size={18} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-3 sm:p-4 lg:p-6 space-y-4 custom-scrollbar flex flex-col">
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
                            {messages.map((msg, idx) => (
                                <div
                                    key={msg.id || idx}
                                    className={clsx(
                                        "flex gap-2 sm:gap-3 max-w-[90%] sm:max-w-[85%]",
                                        msg.role === 'user' ? "self-end flex-row-reverse" : "self-start flex-row"
                                    )}
                                >
                                    {msg.role !== 'user' && msg.role !== 'system' && (
                                        <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden self-end">
                                            {linkedCharacter?.has_avatar
                                                ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                                                : <MessageSquare className="text-blue-400" size={12} />
                                            }
                                        </div>
                                    )}
                                    <div className="flex flex-col max-w-full">
                                        <div className={clsx(
                                            "text-[10px] mb-1",
                                            msg.role === 'user' ? "text-gray-500 text-right" : "text-gray-400"
                                        )}>
                                            {msg.role === 'user'
                                                ? (activeChat?.persona_name || 'You')
                                                : msg.role === 'system' ? '✦ System'
                                                : (linkedCharacter?.name || 'AI')}
                                        </div>
                                        {(msg.role === 'char' || msg.role === 'assistant') ? (
                                            <div className="flex flex-col gap-2 w-full">
                                                <TavernMessage content={msg.content} />
                                                {msg.image_path && (
                                                    <div className="mt-1">
                                                        <img
                                                            src={`/api/files/${msg.image_path}`}
                                                            alt="Attachment"
                                                            className="rounded-2xl max-w-full h-auto border border-white/10 shadow-lg"
                                                        />
                                                    </div>
                                                )}
                                            </div>
                                        ) : (
                                            <div className={clsx(
                                                "px-3 sm:px-4 py-3 rounded-2xl text-sm leading-relaxed break-words",
                                                msg.role === 'user'
                                                    ? "bg-blue-600/20 text-blue-100 border border-blue-500/20 rounded-tr-sm"
                                                    : "bg-yellow-500/10 text-yellow-200/80 border border-yellow-500/15 rounded-tl-sm text-xs italic"
                                            )}>
                                                <span className="whitespace-pre-wrap">{msg.content}</span>
                                                {msg.image_path && (
                                                    <div className="mt-3">
                                                        <img
                                                            src={`/api/files/${msg.image_path}`}
                                                            alt="Attachment"
                                                            className="rounded-xl max-w-full h-auto border border-white/10 shadow-lg"
                                                        />
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}

                            {Object.entries(streamingJobs).map(([jobId, jobData]) => (
                                jobData.status === 'running' && jobData.chatId === activeChatId && (
                                    <div key={jobId} className="flex flex-col max-w-[85%] self-start items-start gap-1">
                                        <div className="text-[10px] text-blue-400 ml-1 flex items-center gap-1.5">
                                            {linkedCharacter?.name || 'AI'} <Loader2 size={10} className="animate-spin" />
                                        </div>
                                        <div className="px-4 py-3 rounded-2xl rounded-tl-sm text-sm bg-gray-800/50 text-gray-200 border border-gray-700/40 leading-relaxed">
                                            {jobData.text ? (
                                                <span className="whitespace-pre-wrap">{jobData.text}<span className="inline-block w-1 h-4 bg-blue-400/70 animate-pulse ml-0.5 align-text-bottom rounded-sm" /></span>
                                            ) : (
                                                <span className="flex items-center gap-2 text-purple-400 text-sm">
                                                    <Wand2 size={14} className="animate-pulse" />
                                                    Thinking...
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                )
                            ))}

                            <div ref={messagesEndRef} />
                        </>
                    )}
                </div>

                <div className="px-3 sm:px-4 lg:px-6 py-3 sm:py-4 pb-16 lg:pb-4 border-t border-white/5 bg-gray-900/40 backdrop-blur-md shrink-0">
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
                            <input ref={fileInputRef} type="file" accept="image/*" onChange={handleAttachmentChange} className="hidden" />
                            <textarea
                                ref={textareaRef}
                                value={message}
                                onChange={e => setMessage(e.target.value)}
                                onKeyDown={handleKeyDown}
                                placeholder={activeChatId ? 'Type a message...' : 'Select a chat to start...'}
                                className="w-full bg-gray-900/80 border border-gray-700/50 rounded-2xl pl-10 sm:pl-12 pr-28 sm:pr-36 py-3.5 sm:py-4 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/30 transition-all resize-none shadow-inner text-sm"
                                rows={1}
                                style={{ minHeight: '52px', maxHeight: '200px' }}
                                disabled={sendMessageMutation.isPending || !activeChatId}
                            />
                            <button
                                onClick={() => fileInputRef.current?.click()}
                                disabled={isUploading}
                                className="absolute left-2 sm:left-3 bottom-2.5 sm:bottom-3 p-1.5 sm:p-2 text-gray-400 hover:text-blue-400 transition-colors rounded-xl hover:bg-blue-500/10 disabled:opacity-50"
                                title="Attach image"
                            >
                                {isUploading ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
                            </button>
                            {/* Generate scene */}
                            <button
                                onClick={handleGenerateScene}
                                disabled={isGeneratingScene || !activeChatId}
                                className="absolute right-20 sm:right-24 bottom-2.5 sm:bottom-3 p-1.5 sm:p-2 text-gray-400 hover:text-green-400 transition-colors rounded-xl hover:bg-green-500/10 disabled:opacity-50"
                                title="Generate Scene"
                            >
                                {isGeneratingScene ? <Loader2 size={18} className="animate-spin" /> : <ImageIcon size={18} />}
                            </button>
                            {/* Agentic mode */}
                            <button
                                onClick={() => setAgenticMode(!agenticMode)}
                                className={clsx(
                                    "absolute right-10 sm:right-12 bottom-2.5 sm:bottom-3 p-1.5 sm:p-2 transition-colors rounded-xl",
                                    agenticMode
                                        ? "text-purple-400 hover:text-purple-300 hover:bg-purple-500/10"
                                        : "text-gray-500 hover:text-gray-400 hover:bg-white/5"
                                )}
                                title={agenticMode ? "Agentic ON" : "Agentic OFF"}
                            >
                                <Wand2 size={18} />
                            </button>
                            {/* Send */}
                            <button
                                onClick={handleSendMessage}
                                disabled={!canSend}
                                className={clsx(
                                    "absolute right-2 sm:right-2 bottom-2 sm:bottom-2 p-2 transition-all rounded-xl",
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
                        <div className="mt-1.5 hidden sm:flex items-center justify-between px-1 text-[10px] text-gray-600">
                            <span><kbd className="font-mono bg-gray-800 px-1 py-0.5 rounded border border-gray-700 text-gray-500">Enter</kbd> to send · <kbd className="font-mono bg-gray-800 px-1 py-0.5 rounded border border-gray-700 text-gray-500">Shift+Enter</kbd> for newline</span>
                            <span className={clsx("transition-colors", agenticMode ? "text-purple-400" : "text-gray-600")}>
                                {agenticMode ? '⚡ Agentic' : 'Standard'}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* === CONTEXT PANEL (Right) === */}
            <div className={clsx(
                "flex-col border-l border-white/5 bg-gray-900/60 shrink-0 overflow-hidden",
                // Desktop: shown when context tab active (reuse mobileTab for desktop toggle too)
                "lg:w-80",
                // Mobile: full-screen when context tab; hidden otherwise
                contextPanelVisible
                    ? "absolute inset-0 z-30 flex w-full"
                    : "hidden lg:flex",
                // On desktop, if context not selected, collapse
                !contextPanelVisible && "lg:hidden"
            )}>
                <div className="h-16 border-b border-white/5 flex items-center justify-between px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
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
                        <p className="text-[10px] text-gray-600 mt-2 px-1">
                            Sets <code className="text-gray-500">{'{{user}}'}</code> in character prompts.
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

                    {/* Character */}
                    <div className="glass-panel p-4 rounded-xl border border-white/5">
                        <div className="flex items-center justify-between mb-3">
                            <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                                <User size={12} /> Character
                            </h4>
                            <a href="/characters" className="text-[9px] text-blue-400 hover:text-blue-300 font-medium px-1.5 py-0.5 rounded bg-blue-500/10 hover:bg-blue-500/20 transition-colors">
                                Manage
                            </a>
                        </div>
                        {linkedCharacter ? (
                            <div 
                                className="flex items-center gap-3 p-2 bg-gray-800/30 hover:bg-gray-800/60 rounded-lg cursor-pointer transition-colors group"
                                onClick={() => setShowCharacterDetails(true)}
                                title="View character details"
                            >
                                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center shrink-0 overflow-hidden border border-white/10 group-hover:border-blue-500/30 transition-colors">
                                    {linkedCharacter.has_avatar
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
                                            onClick={() => toggleLorebook(lb.id)}
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

            {/* === MOBILE BOTTOM TAB BAR === */}
            <div className="fixed bottom-0 left-0 right-0 z-50 lg:hidden bg-gray-950/95 backdrop-blur-xl border-t border-white/10 flex items-stretch h-[60px] safe-area-inset-bottom">
                {/* Chats Tab */}
                <button
                    onClick={() => setMobileTab('chats')}
                    className={clsx(
                        "flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] font-semibold transition-all",
                        mobileTab === 'chats'
                            ? "text-blue-400"
                            : "text-gray-500 hover:text-gray-300"
                    )}
                >
                    <div className={clsx("p-1.5 rounded-xl transition-all", mobileTab === 'chats' ? "bg-blue-500/15" : "")}>
                        <MessageSquare size={20} />
                    </div>
                    Chats
                </button>

                {/* Chat Tab (centre — primary) */}
                <button
                    onClick={() => setMobileTab('chat')}
                    className={clsx(
                        "flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] font-semibold transition-all",
                        mobileTab === 'chat'
                            ? "text-white"
                            : "text-gray-500 hover:text-gray-300"
                    )}
                >
                    <div className={clsx(
                        "p-1.5 rounded-xl transition-all",
                        mobileTab === 'chat' ? "bg-blue-600 shadow-[0_0_12px_rgba(37,99,235,0.4)]" : ""
                    )}>
                        {linkedCharacter?.has_avatar
                            ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-5 h-5 rounded-full object-cover" />
                            : <User size={20} className={mobileTab === 'chat' ? 'text-white' : ''} />
                        }
                    </div>
                    Chat
                </button>

                {/* Context Tab */}
                <button
                    onClick={() => setMobileTab('context')}
                    className={clsx(
                        "flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] font-semibold transition-all",
                        mobileTab === 'context'
                            ? "text-blue-400"
                            : "text-gray-500 hover:text-gray-300"
                    )}
                >
                    <div className={clsx("p-1.5 rounded-xl transition-all", mobileTab === 'context' ? "bg-blue-500/15" : "")}>
                        <BookOpen size={20} />
                    </div>
                    Context
                </button>
            </div>

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

            <ConfirmationModal
                isOpen={!!deleteTarget}
                onClose={() => setDeleteTarget(null)}
                onConfirm={handleDeleteChat}
                title="Delete Chat"
                message={`Are you sure you want to delete "${deleteTarget?.name || 'this chat'}"? All messages will be permanently lost.`}
                confirmText="Delete"
                isDangerous
            />
        </motion.div>
    );
}
