import clsx from 'clsx';
import {
    User, Clock, MapPin, Activity, Sparkles, ImageIcon, Loader2, BookOpen, Check, MessageSquare,
} from 'lucide-react';
import { getAvatarUrl } from '../../hooks/useWorldVault';
import ContextField from './ContextField';
import ContextSlider from './ContextSlider';
import SystemPromptPanel from './SystemPromptPanel';
import ExpressionSelector from './ExpressionSelector';
import { useChatWorkspace } from '../../contexts/ChatWorkspaceContext';

function ChatContextPanel() {
    const {
        activeChat,
        linkedCharacter,
        chatJobs,
        chatCollection,
        activeStreamEntries,
        sceneJobId,
        characters,
        lorebooks,
        selectedLorebooks,
        patchCharacterMutation,
        systemPromptData,
        availableModels,
        defaultLlmConfig,
        setShowCharacterDetails,
        setShowScenesModal,
        handleChatUpdate,
    } = useChatWorkspace();

    const onChatUpdate = (data) => handleChatUpdate(data);
    const onCharacterPatch = (data) => patchCharacterMutation.mutate(data);
    const onShowCharacterDetails = () => setShowCharacterDetails(true);
    const onShowScenes = () => setShowScenesModal(true);

    return (
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
                    onSave={val => onChatUpdate({ persona_name: val })}
                />
                {/* Persona description */}
                <div className="mt-3">
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">
                        Description
                    </label>
                    <textarea
                        key={`persona-desc-${activeChat?.id}`}
                        defaultValue={activeChat?.persona_description || ''}
                        onBlur={(e) => {
                            const val = e.target.value.trim() || null;
                            if (val !== (activeChat?.persona_description || null)) {
                                onChatUpdate({ persona_description: val });
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
                            onClick={() => onChatUpdate({ persona_description: linkedCharacter.suggested_persona })}
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
                onSave={val => onChatUpdate({ story_time: val })}
            />
            
            <ContextField
                label="Location"
                icon={MapPin}
                value={activeChat?.story_location}
                placeholder="Not set"
                onSave={val => onChatUpdate({ story_location: val })}
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
                        onChange={(e) => onChatUpdate({ character_id: e.target.value || null })}
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
                        onClick={onShowCharacterDetails}
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
                        No primary character assigned
                    </p>
                )}

                {/* Additional Characters */}
                <div className="mt-4 pt-4 border-t border-white/5">
                    <div className="flex items-center justify-between mb-3">
                        <h5 className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">
                            Group Members
                        </h5>
                        <select
                            value=""
                            onChange={(e) => {
                                const val = e.target.value;
                                if (val) {
                                    const current = activeChat?.additional_character_ids || [];
                                    if (!current.includes(val)) {
                                        onChatUpdate({ additional_character_ids: [...current, val] });
                                    }
                                }
                            }}
                            className="bg-gray-800 border border-gray-700 text-xs rounded px-2 py-1 text-gray-300 focus:outline-none max-w-[120px] truncate"
                        >
                            <option value="">+ Add Member</option>
                            {characters
                                .filter(c => c.id !== activeChat?.character_id && !(activeChat?.additional_character_ids || []).includes(c.id))
                                .map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                        </select>
                    </div>
                    
                    <div className="space-y-1.5">
                        {(activeChat?.additional_character_ids || []).map(id => {
                            const c = characters.find(char => char.id === id);
                            if (!c) return null;
                            return (
                                <div key={c.id} className="flex items-center justify-between bg-gray-800/40 px-2 py-1.5 rounded-lg group">
                                    <div className="flex items-center gap-2 overflow-hidden">
                                        <div className="w-5 h-5 rounded-full bg-gray-700 shrink-0 overflow-hidden">
                                            {c.avatar_path ? (
                                                <img src={getAvatarUrl(c.id)} alt="" className="w-full h-full object-cover" />
                                            ) : (
                                                <User size={10} className="mx-auto mt-1 text-gray-400" />
                                            )}
                                        </div>
                                        <span className="text-xs text-gray-300 truncate">{c.name}</span>
                                    </div>
                                    <button
                                        type="button"
                                        className="opacity-0 group-hover:opacity-100 p-1 text-red-400 hover:text-red-300 transition-opacity"
                                        title="Remove from group"
                                        onClick={() => {
                                            const current = activeChat?.additional_character_ids || [];
                                            onChatUpdate({ additional_character_ids: current.filter(cid => cid !== c.id) });
                                        }}
                                    >
                                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
                                    </button>
                                </div>
                            );
                        })}
                        {!(activeChat?.additional_character_ids || []).length && (
                            <p className="text-[10px] text-gray-600 text-center py-2">
                                Add more characters for a group chat
                            </p>
                        )}
                    </div>
                </div>
            </div>

            {/* AI Model + Image generation */}
            <div className="glass-panel p-4 rounded-xl border border-white/5 space-y-3">
                <div>
                    <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 mb-2">
                        <Sparkles size={12} /> AI Model
                    </h4>
                    <select
                        value={activeChat?.llm_model || ''}
                        onChange={(e) => onChatUpdate({ llm_model: e.target.value || null })}
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
                        onChange={(val) => onChatUpdate({ max_context_tokens: val })}
                    />
                    <div className="flex justify-between text-[9px] text-gray-600 mt-0.5">
                        <span>2k</span><span>32k</span><span>64k</span><span>128k</span>
                    </div>
                    {activeChat?.max_context_tokens && (
                        <button
                            onClick={() => onChatUpdate({ max_context_tokens: null })}
                            className="mt-1 text-[9px] text-gray-500 hover:text-red-400 transition-colors"
                        >
                            Reset to global default
                        </button>
                    )}
                </div>
                <div>
                    <div className="flex items-center justify-between mb-1.5">
                        <p className="text-xs text-gray-300 font-medium">Agentic Loop Depth</p>
                        <span className="text-[10px] text-gray-500 font-mono">
                            {activeChat?.max_agentic_depth
                                ? `${activeChat.max_agentic_depth} steps`
                                : 'Global default (5)'}
                        </span>
                    </div>
                    <input
                        type="range"
                        min="1"
                        max="10"
                        step="1"
                        value={activeChat?.max_agentic_depth || 5}
                        onChange={(e) => onChatUpdate({ max_agentic_depth: parseInt(e.target.value) })}
                        className="w-full accent-purple-500"
                        title="Max agentic tool-call loops per reply. Higher = more autonomous but slower."
                    />
                    <div className="flex justify-between text-[9px] text-gray-600 mt-0.5">
                        <span>1</span><span>5</span><span>10</span>
                    </div>
                    {activeChat?.max_agentic_depth && (
                        <button
                            onClick={() => onChatUpdate({ max_agentic_depth: null })}
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
                        onClick={() => onChatUpdate({ allow_image_generation: activeChat?.allow_image_generation === false })}
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
                        onClick={() => onChatUpdate({ allow_narration: activeChat?.allow_narration === false })}
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
                onChatUpdate={onChatUpdate}
                onCharacterPatch={onCharacterPatch}
            />

            {/* Scenes */}
            <div className="glass-panel p-4 rounded-xl border border-white/5">
                <div className="flex items-center justify-between mb-3">
                    <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                        <ImageIcon size={12} /> Scenes
                    </h4>
                    {(() => {
                        const sceneStream = activeStreamEntries.find(
                            (item) => item.jobId && item.jobData?.chatId === activeChat?.id && (item.jobData?.type === 'image' || item.jobData?.taskType === 'image')
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
                        onClick={onShowScenes}
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
                                        onChatUpdate({ active_lorebook_ids: newLorebooks });
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

            {/* Expressions (if character has any) */}
            {linkedCharacter?.expressions && Object.keys(linkedCharacter.expressions).some(k => !k.startsWith('_')) && (
                <ExpressionSelector character={linkedCharacter} characterId={linkedCharacter.id} inline />
            )}
        </div>
    );
}

export default ChatContextPanel;
