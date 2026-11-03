import clsx from 'clsx';
import { memo, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
    User, Clock, Activity, Sparkles, ImageIcon, Loader2, BookOpen, Check, MessageSquare, Brain, ChevronDown, NotebookPen,
    MapPin, Plus, Edit2, Calendar, Layers, Shield, Users, Compass, Shirt, Eye, Lock, Unlock, Zap,
} from 'lucide-react';
import {
    getAvatarUrl,
    useEvaluateChatDirector,
    useUpdateChatStateSnapshot,
    useCommitChatToCanon,
    useCompileChatToStory,
    useRunWorldTick,
    useReverseVisionSync,
    useFastTravelChat,
    useVisualizeInventoryItem,
    useLLMRuntimeDefaults,
} from '../../hooks/useWorldVault';
import { useLocations } from '../../hooks/useLocations';
import { isJobComplete, isJobFailed, isJobRunning } from '../../utils/jobStatus';
import { parseGalleryDate } from '../../utils/dateTime';
import { classifyDirectorEngine } from '../../utils/directorEngine';
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
    const isStateUpdater = job.type === 'state_updater' || job.metadata?.source === 'state_updater';
    const isFailed = isJobFailed(job.status);
    const isComplete = isJobComplete(job.status);
    const label = isImage
        ? (job.type === 'agentic_image' ? 'Image generation' : 'Image job')
        : isStateUpdater
            ? 'Statekeeper update'
            : 'LLM reply';
    return (
        <div className={clsx(
            "flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs border",
            isFailed ? "bg-red-500/5 border-red-500/15 text-red-300" :
                isComplete ? (isImage ? "bg-emerald-500/5 border-emerald-500/15 text-emerald-300" : isStateUpdater ? "bg-purple-500/5 border-purple-500/15 text-purple-300" : "bg-blue-500/5 border-blue-500/15 text-blue-300") :
                    isRunning ? "bg-amber-500/5 border-amber-500/15 text-amber-300" : "bg-gray-800/30 border-gray-700/30 text-gray-400"
        )}>
            <span className={clsx("w-1.5 h-1.5 rounded-full shrink-0", isFailed ? "bg-red-400" : isComplete ? (isImage ? "bg-emerald-400" : isStateUpdater ? "bg-purple-400" : "bg-blue-400") : isRunning ? "bg-amber-400 animate-pulse" : "bg-gray-600")} />
            <span className="truncate flex-1 font-medium">{label}</span>
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

const CONTEXT_TABS = [
    { id: 'scene', label: 'Scene', icon: Compass },
    { id: 'cast', label: 'Cast', icon: Users },
    { id: 'lore', label: 'Lore', icon: BookOpen },
    { id: 'generation', label: 'AI Model', icon: Sparkles },
];

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
    const {
        data: locations = [],
        isError: isLocationsError,
        error: locationsError,
        refetch: refetchLocations,
    } = useLocations();

    const navigate = useNavigate();

    const onChatUpdate = (data) => handleChatUpdate(data);
    const onCharacterPatch = (data) => {
        if (linkedCharacter?.id) {
            patchCharacterMutation.mutate({ ...data, id: linkedCharacter.id });
        }
    };
    const onShowCharacterDetails = () => setShowCharacterDetails(true);
    const onShowScenes = () => setShowScenesModal(true);

    const { data: runtimeDefaults } = useLLMRuntimeDefaults();
    const [activeTab, setActiveTab] = useState('scene');

    const lorebookContextText = useMemo(
        () => messages
            .slice(-LOREBOOK_CONTEXT_TAIL)
            .map(m => m?.content || '')
            .join('\n'),
        [messages]
    );

    return (
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
            {/* 4-Tab Navigation Bar */}
            <div className="flex items-center gap-1 p-1 bg-gray-900/80 rounded-xl border border-white/5 sticky top-0 z-10 backdrop-blur-md mb-2 shadow-sm">
                {CONTEXT_TABS.map(tab => {
                    const Icon = tab.icon;
                    const isActive = activeTab === tab.id;
                    return (
                        <button
                            key={tab.id}
                            type="button"
                            data-testid={`context-tab-${tab.id}`}
                            onClick={() => setActiveTab(tab.id)}
                            className={clsx(
                                "flex-1 flex items-center justify-center gap-1.5 py-1.5 px-1.5 rounded-lg text-xs font-medium transition-all",
                                isActive
                                    ? "bg-purple-600/30 text-purple-200 border border-purple-500/30 shadow-sm"
                                    : "text-gray-400 hover:text-gray-200 hover:bg-white/5 border border-transparent"
                            )}
                        >
                            <Icon size={13} className={isActive ? "text-purple-400" : "text-gray-500"} />
                            <span className="truncate">{tab.label}</span>
                        </button>
                    );
                })}
            </div>

            {/* Tab 1: Scene & State */}
            <div className={clsx("space-y-4", activeTab !== 'scene' && "hidden")}>
                <DirectorStatekeeperSection
                    key={`dir-${activeChat?.id}`}
                    chat={activeChat}
                    onSave={onChatUpdate}
                />

                <SceneOverridesSection
                    key={`so-${activeChat?.id}`}
                    chat={activeChat}
                    onSave={onChatUpdate}
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

                {/* Chat Jobs (LLM + image progress for this chat) */}
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <div className="flex items-center justify-between mb-2">
                        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                            <Activity size={12} /> Jobs
                        </h4>
                        <span className="text-xs text-gray-600 shrink-0">{chatJobs?.length || 0} total</span>
                    </div>
                    {queryErrors.chatJobs ? (
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
            </div>

            {/* Tab 2: Cast & Persona */}
            <div className={clsx("space-y-4", activeTab !== 'cast' && "hidden")}>
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

            {/* Tab 3: Lore & Canon */}
            <div className={clsx("space-y-4", activeTab !== 'lore' && "hidden")}>
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

                {/* Lorebooks */}
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <div className="flex items-center justify-between gap-2 mb-3">
                        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 min-w-0">
                            <BookOpen size={12} /> Lorebooks
                        </h4>
                        <div className="flex items-center gap-1.5 shrink-0">
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

                {/* Locations */}
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
                    {(queryErrors.locations || isLocationsError) ? (
                        <QueryErrorState
                            noun={queryErrors.locations?.noun || 'locations'}
                            error={queryErrors.locations?.error || locationsError}
                            onRetry={queryErrors.locations?.refetch || refetchLocations}
                        />
                    ) : locations.length === 0 ? (
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
            </div>

            {/* Tab 4: Model & Prompts */}
            <div className={clsx("space-y-4", activeTab !== 'generation' && "hidden")}>
                {/* Runtime Configuration & Statistics Overview */}
                <div className="glass-panel p-3.5 rounded-xl border border-white/5 bg-gradient-to-br from-purple-500/5 via-blue-500/5 to-transparent">
                    <div className="flex items-center justify-between mb-2.5">
                        <h4 className="text-2xs font-bold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                            <Activity size={11} className="text-purple-400" /> Active Generation Config
                        </h4>
                        <span className="text-2xs text-gray-500 font-mono">
                            {activeChat?.llm_model || activeChat?.max_context_tokens || activeChat?.max_output_tokens || activeChat?.temperature != null
                                ? 'Custom overrides'
                                : 'Default profile'}
                        </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="bg-gray-800/40 border border-white/5 rounded-lg p-2">
                            <span className="block text-2xs text-gray-500 font-medium uppercase tracking-wider">Max Input</span>
                            <span className="font-mono text-gray-200 font-semibold">
                                {(activeChat?.max_context_tokens ?? runtimeDefaults?.max_context_tokens ?? runtimeDefaults?.context_tokens ?? 4096).toLocaleString()} tok
                            </span>
                            <span className="block text-2xs text-gray-500 truncate">
                                {activeChat?.max_context_tokens ? 'Per-chat override' : 'Engine default'}
                            </span>
                        </div>
                        <div className="bg-gray-800/40 border border-white/5 rounded-lg p-2">
                            <span className="block text-2xs text-gray-500 font-medium uppercase tracking-wider">Max Output</span>
                            <span className="font-mono text-gray-200 font-semibold">
                                {(activeChat?.max_output_tokens ?? runtimeDefaults?.max_output_tokens ?? 2048).toLocaleString()} tok
                            </span>
                            <span className="block text-2xs text-gray-500 truncate">
                                {activeChat?.max_output_tokens ? 'Per-chat override' : 'Engine default'}
                            </span>
                        </div>
                        <div className="bg-gray-800/40 border border-white/5 rounded-lg p-2">
                            <span className="block text-2xs text-gray-500 font-medium uppercase tracking-wider">Temperature</span>
                            <span className="font-mono text-gray-200 font-semibold">
                                {Number(activeChat?.temperature ?? runtimeDefaults?.temperature ?? 1.0).toFixed(2)}
                            </span>
                            <span className="block text-2xs text-gray-500 truncate">
                                Top P: {Number(activeChat?.top_p ?? runtimeDefaults?.top_p ?? 1.0).toFixed(2)}
                            </span>
                        </div>
                        <div className="bg-gray-800/40 border border-white/5 rounded-lg p-2">
                            <span className="block text-2xs text-gray-500 font-medium uppercase tracking-wider">Active Model</span>
                            <span className="font-mono text-gray-200 font-semibold truncate block" title={activeChat?.llm_model || defaultLlmConfig?.model_id || 'default'}>
                                {activeChat?.llm_model || defaultLlmConfig?.model_id || 'Default'}
                            </span>
                            <span className="block text-2xs text-gray-500 truncate">
                                {activeChat?.llm_model ? 'Per-chat override' : 'Default provider'}
                            </span>
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
                                    ? `${(activeChat.max_context_tokens / 1024).toFixed(0)}k tokens (${activeChat.max_context_tokens.toLocaleString()})`
                                    : `Default (${(runtimeDefaults?.max_context_tokens || runtimeDefaults?.context_tokens || 4096).toLocaleString()} tok · 32k max)`}
                            </span>
                        </div>
                        <ContextSlider
                            activeChat={activeChat}
                            defaultTokens={runtimeDefaults?.max_context_tokens || runtimeDefaults?.context_tokens || 4096}
                            onChange={(val) => onChatUpdate({ max_context_tokens: val })}
                        />
                        <div className="flex justify-between text-xs text-gray-600 mt-0.5">
                            <span>1k</span><span>8k</span><span>16k</span><span>24k</span><span>32k</span>
                        </div>
                        {activeChat?.max_context_tokens && (
                            <button
                                onClick={() => onChatUpdate({ max_context_tokens: null })}
                                className="mt-1 inline-flex items-center min-h-[24px] text-xs text-gray-500 hover:text-red-400 transition-colors"
                            >
                                Reset to default ({(runtimeDefaults?.max_context_tokens || runtimeDefaults?.context_tokens || 4096).toLocaleString()} tokens)
                            </button>
                        )}
                    </div>

                    {/* KV Cache Precision & Laya Continuation */}
                    <div className="pt-2 border-t border-white/5 space-y-3">
                        <div className="flex items-center justify-between gap-2">
                            <div>
                                <label className="text-xs text-gray-300 font-medium block">KV Cache Precision</label>
                                <span className="text-2xs text-gray-500">4-bit saves ~4GB VRAM for large contexts</span>
                            </div>
                            <select
                                value={activeChat?.kv_cache_type || 'q8_0'}
                                onChange={(e) => onChatUpdate({ kv_cache_type: e.target.value })}
                                className="bg-gray-800 border border-white/10 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-purple-500/50"
                            >
                                <option value="q8_0">8-bit (q8_0 - Default)</option>
                                <option value="q4_0">4-bit (q4_0 - Memory Saver)</option>
                            </select>
                        </div>

                        <div className="flex items-center justify-between gap-2">
                            <div>
                                <label className="text-xs text-gray-300 font-medium block flex items-center gap-1.5">
                                    <Zap size={12} className="text-amber-400" />
                                    Smart Chained Continuation
                                </label>
                                <span className="text-2xs text-gray-500">Laya System 1 auto-resumes cut-off text</span>
                            </div>
                            <input
                                type="checkbox"
                                checked={activeChat?.smart_continuation !== false}
                                onChange={(e) => onChatUpdate({ smart_continuation: e.target.checked })}
                                className="accent-purple-500 h-4 w-4 rounded"
                            />
                        </div>
                    </div>
                    <SamplingControls values={activeChat || {}} onChange={onChatUpdate} />
                    <div>
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
                            <p className="text-xs text-gray-300 font-medium">Illustrator authors the parameters</p>
                            <p className="text-xs text-gray-600 mt-1">
                                Lets the Illustrator choose the sampler, resolution, steps and LoRA for
                                a scene, not just its prompt. The numbers are bounded and the model
                                names are checked before the image is generated.
                            </p>
                        </div>
                        <button
                            role="switch"
                            aria-label="Illustrator authors the parameters"
                            aria-checked={activeChat?.scene_graph_enabled === true}
                            onClick={() => onChatUpdate({ scene_graph_enabled: activeChat?.scene_graph_enabled !== true })}
                            className={clsx(
                                "relative w-10 h-6 rounded-full transition-colors shrink-0",
                                activeChat?.scene_graph_enabled === true ? "bg-purple-500" : "bg-gray-700"
                            )}
                        >
                            <span className={clsx(
                                "absolute top-1 w-4 h-4 rounded-full bg-white transition-all",
                                activeChat?.scene_graph_enabled === true ? "left-5.5" : "left-0.5"
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
            </div>
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

function DirectorStatekeeperSection({ chat, onSave }) {
    const navigate = useNavigate();
    const evaluateDirector = useEvaluateChatDirector();
    const updateSnapshot = useUpdateChatStateSnapshot();
    const commitCanon = useCommitChatToCanon();
    const compileStory = useCompileChatToStory();
    const runWorldTick = useRunWorldTick();
    const reverseVision = useReverseVisionSync();
    const fastTravel = useFastTravelChat();
    const visualizeItem = useVisualizeInventoryItem();
    const { data: allLocations = [] } = useLocations();

    const [inventoryInput, setInventoryInput] = useState('');
    const [charSkillInput, setCharSkillInput] = useState('');
    const [userSkillInput, setUserSkillInput] = useState('');
    const [newRelTarget, setNewRelTarget] = useState('');
    const [newRelType, setNewRelType] = useState('character');
    const [newRelStatus, setNewRelStatus] = useState('');
    const [newRelAffinity] = useState('neutral');
    const [wardrobeNameInput, setWardrobeNameInput] = useState('');
    const [fastTravelLocInput, setFastTravelLocInput] = useState('');
    const [actionFeedback, setActionFeedback] = useState('');
    const [showDecisionInspector, setShowDecisionInspector] = useState(false);

    if (!chat?.id) return null;

    const directorEnabled = chat.director_enabled !== false;
    const snap = chat.state_snapshot || {};
    const lastDecision = snap.last_director_decision || snap.last_decision || null;
    // The engine stamp says which tier of the Laya cascade actually answered
    // (an in-process or remote Laya pass, a generative fallback, the rule
    // table, or nothing). Show degraded tiers as degraded instead of in the
    // same green as a live pass, so a director that fell back is visible
    // from the chat, not only on the Studio's Decision Traces tab.
    const engineInfo = classifyDirectorEngine(lastDecision);
    const tension = Number(snap.scene_tension || lastDecision?.scene_tension || 2);
    const tensionLabel = snap.scene_tension_label || lastDecision?.scene_tension_label || 'normal';
    const inventoryList = Array.isArray(snap.inventory) ? snap.inventory : [];
    const charSkills = Array.isArray(snap.character_skills) ? snap.character_skills : [];
    const userSkills = Array.isArray(snap.user_skills) ? snap.user_skills : [];
    const wardrobeList = Array.isArray(snap.wardrobe) ? snap.wardrobe : [];
    const relationshipsList = Array.isArray(snap.relationships) ? snap.relationships : [];
    const worldClock = snap.world_clock && typeof snap.world_clock === 'object' ? snap.world_clock : null;
    const chronologyLog = Array.isArray(worldClock?.chronology_log) ? worldClock.chronology_log : [];

    const fateEnabled = Boolean(snap.fate_check_enabled);
    const fateDifficulty = snap.fate_difficulty || 'auto';
    const fateOutcomeOverride = snap.fate_outcome_override || 'auto';
    const lastFateOutcome = snap.last_fate_outcome || lastDecision?.fate_outcome || null;
    const lastFateDirective = snap.last_fate_directive || lastDecision?.fate_directive || null;
    const matchedSkills = Array.isArray(snap.matched_skills)
        ? snap.matched_skills
        : (Array.isArray(lastDecision?.matched_skills) ? lastDecision.matched_skills : []);

    const worldLocations = chat.world_id
        ? allLocations.filter((l) => l.world_id === chat.world_id)
        : allLocations.slice(0, 12);

    const flashFeedback = (msg) => {
        setActionFeedback(msg);
        setTimeout(() => setActionFeedback(''), 3500);
    };

    const handleFieldSave = (key, val) => {
        const payload = (key === 'relationship_status' || key === 'relationship')
            ? { relationship_status: val, relationship: val }
            : { [key]: val };
        updateSnapshot.mutate({
            chatId: chat.id,
            state_snapshot: payload,
        });
    };

    const lockedFields = Array.isArray(snap.locked_fields) ? snap.locked_fields : [];
    const isLocked = (field) => {
        if (field === 'relationship_status' || field === 'relationship') {
            return lockedFields.includes('relationship_status') || lockedFields.includes('relationship');
        }
        if (field === 'character_expression' || field === 'expression') {
            return lockedFields.includes('character_expression') || lockedFields.includes('expression');
        }
        return lockedFields.includes(field);
    };
    const toggleLock = (field) => {
        const locked = isLocked(field);
        let next;
        if (field === 'relationship_status' || field === 'relationship') {
            next = locked
                ? lockedFields.filter((f) => f !== 'relationship_status' && f !== 'relationship')
                : [...lockedFields, 'relationship_status', 'relationship'];
        } else if (field === 'character_expression' || field === 'expression') {
            next = locked
                ? lockedFields.filter((f) => f !== 'character_expression' && f !== 'expression')
                : [...lockedFields, 'character_expression', 'expression'];
        } else {
            next = locked
                ? lockedFields.filter((f) => f !== field)
                : [...lockedFields, field];
        }
        handleFieldSave('locked_fields', next);
        flashFeedback(`${!locked ? 'Locked' : 'Unlocked'} ${field.replace(/_/g, ' ')}`);
    };

    const handleAddInventory = (e) => {
        e.preventDefault();
        const item = inventoryInput.trim();
        if (!item) return;
        const next = Array.from(new Set([...inventoryList, item]));
        setInventoryInput('');
        handleFieldSave('inventory', next);
    };

    const handleRemoveInventory = (item) => {
        handleFieldSave('inventory', inventoryList.filter((x) => x !== item));
    };

    const handleAddSkill = (e, field, list, inputVal, setInputVal) => {
        e.preventDefault();
        const s = inputVal.trim();
        if (!s) return;
        const next = Array.from(new Set([...list, s]));
        setInputVal('');
        handleFieldSave(field, next);
    };

    const handleRemoveSkill = (field, list, skill) => {
        handleFieldSave(field, list.filter((x) => x !== skill));
    };

    const handleSaveWardrobePreset = (e) => {
        e.preventDefault();
        const currentOutfit = (snap.character_outfit || '').trim();
        if (!currentOutfit) return;
        const presetName = wardrobeNameInput.trim() || `Look #${wardrobeList.length + 1}`;
        const next = [
            ...wardrobeList.filter((w) => (w.name || '').toLowerCase() !== presetName.toLowerCase()),
            { name: presetName, outfit: currentOutfit, visual_tags: currentOutfit },
        ];
        setWardrobeNameInput('');
        handleFieldSave('wardrobe', next);
        flashFeedback(`Saved outfit preset "${presetName}"`);
    };

    const handleSelectWardrobePreset = (preset) => {
        const outfitText = preset.outfit || preset.description || preset.name;
        handleFieldSave('character_outfit', outfitText);
        flashFeedback(`Switched outfit to "${preset.name}"`);
    };

    const handleAddRelationship = (e) => {
        e.preventDefault();
        const target = newRelTarget.trim();
        const status = newRelStatus.trim();
        if (!target || !status) return;
        const filtered = relationshipsList.filter(
            (r) => (r.target_name || '').toLowerCase() !== target.toLowerCase()
        );
        const next = [
            ...filtered,
            {
                target_name: target,
                target_type: newRelType,
                status,
                affinity: newRelAffinity,
            },
        ];
        setNewRelTarget('');
        setNewRelStatus('');
        updateSnapshot.mutate({
            chatId: chat.id,
            state_snapshot: {
                relationships: next,
                ...(newRelType === 'user' ? { relationship_status: status } : {}),
            },
        });
    };

    const handleUpdateRelationship = (index, patch) => {
        const next = relationshipsList.map((r, i) => (i === index ? { ...r, ...patch } : r));
        const updatedRow = next[index];
        updateSnapshot.mutate({
            chatId: chat.id,
            state_snapshot: {
                relationships: next,
                ...(updatedRow?.target_type === 'user' && patch.status
                    ? { relationship_status: patch.status }
                    : {}),
            },
        });
    };

    const handleRemoveRelationship = (index) => {
        const next = relationshipsList.filter((_, i) => i !== index);
        handleFieldSave('relationships', next);
    };

    const handleFastTravel = (locId, locName) => {
        fastTravel.mutate(
            { chatId: chat.id, locationId: locId || null, locationName: locName || null },
            {
                onSuccess: (res) => {
                    setFastTravelLocInput('');
                    flashFeedback(`Traveled to ${res.story_location}`);
                },
            }
        );
    };

    return (
        <details
            data-testid="director-statekeeper-panel"
            open
            className="group glass-panel rounded-xl border border-emerald-500/20 bg-emerald-950/5"
        >
            <summary className="flex items-center justify-between gap-2 p-4 cursor-pointer list-none">
                <h4 className="text-xs font-semibold text-emerald-300 uppercase tracking-widest flex items-center gap-1.5">
                    <Sparkles size={12} className="text-emerald-400" /> Director &amp; Statekeeper
                </h4>
                <span className="flex items-center gap-1.5 min-w-0">
                    <span className={clsx(
                        "px-1.5 py-0.5 rounded text-2xs font-bold uppercase",
                        directorEnabled
                            ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                            : "bg-gray-800 text-gray-500"
                    )}>
                        {directorEnabled ? `Active • T${tension}/5` : 'Paused'}
                    </span>
                    <ChevronDown size={14} className="shrink-0 text-gray-500 transition-transform group-open:rotate-180" />
                </span>
            </summary>

            <div className="px-4 pb-4 -mt-1 space-y-3 text-xs">
                {actionFeedback && (
                    <div className="px-2.5 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-200 text-2xs font-medium">
                        {actionFeedback}
                    </div>
                )}

                {/* Toggle & Quick Actions */}
                <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-white/5">
                    <label className="flex items-center gap-2 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={directorEnabled}
                            onChange={(e) => onSave({ director_enabled: e.target.checked })}
                            className="accent-emerald-500"
                        />
                        <span className="text-xs text-gray-300 font-medium">System 1 Auto-Director</span>
                    </label>
                    <div className="flex items-center gap-1.5">
                        <button
                            type="button"
                            onClick={() => evaluateDirector.mutate({ chatId: chat.id, force_updater: false })}
                            disabled={evaluateDirector.isPending}
                            className="px-2 py-1 rounded bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 text-emerald-300 text-2xs font-semibold flex items-center gap-1 transition-colors disabled:opacity-50"
                            title="Evaluate the current scene with the 13-question System 1 Director (0 MB GPU VRAM)"
                        >
                            {evaluateDirector.isPending ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                            Evaluate
                        </button>
                        <button
                            type="button"
                            onClick={() => evaluateDirector.mutate({ chatId: chat.id, force_updater: true })}
                            disabled={evaluateDirector.isPending}
                            className="px-2 py-1 rounded bg-purple-500/15 hover:bg-purple-500/25 border border-purple-500/30 text-purple-300 text-2xs font-semibold flex items-center gap-1 transition-colors disabled:opacity-50"
                            title="Force the Statekeeper (Updater) to extract world state deltas on the Util model"
                        >
                            <Brain size={10} />
                            Sync State
                        </button>
                    </div>
                </div>

                {/* Director Autonomy Mode & Turn Cap */}
                <div className="flex items-center justify-between gap-2 pb-2 border-b border-white/5 text-2xs">
                    <div>
                        <label className="text-gray-300 font-medium block">Director Autonomy</label>
                        <span className="text-gray-500">Autonomous scene conductor turns</span>
                    </div>
                    <select
                        value={chat.director_autonomy_level || 'balanced'}
                        onChange={(e) => onSave({ director_autonomy_level: e.target.value })}
                        className="bg-gray-800 border border-white/10 rounded px-2 py-1 text-2xs text-gray-200 focus:outline-none focus:border-emerald-500/50"
                    >
                        <option value="strict">Strict (1 turn / User reply)</option>
                        <option value="balanced">Balanced (Up to {chat.max_autonomous_turns || 4} turns, prob ≥ 0.65)</option>
                        <option value="cinematic">Cinematic (Up to {chat.max_autonomous_turns || 4} turns, prob ≥ 0.50)</option>
                    </select>
                </div>

                {/* Statekeeper Sensitivity Control */}
                <div className="flex items-center justify-between gap-2 pb-2 border-b border-white/5 text-2xs">
                    <div>
                        <label className="text-gray-300 font-medium block">Statekeeper Sensitivity</label>
                        <span className="text-gray-500">Threshold required to fire background updater</span>
                    </div>
                    <select
                        value={snap.director_mode === 'wild' ? 'wild' : String(snap.gate_threshold || '0.55')}
                        onChange={(e) => {
                            const val = e.target.value;
                            if (val === 'wild') {
                                handleFieldSave('director_mode', 'wild');
                            } else {
                                handleFieldSave('director_mode', 'steered');
                                handleFieldSave('gate_threshold', parseFloat(val));
                            }
                        }}
                        className="bg-gray-800 border border-white/10 rounded px-2 py-1 text-2xs text-purple-200 focus:outline-none focus:border-purple-500/50"
                    >
                        <option value="0.35">Sensitive (35% threshold — triggers frequently)</option>
                        <option value="0.55">Standard (55% threshold — balanced)</option>
                        <option value="0.75">Strict (75% threshold — major changes only)</option>
                        <option value="wild">Wild (Always trigger on every turn)</option>
                    </select>
                </div>

                {/* Illustration Sensitivity Control */}
                <div className="flex items-center justify-between gap-2 pb-2 border-b border-white/5 text-2xs">
                    <div>
                        <label className="text-gray-300 font-medium block">Illustration Sensitivity</label>
                        <span className="text-gray-500">Confidence required for an autonomous scene illustration</span>
                    </div>
                    <select
                        value={String(snap.image_threshold || '0.65')}
                        onChange={(e) => handleFieldSave('image_threshold', parseFloat(e.target.value))}
                        className="bg-gray-800 border border-white/10 rounded px-2 py-1 text-2xs text-amber-200 focus:outline-none focus:border-amber-500/50"
                    >
                        <option value="0.45">Eager (45% threshold — illustrates more beats)</option>
                        <option value="0.65">Standard (65% threshold — balanced)</option>
                        <option value="0.85">Sparing (85% threshold — only striking moments)</option>
                    </select>
                </div>

                {/* Scene Tension, Tone & Pacing Controls */}
                <div className="bg-black/30 rounded-lg p-2.5 border border-white/5 space-y-2">
                    <div className="flex items-center justify-between text-2xs">
                        <span className="text-gray-400 uppercase tracking-wider font-bold flex items-center gap-1.5">
                            <Activity size={11} /> Scene Tension
                        </span>
                        <div className="flex items-center gap-2">
                            <span className="text-amber-300 font-bold uppercase">{tension}/5 · {tensionLabel}</span>
                            <button
                                type="button"
                                onClick={() => toggleLock('scene_tension')}
                                className={clsx(
                                    "p-0.5 rounded transition-colors text-2xs flex items-center gap-1",
                                    isLocked('scene_tension') ? "text-amber-400 bg-amber-500/15" : "text-gray-500 hover:text-gray-300"
                                )}
                                title={isLocked('scene_tension') ? "Locked: Protected from AI & Laya overwrites" : "Unlocked: Can be updated by Director"}
                            >
                                {isLocked('scene_tension') ? <Lock size={11} className="text-amber-400" /> : <Unlock size={11} />}
                                {isLocked('scene_tension') && <span className="text-2xs font-mono font-bold text-amber-400">LOCK</span>}
                            </button>
                        </div>
                    </div>
                    {/* Interactive 5-step Tension Selector */}
                    <div className="grid grid-cols-5 gap-1.5">
                        {[1, 2, 3, 4, 5].map((lvl) => (
                            <button
                                key={lvl}
                                type="button"
                                onClick={() => handleFieldSave('scene_tension', lvl)}
                                className={clsx(
                                    "h-5 rounded text-2xs font-bold transition-all border flex items-center justify-center",
                                    lvl <= tension
                                        ? (tension >= 4
                                            ? "bg-rose-500/30 border-rose-500/50 text-rose-200"
                                            : tension >= 3
                                                ? "bg-amber-500/30 border-amber-500/50 text-amber-200"
                                                : "bg-emerald-500/30 border-emerald-500/50 text-emerald-200")
                                        : "bg-gray-800/60 border-white/5 text-gray-500 hover:bg-white/5"
                                )}
                                title={`Set Scene Tension to ${lvl}/5`}
                            >
                                {lvl}
                            </button>
                        ))}
                    </div>

                    {/* Scene Tone / Atmosphere (Manual Text + Lock) */}
                    <div className="pt-1.5 border-t border-white/5 space-y-1">
                        <div className="flex items-center justify-between text-2xs">
                            <span className="text-gray-400 font-semibold uppercase tracking-wider">Tone / Atmosphere</span>
                            <button
                                type="button"
                                onClick={() => toggleLock('emotional_tone')}
                                className={clsx(
                                    "p-0.5 rounded transition-colors text-2xs flex items-center gap-1",
                                    isLocked('emotional_tone') ? "text-amber-400 bg-amber-500/15" : "text-gray-500 hover:text-gray-300"
                                )}
                                title={isLocked('emotional_tone') ? "Locked: Protected from AI & Laya overwrites" : "Unlocked: Can be updated by Director/Statekeeper"}
                            >
                                {isLocked('emotional_tone') ? <Lock size={11} className="text-amber-400" /> : <Unlock size={11} />}
                                {isLocked('emotional_tone') && <span className="text-2xs font-mono font-bold text-amber-400">LOCK</span>}
                            </button>
                        </div>
                        <input
                            type="text"
                            value={snap.emotional_tone || ''}
                            onChange={(e) => handleFieldSave('emotional_tone', e.target.value)}
                            placeholder="e.g. Warm & intimate, tense suspense, rain-soaked noir..."
                            className="w-full bg-gray-900/80 border border-white/10 rounded px-2 py-1 text-2xs text-purple-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                        />
                    </div>

                    {/* Narrative Pacing Directive */}
                    <div className="pt-1 border-t border-white/5 space-y-1">
                        <div className="flex items-center justify-between text-2xs">
                            <span className="text-gray-400 font-semibold uppercase tracking-wider">Pacing Directive</span>
                            <button
                                type="button"
                                onClick={() => toggleLock('pacing_directive')}
                                className={clsx(
                                    "p-0.5 rounded transition-colors text-2xs flex items-center gap-1",
                                    isLocked('pacing_directive') ? "text-amber-400 bg-amber-500/15" : "text-gray-500 hover:text-gray-300"
                                )}
                                title={isLocked('pacing_directive') ? "Locked: Protected from AI & Laya overwrites" : "Unlocked: Can be updated by Director"}
                            >
                                {isLocked('pacing_directive') ? <Lock size={11} className="text-amber-400" /> : <Unlock size={11} />}
                                {isLocked('pacing_directive') && <span className="text-2xs font-mono font-bold text-amber-400">LOCK</span>}
                            </button>
                        </div>
                        <select
                            value={snap.pacing_directive || lastDecision?.pacing_directive || 'continue_conversation'}
                            onChange={(e) => handleFieldSave('pacing_directive', e.target.value)}
                            className="w-full bg-gray-900/80 border border-white/10 rounded px-2 py-1 text-2xs text-blue-200 focus:outline-none focus:border-blue-500/50"
                        >
                            <option value="continue_conversation">Conversational interplay & standard flow</option>
                            <option value="escalate_conflict">Escalate tension, provoke, or raise stakes</option>
                            <option value="introduce_complication">Introduce unexpected obstacle or narrative twist</option>
                            <option value="resolve_and_transition">Resolve scene beat and transition atmosphere</option>
                            <option value="slow_intimate">Slow down: linger on micro-expressions & touch</option>
                        </select>
                    </div>
                </div>

                {/* Toggleable Fate / Skill Check Gate (Anti-Godmoding + Narrative Control) */}
                <div className="bg-black/30 rounded-lg p-2.5 border border-amber-500/20 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                        <label className="flex items-center gap-2 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={fateEnabled}
                                onChange={(e) => handleFieldSave('fate_check_enabled', e.target.checked)}
                                className="accent-amber-500"
                            />
                            <span className="text-2xs font-bold uppercase tracking-wider text-amber-300 flex items-center gap-1">
                                <Shield size={11} /> Fate / Skill Check Gate
                            </span>
                        </label>
                        <div className="flex items-center gap-1.5">
                            <span className="text-2xs text-gray-500">
                                {fateEnabled ? 'Active' : 'Off (Freeform)'}
                            </span>
                            <button
                                type="button"
                                onClick={() => toggleLock('fate')}
                                className={clsx(
                                    "p-0.5 rounded transition-colors text-2xs flex items-center gap-1",
                                    isLocked('fate') ? "text-amber-400 bg-amber-500/15" : "text-gray-500 hover:text-gray-300"
                                )}
                                title={isLocked('fate') ? "Locked: Protected from AI & Laya overwrites" : "Unlocked: Can be updated by Director"}
                            >
                                {isLocked('fate') ? <Lock size={11} className="text-amber-400" /> : <Unlock size={11} />}
                                {isLocked('fate') && <span className="text-2xs font-mono font-bold text-amber-400">LOCK</span>}
                            </button>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-1.5">
                        <div>
                            <label className="block text-2xs text-gray-400 mb-0.5">Difficulty</label>
                            <select
                                aria-label="Fate Check Difficulty"
                                value={fateDifficulty}
                                onChange={(e) => handleFieldSave('fate_difficulty', e.target.value)}
                                className="w-full bg-gray-900/80 border border-white/10 rounded px-1.5 py-1 text-2xs text-gray-200 focus:outline-none focus:border-amber-500/50"
                            >
                                <option value="auto">Auto (Director)</option>
                                <option value="trivial">Trivial (1/5)</option>
                                <option value="easy">Easy (2/5)</option>
                                <option value="moderate">Moderate (3/5)</option>
                                <option value="hard">Hard (4/5)</option>
                                <option value="extreme">Extreme (5/5)</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-2xs text-gray-400 mb-0.5">Desired Outcome</label>
                            <select
                                aria-label="Fate Check Desired Outcome"
                                value={fateOutcomeOverride}
                                onChange={(e) => handleFieldSave('fate_outcome_override', e.target.value)}
                                className="w-full bg-gray-900/80 border border-white/10 rounded px-1.5 py-1 text-2xs text-gray-200 focus:outline-none focus:border-amber-500/50"
                            >
                                <option value="auto">Auto (Skill + Roll)</option>
                                <option value="critical_success">Pin: Critical Success</option>
                                <option value="success">Pin: Clean Success</option>
                                <option value="success_with_cost">Pin: Success w/ Cost</option>
                                <option value="complication">Pin: Complication</option>
                                <option value="failure">Pin: Hard Failure</option>
                            </select>
                        </div>
                    </div>

                    {(fateEnabled || fateOutcomeOverride !== 'auto') && lastFateOutcome && (
                        <div className="text-2xs bg-amber-500/10 border border-amber-500/25 rounded px-2 py-1 text-amber-200 space-y-0.5">
                            <div className="font-semibold uppercase">
                                Outcome: {String(lastFateOutcome).replace(/_/g, ' ')}
                            </div>
                            {matchedSkills.length > 0 && (
                                <div className="text-emerald-300">
                                    Skill Bonus: {matchedSkills.join(', ')}
                                </div>
                            )}
                            {lastFateDirective && (
                                <div className="text-gray-300 italic line-clamp-2">{lastFateDirective}</div>
                            )}
                        </div>
                    )}
                </div>

                {/* Cohesive World Clock & Fast-Travel */}
                <div className="bg-black/30 rounded-lg p-2.5 border border-cyan-500/20 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-2xs font-bold uppercase tracking-wider text-cyan-300 flex items-center gap-1">
                            <Clock size={11} /> World Clock &amp; Fast-Travel
                        </span>
                        <span className="text-2xs font-mono text-cyan-200">
                            Day {worldClock?.day || 1} · {chat.story_time || worldClock?.time_of_day || 'Evening'}
                        </span>
                    </div>

                    {chronologyLog.length > 0 && (
                        <div className="space-y-1 max-h-24 overflow-y-auto pr-1">
                            {chronologyLog.slice(-3).map((ev, idx) => (
                                <div key={idx} className="text-2xs text-gray-300 bg-white/5 rounded px-2 py-1 flex items-start gap-1.5">
                                    <span className="text-cyan-400 font-mono shrink-0">D{ev.day || 1}</span>
                                    <span className="truncate" title={ev.event}>{ev.event}</span>
                                </div>
                            ))}
                        </div>
                    )}

                    {worldLocations.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                            {worldLocations.slice(0, 5).map((loc) => (
                                <button
                                    key={loc.id}
                                    type="button"
                                    onClick={() => handleFastTravel(loc.id, loc.name)}
                                    disabled={fastTravel.isPending}
                                    className={clsx(
                                        "px-2 py-0.5 rounded text-2xs border transition-colors flex items-center gap-1",
                                        chat.location_id === loc.id || chat.story_location === loc.name
                                            ? "bg-cyan-500/25 border-cyan-400/50 text-cyan-200 font-semibold"
                                            : "bg-gray-800/70 border-white/10 text-gray-300 hover:border-cyan-500/40"
                                    )}
                                    title={`Fast-travel to ${loc.name}`}
                                >
                                    <MapPin size={9} />
                                    <span className="truncate max-w-[110px]">{loc.name}</span>
                                </button>
                            ))}
                        </div>
                    )}

                    <form
                        onSubmit={(e) => {
                            e.preventDefault();
                            if (fastTravelLocInput.trim()) handleFastTravel(null, fastTravelLocInput.trim());
                        }}
                        className="flex gap-1"
                    >
                        <input
                            type="text"
                            value={fastTravelLocInput}
                            onChange={(e) => setFastTravelLocInput(e.target.value)}
                            placeholder="Fast-travel to location..."
                            className="flex-1 bg-gray-800/60 border border-white/5 rounded px-2 py-1 text-2xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500/40"
                        />
                        <button
                            type="submit"
                            disabled={fastTravel.isPending}
                            className="px-2 py-1 rounded bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/30 text-2xs text-cyan-200 flex items-center gap-1"
                        >
                            <Compass size={10} /> Go
                        </button>
                    </form>
                </div>

                {/* Live Statekeeper World State Snapshot */}
                <div className="space-y-2">
                    <div className="text-2xs font-bold uppercase tracking-wider text-gray-400 flex items-center justify-between">
                        <span>Live State Snapshot (Statekeeper)</span>
                    </div>

                    <ContextField
                        inline
                        showLabel
                        label="Expression"
                        value={snap.character_expression}
                        placeholder="e.g. neutral, happy, blushing, sad, angry, surprised, seductive"
                        locked={isLocked('character_expression')}
                        onToggleLock={() => toggleLock('character_expression')}
                        onSave={(val) => handleFieldSave('character_expression', val || '')}
                    />

                    <ContextField
                        inline
                        showLabel
                        label="Mood"
                        value={snap.character_mood}
                        placeholder="e.g. Curious, Guarded"
                        locked={isLocked('character_mood')}
                        onToggleLock={() => toggleLock('character_mood')}
                        onSave={(val) => handleFieldSave('character_mood', val || '')}
                    />
                    <ContextField
                        inline
                        showLabel
                        label="Activity"
                        value={snap.current_activity}
                        placeholder="e.g. Examining the artifact"
                        locked={isLocked('current_activity')}
                        onToggleLock={() => toggleLock('current_activity')}
                        onSave={(val) => handleFieldSave('current_activity', val || '')}
                    />
                    <ContextField
                        inline
                        showLabel
                        label="Outfit"
                        value={snap.character_outfit}
                        placeholder="e.g. Traveling cloak"
                        locked={isLocked('character_outfit')}
                        onToggleLock={() => toggleLock('character_outfit')}
                        onSave={(val) => handleFieldSave('character_outfit', val || '')}
                    />
                    <ContextField
                        inline
                        showLabel
                        label="Physical State"
                        value={snap.physical_condition}
                        placeholder="e.g. Uninjured, fatigued, wounded left shoulder"
                        locked={isLocked('physical_condition')}
                        onToggleLock={() => toggleLock('physical_condition')}
                        onSave={(val) => handleFieldSave('physical_condition', val || '')}
                    />
                    <ContextField
                        inline
                        showLabel
                        label="Weather"
                        value={snap.weather}
                        placeholder="e.g. Torrential rain, clear night sky, dense fog"
                        locked={isLocked('weather')}
                        onToggleLock={() => toggleLock('weather')}
                        onSave={(val) => handleFieldSave('weather', val || '')}
                    />

                    {/* Wardrobe Presets & Reverse Vision Image-to-State */}
                    <div className="bg-black/20 rounded-lg p-2 border border-white/5 space-y-1.5">
                        <div className="flex items-center justify-between gap-1">
                            <span className="text-2xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1">
                                <Shirt size={10} className="text-pink-400" /> Wardrobe Presets
                            </span>
                            <button
                                type="button"
                                onClick={() =>
                                    reverseVision.mutate(
                                        { chatId: chat.id },
                                        { onSuccess: () => flashFeedback('Synced outfit & mood from latest image') }
                                    )
                                }
                                disabled={reverseVision.isPending}
                                className="px-1.5 py-0.5 rounded bg-pink-500/15 hover:bg-pink-500/25 border border-pink-500/30 text-pink-300 text-2xs flex items-center gap-1"
                                title="Reverse Vision: inspect the latest image/avatar to update Outfit, Mood, and Location"
                            >
                                {reverseVision.isPending ? <Loader2 size={9} className="animate-spin" /> : <Eye size={9} />}
                                Sync from Image
                            </button>
                        </div>
                        {wardrobeList.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                                {wardrobeList.map((preset, idx) => (
                                    <button
                                        key={`${preset.name || idx}`}
                                        type="button"
                                        onClick={() => handleSelectWardrobePreset(preset)}
                                        className={clsx(
                                            "px-2 py-0.5 rounded text-2xs border transition-colors",
                                            snap.character_outfit === (preset.outfit || preset.description)
                                                ? "bg-pink-500/25 border-pink-400/50 text-pink-200 font-semibold"
                                                : "bg-gray-800/60 border-white/10 text-gray-300 hover:border-pink-500/40"
                                        )}
                                        title={preset.outfit || preset.description}
                                    >
                                        {preset.name || `Outfit ${idx + 1}`}
                                    </button>
                                ))}
                            </div>
                        )}
                        <form onSubmit={handleSaveWardrobePreset} className="flex gap-1">
                            <input
                                type="text"
                                value={wardrobeNameInput}
                                onChange={(e) => setWardrobeNameInput(e.target.value)}
                                placeholder="Save current outfit as preset..."
                                className="flex-1 bg-gray-800/60 border border-white/5 rounded px-2 py-1 text-2xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-pink-500/40"
                            />
                            <button
                                type="submit"
                                className="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-2xs text-gray-300"
                            >
                                Save
                            </button>
                        </form>
                    </div>

                    <ContextField
                        inline
                        showLabel
                        label="Relationship"
                        value={snap.relationship_status || snap.relationship}
                        placeholder="e.g. Cautious allies (+1 trust)"
                        locked={isLocked('relationship_status')}
                        onToggleLock={() => toggleLock('relationship_status')}
                        onSave={(val) => handleFieldSave('relationship_status', val || '')}
                    />

                    {/* Multi-Target Relationship Network */}
                    <div className="bg-black/20 rounded-lg p-2 border border-white/5 space-y-1.5">
                        <div className="text-2xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1">
                            <Users size={10} className="text-rose-400" /> Multi-Target Relationships ({relationshipsList.length})
                        </div>
                        <div className="space-y-1">
                            {relationshipsList.map((rel, idx) => (
                                <div key={`${rel.target_name}-${idx}`} className="flex items-center gap-1 bg-gray-900/60 rounded px-2 py-1 border border-white/5">
                                    <span className={clsx(
                                        "px-1 py-0.5 rounded text-2xs font-bold uppercase shrink-0",
                                        rel.target_type === 'user' ? "bg-sky-500/20 text-sky-300" : "bg-purple-500/20 text-purple-300"
                                    )}>
                                        {rel.target_name}
                                    </span>
                                    <input
                                        type="text"
                                        value={rel.status || ''}
                                        onChange={(e) => handleUpdateRelationship(idx, { status: e.target.value })}
                                        className="flex-1 min-w-0 bg-transparent text-2xs text-gray-200 focus:outline-none border-b border-transparent focus:border-rose-500/40 px-1"
                                        placeholder="Bond / stance..."
                                    />
                                    <select
                                        value={rel.affinity || 'neutral'}
                                        onChange={(e) => handleUpdateRelationship(idx, { affinity: e.target.value })}
                                        className="bg-gray-800 border border-white/10 rounded px-1 py-0.5 text-2xs text-gray-300"
                                    >
                                        <option value="devoted">Devoted</option>
                                        <option value="trusted">Trusted</option>
                                        <option value="friendly">Friendly</option>
                                        <option value="curious">Curious</option>
                                        <option value="neutral">Neutral</option>
                                        <option value="wary">Wary</option>
                                        <option value="tense">Tense</option>
                                        <option value="hostile">Hostile</option>
                                    </select>
                                    <button
                                        type="button"
                                        onClick={() => handleRemoveRelationship(idx)}
                                        className="text-gray-500 hover:text-red-400 px-0.5"
                                        title="Remove relationship target"
                                    >
                                        ×
                                    </button>
                                </div>
                            ))}
                        </div>
                        <form onSubmit={handleAddRelationship} className="grid grid-cols-12 gap-1 pt-0.5">
                            <select
                                value={newRelType}
                                onChange={(e) => setNewRelType(e.target.value)}
                                className="col-span-3 bg-gray-800/70 border border-white/10 rounded px-1 py-1 text-2xs text-gray-300"
                            >
                                <option value="character">NPC</option>
                                <option value="user">User</option>
                            </select>
                            <input
                                type="text"
                                value={newRelTarget}
                                onChange={(e) => setNewRelTarget(e.target.value)}
                                placeholder="Target name"
                                className="col-span-4 bg-gray-800/60 border border-white/5 rounded px-1.5 py-1 text-2xs text-gray-200 placeholder-gray-600"
                            />
                            <input
                                type="text"
                                value={newRelStatus}
                                onChange={(e) => setNewRelStatus(e.target.value)}
                                placeholder="Stance..."
                                className="col-span-3 bg-gray-800/60 border border-white/5 rounded px-1.5 py-1 text-2xs text-gray-200 placeholder-gray-600"
                            />
                            <button
                                type="submit"
                                className="col-span-2 rounded bg-white/5 hover:bg-white/10 text-2xs text-gray-300"
                            >
                                +
                            </button>
                        </form>
                    </div>

                    {/* Character & User Skillsets */}
                    <div className="grid grid-cols-1 gap-2 pt-1">
                        <div>
                            <div className="text-2xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
                                Character Skillset (Fate Check Advantage)
                            </div>
                            <div className="flex flex-wrap gap-1 mb-1">
                                {charSkills.length === 0 ? (
                                    <span className="text-2xs text-gray-600 italic">No character skills listed</span>
                                ) : (
                                    charSkills.map((skill, index) => (
                                        <span
                                            key={`${skill}-${index}`}
                                            className="px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-2xs flex items-center gap-1"
                                        >
                                            <span>{skill}</span>
                                            <button
                                                type="button"
                                                onClick={() => handleRemoveSkill('character_skills', charSkills, skill)}
                                                className="text-emerald-400 hover:text-white ml-0.5"
                                            >
                                                ×
                                            </button>
                                        </span>
                                    ))
                                )}
                            </div>
                            <form
                                onSubmit={(e) => handleAddSkill(e, 'character_skills', charSkills, charSkillInput, setCharSkillInput)}
                                className="flex gap-1"
                            >
                                <input
                                    type="text"
                                    value={charSkillInput}
                                    onChange={(e) => setCharSkillInput(e.target.value)}
                                    placeholder="Add character skill (e.g. Swordplay, Netrunning)..."
                                    className="flex-1 bg-gray-800/60 border border-white/5 rounded px-2 py-1 text-2xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-emerald-500/40"
                                />
                                <button type="submit" className="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-2xs text-gray-300">
                                    Add
                                </button>
                            </form>
                        </div>

                        <div>
                            <div className="text-2xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
                                User / Persona Skillset
                            </div>
                            <div className="flex flex-wrap gap-1 mb-1">
                                {userSkills.length === 0 ? (
                                    <span className="text-2xs text-gray-600 italic">No user skills listed</span>
                                ) : (
                                    userSkills.map((skill, index) => (
                                        <span
                                            key={`${skill}-${index}`}
                                            className="px-2 py-0.5 rounded-full bg-sky-500/15 border border-sky-500/30 text-sky-300 text-2xs flex items-center gap-1"
                                        >
                                            <span>{skill}</span>
                                            <button
                                                type="button"
                                                onClick={() => handleRemoveSkill('user_skills', userSkills, skill)}
                                                className="text-sky-400 hover:text-white ml-0.5"
                                            >
                                                ×
                                            </button>
                                        </span>
                                    ))
                                )}
                            </div>
                            <form
                                onSubmit={(e) => handleAddSkill(e, 'user_skills', userSkills, userSkillInput, setUserSkillInput)}
                                className="flex gap-1"
                            >
                                <input
                                    type="text"
                                    value={userSkillInput}
                                    onChange={(e) => setUserSkillInput(e.target.value)}
                                    placeholder="Add user skill (e.g. Persuasion, Tactics)..."
                                    className="flex-1 bg-gray-800/60 border border-white/5 rounded px-2 py-1 text-2xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-sky-500/40"
                                />
                                <button type="submit" className="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-2xs text-gray-300">
                                    Add
                                </button>
                            </form>
                        </div>
                    </div>

                    {/* Inventory Pills with 1-Click Item Visualizer */}
                    <div className="pt-1">
                        <div className="text-2xs font-semibold text-gray-500 uppercase tracking-wider mb-1 flex items-center justify-between">
                            <span>Active Inventory / Key Items</span>
                            <button
                                type="button"
                                onClick={() => toggleLock('inventory')}
                                className={clsx(
                                    "p-0.5 rounded transition-colors text-2xs flex items-center gap-1",
                                    isLocked('inventory') ? "text-amber-400 bg-amber-500/15" : "text-gray-500 hover:text-gray-300"
                                )}
                                title={isLocked('inventory') ? "Locked: Protected from AI & Laya overwrites" : "Unlocked: Can be updated by Statekeeper"}
                            >
                                {isLocked('inventory') ? <Lock size={11} className="text-amber-400" /> : <Unlock size={11} />}
                                {isLocked('inventory') && <span className="text-2xs font-mono font-bold text-amber-400">LOCK</span>}
                            </button>
                        </div>
                        <div className="flex flex-wrap gap-1 mb-1.5">
                            {inventoryList.length === 0 ? (
                                <span className="text-2xs text-gray-600 italic">No tracked items yet</span>
                            ) : (
                                inventoryList.map((item, index) => (
                                    <span
                                        key={`${item}-${index}`}
                                        className="px-2 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-2xs flex items-center gap-1"
                                    >
                                        <span>{item}</span>
                                        {chat.allow_image_generation !== false && (
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    visualizeItem.mutate(
                                                        { chatId: chat.id, itemName: item },
                                                        { onSuccess: () => flashFeedback(`Generating illustration for "${item}"...`) }
                                                    )
                                                }
                                                disabled={visualizeItem.isPending}
                                                className="text-indigo-300 hover:text-amber-300 ml-0.5"
                                                title={`1-Click Visualize "${item}" in ComfyUI`}
                                            >
                                                <ImageIcon size={10} />
                                            </button>
                                        )}
                                        <button
                                            type="button"
                                            onClick={() => handleRemoveInventory(item)}
                                            className="text-indigo-400 hover:text-white ml-0.5"
                                            title={`Remove ${item}`}
                                        >
                                            ×
                                        </button>
                                    </span>
                                ))
                            )}
                        </div>
                        <form onSubmit={handleAddInventory} className="flex gap-1">
                            <input
                                type="text"
                                value={inventoryInput}
                                onChange={(e) => setInventoryInput(e.target.value)}
                                placeholder="Add item..."
                                className="flex-1 bg-gray-800/60 border border-white/5 rounded px-2 py-1 text-2xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-emerald-500/40"
                            />
                            <button
                                type="submit"
                                className="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-2xs text-gray-300"
                            >
                                Add
                            </button>
                        </form>
                    </div>

                    <ContextField
                        inline
                        showLabel
                        label="Quests & Goals"
                        value={snap.quests_and_goals}
                        placeholder="e.g. Find the missing key, reach the mountain pass"
                        locked={isLocked('quests_and_goals')}
                        onToggleLock={() => toggleLock('quests_and_goals')}
                        onSave={(val) => handleFieldSave('quests_and_goals', val || '')}
                    />
                    <ContextField
                        inline
                        showLabel
                        label="Social Status"
                        value={snap.social_status}
                        placeholder="e.g. Respected investigator, wanted fugitive"
                        locked={isLocked('social_status')}
                        onToggleLock={() => toggleLock('social_status')}
                        onSave={(val) => handleFieldSave('social_status', val || '')}
                    />
                </div>

                {/* World Vault Canon & Living World Actions */}
                <div className="pt-2 border-t border-white/5 flex flex-wrap gap-1.5">
                    <button
                        type="button"
                        onClick={() =>
                            commitCanon.mutate(chat.id, {
                                onSuccess: (res) => flashFeedback(`Committed to "${res.world_name}" Canon`),
                            })
                        }
                        disabled={commitCanon.isPending}
                        className="px-2 py-1 rounded bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 text-2xs font-semibold flex items-center gap-1"
                        title="Promote this chat's timeline, locations, and relationships to the World Vault Canon Lorebook & Graph"
                    >
                        <BookOpen size={10} /> Commit to Canon
                    </button>
                    <button
                        type="button"
                        onClick={() =>
                            compileStory.mutate(
                                { chatId: chat.id, title: chat.name },
                                {
                                    onSuccess: (res) => {
                                        flashFeedback(`Compiled Story "${res.title}"`);
                                        if (res.story_id) navigate(`/story/${res.story_id}`);
                                    },
                                }
                            )
                        }
                        disabled={compileStory.isPending}
                        className="px-2 py-1 rounded bg-indigo-500/15 hover:bg-indigo-500/25 border border-indigo-500/30 text-indigo-300 text-2xs font-semibold flex items-center gap-1"
                        title="Novelize and compile this chat session into an interactive Story Sandbox chapter"
                    >
                        <NotebookPen size={10} /> Compile Chapter
                    </button>
                    {chat.world_id && (
                        <button
                            type="button"
                            onClick={() =>
                                runWorldTick.mutate(
                                    { worldId: chat.world_id, timeAdvanceLabel: '+1 Day', activeChatId: chat.id },
                                    { onSuccess: () => flashFeedback('Advanced Living World Clock (+1 Day)') }
                                )
                            }
                            disabled={runWorldTick.isPending}
                            className="px-2 py-1 rounded bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/30 text-cyan-300 text-2xs font-semibold flex items-center gap-1"
                            title="Advance the World Clock by +1 Day and simulate off-screen NPC activities"
                        >
                            <Calendar size={10} /> +1 Day Tick
                        </button>
                    )}
                </div>

                {/* Last Statekeeper Action Card */}
                {snap.last_updater_result ? (
                    <div className="p-2 rounded-lg bg-purple-950/20 border border-purple-500/25 space-y-1 text-2xs">
                        <div className="flex items-center justify-between">
                            <span className="font-bold text-purple-300 flex items-center gap-1">
                                <Brain size={11} className="text-purple-400" />
                                Last Statekeeper Action
                            </span>
                            <span className="text-3xs text-gray-400 font-mono">
                                {parseGalleryDate(snap.last_updater_result.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                        </div>
                        <div className="text-gray-300 text-3xs italic">
                            &ldquo;{snap.last_updater_result.summary}&rdquo;
                        </div>
                        {snap.last_updater_result.applied_fields?.length > 0 && (
                            <div className="flex flex-wrap gap-1 pt-0.5">
                                {snap.last_updater_result.applied_fields.map((f, index) => (
                                    <span key={`${f}-${index}`} className="px-1.5 py-0.2 rounded bg-purple-500/15 text-purple-300 font-mono text-3xs border border-purple-500/25">
                                        {f.replace(/_/g, ' ')}
                                    </span>
                                ))}
                            </div>
                        )}
                    </div>
                ) : lastDecision?.updater_evaluation?.diagnostic_summary ? (
                    <div className="p-2 rounded-lg bg-gray-900/60 border border-white/5 space-y-1 text-2xs">
                        <div className="flex items-center justify-between text-gray-400 font-semibold">
                            <span className="flex items-center gap-1">
                                <Shield size={11} className="text-gray-400" />
                                Statekeeper Status
                            </span>
                            <span className={clsx("px-1.5 py-0.2 rounded text-3xs font-mono font-bold", lastDecision.should_run_updater ? "bg-purple-500/20 text-purple-300" : "bg-gray-800 text-gray-500")}>
                                {lastDecision.should_run_updater ? "ACTIVE" : "IDLE"}
                            </span>
                        </div>
                        <div className="text-gray-400 text-3xs">
                            {lastDecision.updater_evaluation.diagnostic_summary}
                        </div>
                    </div>
                ) : null}

                {/* Last System 1 Decision Breakdown */}
                {lastDecision && (
                    <div className="pt-2 border-t border-white/5 space-y-1.5">
                        <div className="flex items-center justify-between text-2xs">
                            <span className="text-gray-400 uppercase tracking-wider font-bold">
                                Last System 1 Decision
                            </span>
                            <span className={clsx("font-mono", engineInfo.tone)} title={engineInfo.level === 'live' ? undefined : "Laya's director pass fell back — variant routing and picky answers come from the lower tier."}>
                                {engineInfo.label} · {lastDecision.latency_ms}ms
                            </span>
                        </div>
                        <div className="flex flex-wrap gap-1 text-2xs">
                            <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/25">
                                Next: {lastDecision.next_speaker}
                            </span>
                            <span className="px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300 border border-blue-500/25">
                                Speed: {lastDecision.pacing_speed_label || `${lastDecision.pacing_speed}/3`}
                            </span>
                            {lastDecision.should_run_updater && (
                                <span className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 font-semibold">
                                    Statekeeper Triggered
                                </span>
                            )}
                            {engineInfo.level !== 'live' && (
                                <span
                                    className={clsx("px-1.5 py-0.5 rounded border font-semibold", engineInfo.chip)}
                                    title="Laya's director model could not answer; the decision came from a lower tier."
                                >
                                    Director: {engineInfo.level}
                                </span>
                            )}
                        </div>
                        {lastDecision.updater_gates && (
                            <div className="grid grid-cols-2 gap-1.5 pt-1">
                                {[
                                    ['Location & Time', lastDecision.updater_gates.gate_world_state],
                                    ['Tone & Atmosphere', lastDecision.updater_gates.gate_scene_tone],
                                    ['Char State & Attire', lastDecision.updater_gates.gate_character_state],
                                    ['Character Mood', lastDecision.updater_gates.gate_character_mood],
                                    ['Relationship Dynamic', lastDecision.updater_gates.gate_relationship_dynamic],
                                    ['Inventory & Items', lastDecision.updater_gates.gate_inventory_or_items],
                                    ['Durable Memory', lastDecision.updater_gates.gate_durable_memory],
                                    ['Lore Discovery', lastDecision.updater_gates.gate_lore_discovery],
                                ].map(([lbl, prob]) => {
                                    const pct = Math.round((prob || 0) * 100);
                                    const threshold = Math.round((lastDecision.updater_evaluation?.activation_threshold || 0.55) * 100);
                                    const fired = pct >= threshold;
                                    return (
                                        <div key={lbl} className="flex items-center justify-between bg-black/25 px-2 py-0.5 rounded text-2xs">
                                            <span className={fired ? "text-purple-300 font-semibold" : "text-gray-500"}>{lbl}</span>
                                            <span className={clsx("font-mono", fired ? "text-purple-300 font-bold" : "text-gray-500")}>{pct}%</span>
                                        </div>
                                    );
                                })}
                            </div>
                        )}

                        {/* Expandable Decision Questions Trace */}
                        {lastDecision.questions_evaluated?.length > 0 && (
                            <div className="pt-1.5">
                                <button
                                    type="button"
                                    onClick={() => setShowDecisionInspector(v => !v)}
                                    className="w-full flex items-center justify-between px-2 py-1 rounded bg-gray-800/60 hover:bg-gray-800 text-gray-300 text-3xs font-medium border border-white/5 transition-colors"
                                >
                                    <span className="flex items-center gap-1">
                                        <Layers size={10} className="text-emerald-400" />
                                        <span>Inspect {lastDecision.questions_evaluated.length} Questions &amp; Rubrics</span>
                                    </span>
                                    <span>{showDecisionInspector ? 'Hide' : 'Show'}</span>
                                </button>
                                {showDecisionInspector && (
                                    <div className="mt-1.5 max-h-56 overflow-y-auto space-y-1 p-1.5 rounded bg-black/40 border border-white/5 text-3xs scrollbar-thin scrollbar-thumb-gray-800">
                                        {lastDecision.questions_evaluated.map((q) => (
                                            <div key={q.key} className="p-1.5 rounded bg-gray-900/90 border border-white/5 space-y-0.5">
                                                <div className="flex items-center justify-between gap-1">
                                                    <span className="font-semibold text-gray-200 truncate">{q.prompt}</span>
                                                    <span className={clsx(
                                                        "px-1 py-0.2 rounded font-mono text-3xs shrink-0 font-bold",
                                                        q.status?.includes('FIRED') || q.status?.includes('Triggered')
                                                            ? "bg-purple-500/25 text-purple-300"
                                                            : "bg-gray-800 text-gray-400"
                                                    )}>
                                                        {q.status}
                                                    </span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </details>
    );
}

export default ChatContextPanel;
