import clsx from 'clsx';
import { memo, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
    User, Clock, Activity, Sparkles, ImageIcon, Loader2, BookOpen, Check, MessageSquare, Brain, ChevronDown, NotebookPen,
    MapPin, Plus, Edit2, Calendar, Layers,
} from 'lucide-react';
import { getAvatarUrl } from '../../hooks/useWorldVault';
import { useLocations } from '../../hooks/useLocations';
import { isJobComplete, isJobFailed, isJobRunning } from '../../utils/jobStatus';
import ContextField from './ContextField';
import ContextSlider from './ContextSlider';
import SamplingControls from '../common/SamplingControls';
import { QueryErrorState } from '../common/QueryState';
import SystemPromptPanel from './SystemPromptPanel';
import ExpressionSelector from './ExpressionSelector';
import MemoriesPanel from './MemoriesPanel';
import EntityContextInspector from '../workspace/EntityContextInspector';
import WorldLinkRow from '../workspace/WorldLinkRow';
import { useChatWorkspace } from '../../contexts/ChatWorkspaceContext';
import { useActiveChatStreams } from '../../hooks/useStreamingJobs';

const LOREBOOK_CONTEXT_TAIL = 12;

/**
 * One row of the chat's job list.
 *
 * Memoised, because this panel re-renders on every streamed token of the
 * conversation behind it and the list sits above eleven other panels — so an
 * un-memoised row meant re-rendering all of them per token. The previous
 * checks used snake_case spellings ('pre_generation', 'post_processing') that
 * the API never emits, so every real in-flight job fell through to the grey
 * branch and printed its raw enum value as the label; the translations live
 * here now so the memo boundary and the fix are the same object.
 */
const ChatJobRow = memo(function ChatJobRow({ job }) {
    const isRunning = isJobRunning(job.status);
    const isImage = job.task_type === 'image' || job.type === 'image' || job.type === 'agentic_image';
    const isFailed = isJobFailed(job.status);
    const isComplete = isJobComplete(job.status);
    return (
        <div className={clsx(
            "flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs border",
            isFailed ? "bg-red-500/5 border-red-500/15 text-red-300" :
                isComplete ? (isImage ? "bg-emerald-500/5 border-emerald-500/15 text-emerald-300" : "bg-blue-500/5 border-blue-500/15 text-blue-300") :
                    isRunning ? "bg-amber-500/5 border-amber-500/15 text-amber-300" : "bg-gray-800/30 border-gray-700/30 text-gray-400"
        )}>
            <span className={clsx("w-1.5 h-1.5 rounded-full shrink-0", isFailed ? "bg-red-400" : isComplete ? (isImage ? "bg-emerald-400" : "bg-blue-400") : isRunning ? "bg-amber-400 animate-pulse" : "bg-gray-600")} />
            <span className="truncate flex-1 font-medium">{isImage ? (job.type === 'agentic_image' ? 'Image generation' : 'Image job') : 'LLM reply'}</span>
            <span className="text-xs text-gray-500 shrink-0">{isFailed ? 'Failed' : isComplete ? 'Done' : isRunning ? 'Active' : job.status}</span>
            {/* The sampler percentage, not the node counter.
                `overall_progress` is frozen while a checkpoint sampler runs —
                the phase that takes the time — so the row sat at one number for
                a minute while the job visibly progressed. */}
            {isRunning && (job.progress || job.overall_progress) != null && (
                <span className="text-xs text-amber-300/80 shrink-0">
                    {Math.round(job.progress > 0 ? job.progress : job.overall_progress)}%
                </span>
            )}
        </div>
    );
});

function ChatContextPanel() {
    const {
        activeChat,
        linkedCharacter,
        chatJobs,
        chatCollection,
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
        voices,
        worlds = [],
        personas = [],
        queryErrors = {},
        messages = [],
        onEditCharacter,
        onEditLorebook,
        onEditLocation,
    } = useChatWorkspace();
    const activeStreamEntries = useActiveChatStreams(activeChat?.id);
    const { data: locations = [] } = useLocations();

    const navigate = useNavigate();

    const onChatUpdate = (data) => handleChatUpdate(data);
    const onCharacterPatch = (data) => {
        if (linkedCharacter?.id) {
            patchCharacterMutation.mutate({ ...data, id: linkedCharacter.id });
        }
    };
    const onShowCharacterDetails = () => setShowCharacterDetails(true);
    const onShowScenes = () => setShowScenesModal(true);

    const lorebookContextText = useMemo(
        () => messages
            .slice(-LOREBOOK_CONTEXT_TAIL)
            .map(m => m?.content || '')
            .join('\n'),
        [messages]
    );

    return (
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
            <EntityContextInspector
                title="Entity Inspector"
                subtitle="What this chat currently feeds the model"
                characters={characters}
                characterIds={[activeChat?.character_id, ...(activeChat?.additional_character_ids || [])].filter(Boolean)}
                primaryCharacterId={activeChat?.character_id || null}
                characterLorebookLinks={characters.flatMap(c => (c.lorebook_ids || []).map(lorebookId => ({ lorebookId, characterName: c.name })))}
                lorebooks={lorebooks}
                lorebookIds={selectedLorebooks}
                locations={locations}
                locationIds={activeChat?.location_id ? [activeChat.location_id] : []}
                freeformLocation={activeChat?.story_location || null}
                contextText={lorebookContextText}
                onEditCharacter={onEditCharacter}
                onEditLorebook={onEditLorebook}
                onEditLocation={onEditLocation}
                extraLinks={[
                    { to: '/activity', label: 'Activity', icon: Calendar },
                    { to: '/world-graph', label: 'Relationships', icon: Layers },
                ]}
            />

            <WorldLinkRow
                worldId={activeChat?.world_id}
                worlds={worlds}
                onChange={(next) => onChatUpdate({ world_id: next })}
                queryErrors={queryErrors}
            />

            {/* Persona Name */}
            <div className="glass-panel p-4 rounded-xl border border-white/5">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                    <User size={12} /> Your Persona
                </h4>
                <ContextField
                    inline
                    label="Your Persona"
                    fieldLabel="Persona name"
                    icon={User}
                    value={activeChat?.persona_name}
                    placeholder="Default (User)"
                    onSave={val => onChatUpdate({ persona_name: val })}
                />
                {/* Persona description */}
                <div className="mt-3">
                    <label htmlFor="persona-description" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
                        Description
                    </label>
                    <textarea
                        id="persona-description"
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
                                : 'Who you are in this roleplay…'
                        }
                        rows={2}
                        className="w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg px-2.5 py-2 text-gray-300 placeholder-gray-600 focus:outline-none focus:border-blue-500/40 resize-none"
                    />
                    {linkedCharacter?.suggested_persona && !activeChat?.persona_description && (
                        <button
                            type="button"
                            onClick={() => onChatUpdate({ persona_description: linkedCharacter.suggested_persona })}
                            className="mt-1 inline-flex items-center min-h-[24px] py-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                        >
                            Use {linkedCharacter.name}'s suggestion
                        </button>
                    )}
                </div>
                <p className="text-xs text-gray-500 mt-2 px-1">
                    Sets <code className="text-gray-400">{'{{user}}'}</code> and injects a persona block into the system prompt.
                </p>
                {(queryErrors.personas || personas.length > 0) && (
                    <div className="mt-3">
                        <label htmlFor="library-persona" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
                            Library Persona
                        </label>
                        {queryErrors.personas ? (
                            // A failed personas fetch is not an absent library.
                            // The selector used to vanish entirely on `length > 0`,
                            // so the outage looked exactly like "you have no
                            // personas" and the setting was silently unavailable.
                            <QueryErrorState
                                noun={queryErrors.personas.noun}
                                error={queryErrors.personas.error}
                                onRetry={queryErrors.personas.refetch}
                            />
) : (
                            <>
                        <select
                            id="library-persona"
                            data-testid="chat-persona-select"
                            value={activeChat?.persona_id || ''}
                            onChange={(e) => onChatUpdate({ persona_id: e.target.value || null })}
                            className="w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg px-2.5 py-2 text-gray-300 focus:outline-none focus:border-blue-500/40 appearance-none"
                        >
                            <option value="">None (custom fields only)</option>
                            {personas.map(p => (
                                <option key={p.id} value={p.id}>{p.name}</option>
                            ))}
                        </select>
                        <p className="text-xs text-gray-500 mt-1 px-1">
                            Library values fill any persona field left blank above. Manage in{' '}
                            <button
                                type="button"
                                onClick={() => navigate('/personas')}
                                className="inline-flex items-center min-h-[24px] py-1 align-baseline text-blue-400 hover:text-blue-300 underline"
                            >
                                Personas
                            </button>
                            .
                        </p>
                            </>
                        )}
                    </div>
                )}
            </div>

            <SceneOverridesSection
                key={`so-${activeChat?.id}`}
                chat={activeChat}
                onSave={onChatUpdate}
            />

            {/* Chat Jobs (LLM + image progress for this chat) */}
            <div className="glass-panel p-4 rounded-xl border border-white/5">
                <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                        <Activity size={12} /> Jobs
                    </h4>
                    <span className="text-xs text-gray-600 shrink-0">{chatJobs?.length || 0} total</span>
                </div>
                {queryErrors.chatJobs ? (
                    // Same inversion as the persona and voices selectors above,
                    // and the same one this very panel already fixed for
                    // `lorebooks`: `chatJobs` sits at its `= []` default when
                    // GET /api/v2/chats/{id}/jobs fails, so "No jobs tracked for
                    // this chat yet" was an outage reading as an idle chat.
                    <QueryErrorState
                        noun={queryErrors.chatJobs.noun}
                        error={queryErrors.chatJobs.error}
                        onRetry={queryErrors.chatJobs.refetch}
                    />
                ) : !chatJobs?.length ? (
                    <p className="text-xs text-gray-600">No jobs tracked for this chat yet.</p>
                ) : (
                    <div className="space-y-1.5 max-h-48 overflow-y-auto custom-scrollbar">
                        {chatJobs.slice(0, 10).map((job) => (
                            <ChatJobRow key={job.id} job={job} />
                        ))}
                    </div>
                )}
            </div>

            {/* Character */}
            <div className="glass-panel p-4 rounded-xl border border-white/5">
                <div className="flex items-center justify-between mb-3">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 whitespace-nowrap shrink-0">
                        <User size={12} /> Character
                    </h4>
                    {/* Constrained width + native truncation so long names don't overflow */}
                    <select
                        value={activeChat?.character_id || ''}
                        onChange={(e) => onChatUpdate({ character_id: e.target.value || null })}
                        className="bg-gray-800 border border-gray-700 text-xs rounded px-2 py-1 text-gray-300 focus:outline-none max-w-[140px] min-w-0 truncate"
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
                            <p className="text-xs text-blue-400 mt-0.5 opacity-80 group-hover:opacity-100">View details</p>
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
                        <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-widest whitespace-nowrap shrink-0">
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
                            className="bg-gray-800 border border-gray-700 text-xs rounded px-2 py-1 text-gray-300 focus:outline-none max-w-[120px] min-w-0 truncate"
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
                                        className="opacity-0 group-hover:opacity-100 p-1 min-w-6 min-h-6 inline-flex items-center justify-center text-red-400 hover:text-red-300 transition-opacity"
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
                            <p className="text-xs text-gray-600 text-center py-2">
                                Add more characters for a group chat
                            </p>
                        )}
                    </div>
                </div>
            </div>

            {/* AI Model + Image generation */}
            <div className="glass-panel p-4 rounded-xl border border-white/5 space-y-3">
                <div>
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 mb-2">
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
                        <p className="text-xs text-gray-300 font-medium whitespace-nowrap shrink-0">Context Window</p>
                        <span className="text-xs text-gray-500 font-mono min-w-0 truncate text-right">
                            {activeChat?.max_context_tokens
                                ? `${(activeChat.max_context_tokens / 1024).toFixed(0)}k tokens`
                                : 'Global default'}
                        </span>
                    </div>
                    <ContextSlider
                        activeChat={activeChat}
                        onChange={(val) => onChatUpdate({ max_context_tokens: val })}
                    />
                    <div className="flex justify-between text-xs text-gray-600 mt-0.5">
                        <span>2k</span><span>32k</span><span>64k</span><span>128k</span>
                    </div>
                    {activeChat?.max_context_tokens && (
                        <button
                            onClick={() => onChatUpdate({ max_context_tokens: null })}
                            className="mt-1 inline-flex items-center min-h-[24px] text-xs text-gray-500 hover:text-red-400 transition-colors"
                        >
                            Reset to global default
                        </button>
                    )}
                </div>
                <SamplingControls values={activeChat || {}} onChange={onChatUpdate} />
                <div>
                    {/* The cost cap. Separate from depth, which bounds how many
                        times the model may think rather than how much it may
                        spend: generate_image was callable once per hop, so the
                        depth cap alone let one reply chain five paid image jobs.
                        min is 0, not 1 — zero is how you keep the agentic loop
                        but turn its images off. */}
                    <div className="flex items-center justify-between mb-1.5">
                        <p className="text-xs text-gray-300 font-medium whitespace-nowrap shrink-0">Agentic Image Budget</p>
                        <span className="text-xs text-gray-500 font-mono min-w-0 truncate text-right">
                            {activeChat?.max_agentic_images != null
                                ? (activeChat.max_agentic_images > 0
                                    ? `${activeChat.max_agentic_images} per reply`
                                    : 'Off')
                                : 'Global default (2)'}
                        </span>
                    </div>
                    <input
                        type="range"
                        min="0"
                        max="8"
                        step="1"
                        value={activeChat?.max_agentic_images ?? 2}
                        onChange={(e) => onChatUpdate({ max_agentic_images: parseInt(e.target.value) })}
                        className="w-full accent-purple-500 min-h-[24px]"
                        title="How many images the AI may spend on one reply. 0 disables autonomous illustration."
                    />
                    <div className="flex justify-between text-xs text-gray-600 mt-0.5">
                        <span>Off</span><span>2</span><span>8</span>
                    </div>
                    {activeChat?.max_agentic_images != null && (
                        <button
                            onClick={() => onChatUpdate({ max_agentic_images: null })}
                            className="mt-1 inline-flex items-center min-h-[24px] text-xs text-gray-500 hover:text-red-400 transition-colors"
                        >
                            Reset to global default
                        </button>
                    )}
                </div>
                <div>
                    {/* Narration, its own budget. It was the worst offender of the
                        uncapped kind: a narration is always a whole extra LLM
                        completion, it is the tool the model is most likely to
                        reach for, and it had no cap at all — so the single most
                        expensive discretionary decision in the agentic loop was
                        also the only unbounded one. A separate column, because
                        raising the image cap must not lower this one. */}
                    <div className="flex items-center justify-between mb-1.5">
                        <p className="text-xs text-gray-300 font-medium whitespace-nowrap shrink-0">Agentic Narrations</p>
                        <span className="text-xs text-gray-500 font-mono min-w-0 truncate text-right">
                            {activeChat?.max_agentic_narrations != null
                                ? (activeChat.max_agentic_narrations > 0
                                    ? `${activeChat.max_agentic_narrations} per reply`
                                    : 'Off')
                                : 'Global default (1)'}
                        </span>
                    </div>
                    <input
                        type="range"
                        min="0"
                        max="4"
                        step="1"
                        value={activeChat?.max_agentic_narrations ?? 1}
                        onChange={(e) => onChatUpdate({ max_agentic_narrations: parseInt(e.target.value) })}
                        className="w-full accent-purple-500 min-h-[24px]"
                        title="How many narrator paragraphs the AI may write on its own per reply. 0 means it may write scene prose inside the reply but will not run separate narration jobs."
                    />
                    <div className="flex justify-between text-xs text-gray-600 mt-0.5">
                        <span>Off</span><span>1</span><span>4</span>
                    </div>
                    {activeChat?.max_agentic_narrations != null && (
                        <button
                            onClick={() => onChatUpdate({ max_agentic_narrations: null })}
                            className="mt-1 inline-flex items-center min-h-[24px] text-xs text-gray-500 hover:text-red-400 transition-colors"
                        >
                            Reset to global default
                        </button>
                    )}
                </div>
                <div>
                    <div className="flex items-center justify-between mb-1.5">
                        <p className="text-xs text-gray-300 font-medium whitespace-nowrap shrink-0">Agentic Loop Depth</p>
                        <span className="text-xs text-gray-500 font-mono min-w-0 truncate text-right">
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
                        className="w-full accent-purple-500 min-h-[24px]"
                        title="Max agentic tool-call loops per reply. Higher = more autonomous but slower."
                    />
                    <div className="flex justify-between text-xs text-gray-600 mt-0.5">
                        <span>1</span><span>5</span><span>10</span>
                    </div>
                    {activeChat?.max_agentic_depth && (
                        <button
                            onClick={() => onChatUpdate({ max_agentic_depth: null })}
                            className="mt-1 inline-flex items-center min-h-[24px] text-xs text-gray-500 hover:text-red-400 transition-colors"
                        >
                            Reset to global default
                        </button>
                    )}
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <p className="text-xs text-gray-300 font-medium">Allow image generation</p>
                        <p className="text-xs text-gray-600 mt-1">
                            Lets the LLM call the <code className="text-gray-500">generate_image</code> tool in agentic mode.
                        </p>
                    </div>
                    <button
                        role="switch"
                        aria-label="Allow image generation"
                        aria-checked={activeChat?.allow_image_generation !== false}
                        onClick={() => onChatUpdate({ allow_image_generation: activeChat?.allow_image_generation === false })}
                        className={clsx(
                            "relative w-10 h-6 rounded-full transition-colors shrink-0",
                            activeChat?.allow_image_generation !== false ? "bg-purple-500" : "bg-gray-700"
                        )}
                    >
                        <span className={clsx(
                            "absolute top-1 w-4 h-4 rounded-full bg-white transition-all",
                            activeChat?.allow_image_generation !== false ? "left-5.5" : "left-0.5"
                        )} />
                    </button>
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <p className="text-xs text-gray-300 font-medium">Allow narration</p>
                        <p className="text-xs text-gray-600 mt-1">
                            Lets the LLM call the <code className="text-gray-500">narrate_scene</code> tool when the story calls for it.
                        </p>
                    </div>
                    <button
                        role="switch"
                        aria-label="Allow narration"
                        aria-checked={activeChat?.allow_narration !== false}
                        onClick={() => onChatUpdate({ allow_narration: activeChat?.allow_narration === false })}
                        className={clsx(
                            "relative w-10 h-6 rounded-full transition-colors shrink-0",
                            activeChat?.allow_narration !== false ? "bg-purple-500" : "bg-gray-700"
                        )}
                    >
                        <span className={clsx(
                            "absolute top-1 w-4 h-4 rounded-full bg-white transition-all",
                            activeChat?.allow_narration !== false ? "left-5.5" : "left-0.5"
                        )} />
                    </button>
                </div>
                {(queryErrors.voices || voices.length > 0) && (
                    <div>
                        <p className="text-xs text-gray-300 font-medium mb-1">Default TTS voice</p>
                        {queryErrors.voices ? (
                            // Same inversion as the persona selector above: the
                            // voices query failing used to remove the control,
                            // not report the failure, so narration became
                            // silently unconfigurable.
                            <QueryErrorState
                                noun={queryErrors.voices.noun}
                                error={queryErrors.voices.error}
                                onRetry={queryErrors.voices.refetch}
                            />
                        ) : (
                        <>
                        <select
                            className="w-full bg-gray-900 border border-gray-700 rounded-lg text-xs p-1.5 text-gray-300 focus:border-blue-500 outline-none"
                            value={activeChat?.tts_voice_id || ''}
                            onChange={(e) => onChatUpdate({ tts_voice_id: e.target.value || null })}
                        >
                            <option value="">Character default</option>
                            {voices.map(v => (
                                <option key={v.id} value={v.id}>{v.name}</option>
                            ))}
                        </select>
                        <p className="text-xs text-gray-600 mt-1">Applied to every message in this chat.</p>
                        </>
                        )}
                    </div>
                )}
                <div className="flex items-center justify-between">
                    <div>
                        <p className="text-xs text-gray-300 font-medium">Idle simulation</p>
                        <p className="text-xs text-gray-600 mt-1">
                            Character keeps the scene alive with proactive in-character messages while you're away.
                        </p>
                    </div>
                    <button
                        role="switch"
                        aria-label="Idle simulation"
                        aria-checked={activeChat?.idle_sim_enabled === true}
                        onClick={() => onChatUpdate({ idle_sim_enabled: !activeChat?.idle_sim_enabled })}
                        className={clsx(
                            "relative w-10 h-6 rounded-full transition-colors shrink-0",
                            activeChat?.idle_sim_enabled === true ? "bg-purple-500" : "bg-gray-700"
                        )}
                    >
                        <span className={clsx(
                            "absolute top-1 w-4 h-4 rounded-full bg-white transition-all",
                            activeChat?.idle_sim_enabled === true ? "left-5.5" : "left-0.5"
                        )} />
                    </button>
                </div>
            </div>

            {/* System prompt */}
            <SystemPromptPanel
                activeChat={activeChat}
                linkedCharacter={linkedCharacter}
                systemPromptData={systemPromptData}
                systemPromptError={queryErrors.systemPromptData?.error}
                onRetrySystemPrompt={queryErrors.systemPromptData?.refetch}
                onChatUpdate={onChatUpdate}
                onCharacterPatch={onCharacterPatch}
            />

            {/* Scenes */}
            <div className="glass-panel p-4 rounded-xl border border-white/5">
                <div className="flex items-center justify-between mb-3">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                        <ImageIcon size={12} /> Scenes
                    </h4>
                    {(() => {
                        const sceneStream = activeStreamEntries.find(
                            (item) => item.jobId && item.jobData?.chatId === activeChat?.id && (item.jobData?.type === 'image' || item.jobData?.taskType === 'image')
                        );
                        const pctNum = Number.isFinite(sceneStream?.jobData?.progress) ? Math.min(100, Math.max(0, Math.round(sceneStream.jobData.progress))) : null;
                        return (sceneStream && pctNum != null) ? (
                            <span className="text-xs text-green-400 flex items-center gap-1">
                                <Loader2 size={10} className="animate-spin" />
                                {pctNum}%
                            </span>
                        ) : (
                            <span className="text-xs text-gray-600 shrink-0">
                                {chatCollection?.image_count || 0} image{(chatCollection?.image_count || 0) !== 1 ? 's' : ''}
                            </span>
                        );
                    })()}
                </div>
                {sceneJobId && (() => {
                    const ss = activeStreamEntries.find(
                        (item) => item.jobId && item.jobData?.chatId === activeChat?.id && (item.jobData?.type === 'image' || item.jobData?.taskType === 'image')
                    );
                    const prog = ss?.jobData?.progress;
                    const pct = Number.isFinite(prog) ? Math.min(100, Math.max(0, Math.round(prog))) : null;
                    return (
                        <div className="mb-2">
                            <div className="flex items-center gap-2 text-xs text-purple-400 mb-1">
                                <Loader2 size={12} className="animate-spin" />
                                {pct != null ? `Generating scene image… ${pct}%` : 'Generating scene image...'}
                            </div>
                            <div className="h-1.5 w-full rounded-full bg-gray-800 overflow-hidden">
                                <div
                                    className={`h-full bg-gradient-to-r from-purple-500 to-indigo-400 rounded-full transition-all ${pct == null ? 'animate-pulse' : ''}`}
                                    style={{ width: `${pct ?? 60}%` }}
                                />
                            </div>
                        </div>
                    );
                })()}
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
                <div className="flex items-center justify-between gap-2 mb-3">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 min-w-0">
                        <BookOpen size={12} /> Lorebooks
                    </h4>
                    <div className="flex items-center gap-1.5 shrink-0">
                        {/* The story panel has had this create-in-place affordance
                            since it was written; here it was a "Manage" link to
                            another page and nothing else, so making a lorebook
                            meant leaving the chat you were configuring. */}
                        <button
                            type="button"
                            data-testid="new-lorebook"
                            onClick={() => onEditLorebook?.(null)}
                            className="p-1 rounded text-gray-500 hover:text-indigo-400 hover:bg-white/10 transition-colors inline-flex items-center justify-center"
                            title="New Lorebook"
                            aria-label="New Lorebook"
                        >
                            <Plus size={14} />
                        </button>
                        <Link
                            to="/lorebooks"
                            className="inline-flex items-center min-h-[24px] px-2 text-xs text-blue-400 hover:text-blue-300 font-medium rounded bg-blue-500/10 hover:bg-blue-500/20 transition-colors"
                        >
                            Manage
                        </Link>
                    </div>
                </div>
                {queryErrors.lorebooks ? (
                    <QueryErrorState
                        noun={queryErrors.lorebooks.noun}
                        error={queryErrors.lorebooks.error}
                        onRetry={queryErrors.lorebooks.refetch}
                    />
                ) : lorebooks.length === 0 ? (
                    <p className="text-xs text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">
                        No lorebooks available
                    </p>
                ) : (
                    <div className="space-y-1.5">
                        {lorebooks.map(lb => {
                            const isActive = selectedLorebooks.includes(lb.id);
                            return (
                                <div
                                    key={lb.id}
                                    className={clsx(
                                        "w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm transition-colors group",
                                        isActive
                                            ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                                            : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                    )}
                                >
                                    <button
                                        type="button"
                                        data-testid={`lorebook-row-${lb.id}`}
                                        onClick={() => {
                                            const newLorebooks = isActive
                                                ? selectedLorebooks.filter(id => id !== lb.id)
                                                : [...selectedLorebooks, lb.id];
                                            onChatUpdate({ active_lorebook_ids: newLorebooks });
                                        }}
                                        className="flex-1 text-left flex items-center gap-2 min-w-0"
                                    >
                                        {isActive
                                            ? <Check size={13} className="text-indigo-400 shrink-0" />
                                            : <div className="w-3 h-3 rounded border border-gray-600 shrink-0" />
                                        }
                                        <span className="truncate font-medium text-xs">{lb.name}</span>
                                    </button>
                                    <button
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); onEditLorebook?.(lb); }}
                                        className="p-1 rounded text-gray-500 hover:text-indigo-400 hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                                        title="Edit Lorebook"
                                        aria-label={`Edit ${lb.name}`}
                                    >
                                        <Edit2 size={12} />
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                )}
                {selectedLorebooks.length > 0 && (
                    <p className="text-xs text-gray-500 mt-2 px-1">
                        {selectedLorebooks.length} lorebook{selectedLorebooks.length !== 1 ? 's' : ''} active
                    </p>
                )}
            </div>

            {/* Locations
                `Chat.location_id` had exactly one reader (the inspector above)
                and no writer anywhere in the app: the new-chat wizard wrote free
                text into `story_location` instead, so a chat's location image,
                atmosphere and tags never reached the prompt and the Locations
                page was unreachable from a chat. Unlike a story's
                `location_ids`, this column is a single FK, so the row list is a
                single choice — click to make it the chat's location, click again
                to leave. */}
            <div className="glass-panel p-4 rounded-xl border border-white/5">
                <div className="flex items-center justify-between gap-2 mb-3">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 min-w-0">
                        <MapPin size={12} className="text-emerald-400 shrink-0" /> Location
                    </h4>
                    <button
                        type="button"
                        data-testid="new-location"
                        onClick={() => onEditLocation?.(null)}
                        className="p-1 rounded text-gray-500 hover:text-emerald-400 hover:bg-white/10 transition-colors inline-flex items-center justify-center"
                        title="New Location"
                        aria-label="New Location"
                    >
                        <Plus size={14} />
                    </button>
                </div>
                {locations.length === 0 ? (
                    <p className="text-xs text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">
                        No locations
                    </p>
                ) : (
                    <div className="space-y-1.5" data-testid="chat-locations">
                        {locations.map(loc => {
                            const isActive = activeChat?.location_id === loc.id;
                            return (
                                <div
                                    key={loc.id}
                                    className={clsx(
                                        "w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm transition-colors group",
                                        isActive
                                            ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                            : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                    )}
                                >
                                    <button
                                        type="button"
                                        data-testid={`location-row-${loc.id}`}
                                        aria-pressed={isActive}
                                        onClick={() => onChatUpdate({ location_id: isActive ? null : loc.id })}
                                        className="flex-1 text-left flex items-center gap-2 min-w-0"
                                    >
                                        {isActive
                                            ? <Check size={13} className="text-emerald-400 shrink-0" />
                                            : <div className="w-3 h-3 rounded border border-gray-600 shrink-0" />
                                        }
                                        <span className="min-w-0">
                                            <span className="block truncate font-medium text-xs">{loc.name}</span>
                                            {(loc.atmosphere || loc.description) && (
                                                <span className="block truncate text-2xs text-gray-500">{loc.atmosphere || loc.description}</span>
                                            )}
                                        </span>
                                    </button>
                                    <button
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); onEditLocation?.(loc); }}
                                        className="p-1 rounded text-gray-500 hover:text-emerald-400 hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                                        title="Edit Location"
                                        aria-label={`Edit ${loc.name}`}
                                    >
                                        <Edit2 size={12} />
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                )}
                {activeChat?.location_id ? (
                    <p className="text-xs text-gray-500 mt-2 px-1">
                        Its description, atmosphere and tags are injected into the prompt. Click the row again to leave.
                    </p>
                ) : (
                    <p className="text-xs text-gray-600 mt-2 px-1">
                        Pick a location to inject its description, atmosphere and tags. A chat is in one location at a time.
                    </p>
                )}
            </div>

            {/* Memories */}
            {linkedCharacter && (
                <div key={`mem-${linkedCharacter.id}`} className="glass-panel rounded-xl border border-white/5">
                    <details className="group">
                        <summary className="flex items-center justify-between p-4 cursor-pointer list-none">
                            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                                <Brain size={12} /> Memories
                            </h4>
                            <ChevronDown size={14} className="text-gray-500 transition-transform group-open:rotate-180" />
                        </summary>
                        <div className="px-3 pb-3 -mt-1">
                            <MemoriesPanel characterId={linkedCharacter.id} />
                        </div>
                    </details>
                </div>
            )}

            {/* Expressions (if character has any) */}
            {linkedCharacter?.expressions && Object.keys(linkedCharacter.expressions).some(k => !k.startsWith('_')) && (
                <ExpressionSelector character={linkedCharacter} characterId={linkedCharacter.id} inline />
            )}
        </div>
    );
}

/**
 * Author's Note (with its depth), Story Time and Location, behind one
 * disclosure. They were three sibling panels in an eleven-panel column; they
 * are advanced knobs that most sessions never touch, so they now cost one row
 * until asked for. Everything stays in the DOM and reachable by opening it.
 */
function SceneOverridesSection({ chat, onSave }) {
    const [depth, setDepth] = useState(chat?.authors_note_depth ?? 4);
    const savedDepth = chat?.authors_note_depth ?? 4;

    const setCount = [
        chat?.authors_note,
        chat?.story_time,
        chat?.story_location,
    ].filter(Boolean).length;

    return (
        <details data-testid="scene-overrides" className="group glass-panel rounded-xl border border-white/5">
            <summary className="flex items-center justify-between gap-2 p-4 cursor-pointer list-none">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                    <NotebookPen size={12} /> Scene Overrides
                </h4>
                <span className="flex items-center gap-1.5 min-w-0">
                    <span className="text-xs text-gray-500 truncate">
                        {setCount ? `${setCount} set` : 'None set'}
                    </span>
                    <ChevronDown size={14} className="shrink-0 text-gray-500 transition-transform group-open:rotate-180" />
                </span>
            </summary>
            <div className="px-4 pb-4 -mt-1 space-y-4">
                <div>
                    <label htmlFor="authors-note" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1 flex items-center gap-1.5">
                        <NotebookPen size={12} /> Author's Note
                    </label>
                    <textarea
                        id="authors-note"
                        data-testid="authors-note-input"
                        defaultValue={chat?.authors_note || ''}
                        onBlur={(e) => {
                            const val = e.target.value.trim() || null;
                            if (val !== (chat?.authors_note || null)) onSave({ authors_note: val });
                        }}
                        placeholder="e.g. Keep replies under 3 sentences."
                        title="A directive injected N messages from the end of context (survives pruning). 0 pins it to the very end; the default depth is 4 messages from the tail."
                        rows={2}
                        className="w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg px-2.5 py-2 text-gray-300 placeholder-gray-600 focus:outline-none focus:border-blue-500/40 resize-none"
                    />
                    <div className="mt-2 flex items-center gap-3">
                        <span className="text-xs text-gray-500 uppercase tracking-wider shrink-0">Depth</span>
                        <input
                            data-testid="authors-note-depth"
                            type="range"
                            min={0}
                            max={20}
                            step={1}
                            value={depth}
                            onChange={(e) => setDepth(Number(e.target.value))}
                            onMouseUp={() => { if (depth !== savedDepth) onSave({ authors_note_depth: depth }); }}
                            onTouchEnd={() => { if (depth !== savedDepth) onSave({ authors_note_depth: depth }); }}
                            className="flex-1 min-w-0 accent-sky-500 min-h-[24px]"
                        />
                        <span className={`text-xs font-mono w-8 text-right ${depth !== savedDepth ? 'text-amber-400' : 'text-sky-400'}`}>
                            {depth}{depth !== savedDepth ? '*' : ''}
                        </span>
                        {chat?.authors_note_depth != null && (
                            <button
                                type="button"
                                onClick={() => onSave({ authors_note_depth: null })}
                                className="inline-flex items-center min-h-[24px] px-1 text-xs text-gray-500 hover:text-gray-300 transition-colors shrink-0"
                                title="Reset to global default depth (4)"
                            >
                                reset
                            </button>
                        )}
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                        A directive injected N messages from the end of context, so it survives pruning. 0 pins the note to the very end; the default is 4 messages from the tail.
                    </p>
                </div>
                <ContextField
                    inline
                    showLabel
                    label="Story Time"
                    icon={Clock}
                    value={chat?.story_time}
                    placeholder="Not set"
                    onSave={val => onSave({ story_time: val })}
                />
                {/* The free-text Location field that used to live here is gone.
                    It was the only thing this panel ever offered, it wrote
                    `story_location` and nothing read it back as a location, and
                    a second "Location" control next to the real, linked Location
                    picker above is how the two drifted apart in the first place.
                    The real picker also mirrors its choice into
                    `story_location`, so this text is still what reaches the
                    prompt's `Current Location:` line. */}
            </div>
        </details>
    );
}

export default ChatContextPanel;
