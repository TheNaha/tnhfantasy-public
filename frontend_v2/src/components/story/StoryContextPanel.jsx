import React, { useMemo } from 'react';
import { ImageIcon, X, Layers, Check, Settings, Book, Calendar, Tag, PenTool, Edit2, Plus, MapPin, Eye, Target, Sparkles } from 'lucide-react';
import clsx from 'clsx';
import { assetUrl } from '../../utils/assetUrl';
import SamplingControls from '../common/SamplingControls';
import EntityContextInspector from '../workspace/EntityContextInspector';
import WorldLinkRow from '../workspace/WorldLinkRow';
import StoryOutlinePanel from './StoryOutlinePanel';

export default React.memo(function StoryContextPanel({
    activeStory,
    activeChapter,
    characters,
    lorebooks,
    locations,
    worlds = [],
    scenarios = [],
    storyImages,
    chapters,
    llmModels,
    defaultLlmConfig,
    onClose,
    onShowGallery,
    onUpdateStory,
    onEditCharacter,
    onEditLorebook,
    onEditLocation,
    onOpenRevisions,
    onSnapshotChapter,
    isSnapshotting
}) {
    const lorebookContextText = useMemo(
        () => [activeStory?.memory, activeChapter?.content].filter(Boolean).join('\n'),
        [activeStory?.memory, activeChapter?.content]
    );

    return (
        <>
            <div className="lg:hidden absolute top-3 right-4 z-50">
                <button onClick={onClose} className="p-2 bg-gray-800 rounded-full text-white">
                    <X size={16} />
                </button>
            </div>
            <div className="h-16 border-b border-white/5 flex items-center px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                <h3 className="font-semibold text-gray-200 flex items-center gap-2">
                    <ImageIcon size={16} className="text-indigo-400" />
                    Story Context
                </h3>
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
                <EntityContextInspector
                    title="Entity Inspector"
                    subtitle="What this story currently feeds the model"
                    characters={characters}
                    characterIds={activeStory?.character_ids || []}
                    lorebooks={lorebooks}
                characterLorebookLinks={characters.flatMap(c => (c.lorebook_ids || []).map(lorebookId => ({ lorebookId, characterName: c.name })))}
                    lorebookIds={activeStory?.lorebook_ids || []}
                    locations={locations}
                    locationIds={activeStory?.location_ids || []}
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
                    worldId={activeStory?.world_id}
                    worlds={worlds}
                    onChange={(next) => onUpdateStory({ world_id: next })}
                />

                {/* `Story.scenario_id` is written by Scenarios → Apply and was
                    read by nothing in the UI, so a scenario applied to a story
                    was a write into a void the user could not see or undo. It
                    is not a void server-side — `stories.py` injects the
                    scenario's `prompt_template` into every continuation — which
                    is exactly why it needed a row: the user has to be able to
                    see it and take it off. */}
                <div className="glass-panel p-4 rounded-xl border border-white/5" data-testid="story-scenario-row">
                    <div className="flex items-center justify-between gap-2 mb-3">
                        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 min-w-0">
                            <Sparkles size={12} className="text-purple-400 shrink-0" /> Scenario
                        </h4>
                        {scenarios.length > 0 ? (
                            <select
                                aria-label="Scenario"
                                data-testid="story-scenario-select"
                                value={activeStory?.scenario_id || ''}
                                onChange={(e) => onUpdateStory({ scenario_id: e.target.value || null })}
                                className={clsx(
                                    'bg-gray-800 border text-xs rounded px-2 py-1 text-gray-300 focus:outline-none min-w-0 truncate max-w-[60%]',
                                    activeStory?.scenario_id ? 'border-purple-500/30' : 'border-gray-700'
                                )}
                            >
                                <option value="">No scenario</option>
                                {scenarios.map(s => (
                                    <option key={s.id} value={s.id}>{s.name}</option>
                                ))}
                            </select>
                        ) : null}
                    </div>
                    {(() => {
                        const applied = scenarios.find(s => s.id === activeStory?.scenario_id);
                        if (!activeStory?.scenario_id) {
                            return (
                                <p className="text-xs text-gray-500">
                                    {scenarios.length === 0
                                        ? 'No scenarios yet. A scenario supplies the prompt template used for every continuation.'
                                        : "A scenario's prompt template is injected into every continuation. Applied ones show here."}
                                </p>
                            );
                        }
                        return (
                            <div className="space-y-1.5">
                                <p className="text-xs text-purple-300">
                                    Injected into every continuation of this story.
                                </p>
                                {applied?.description && (
                                    <p className="text-xs text-gray-400 leading-relaxed line-clamp-2">{applied.description}</p>
                                )}
                                {!applied && (
                                    <p className="text-2xs text-gray-500">
                                        Applied scenario <code className="text-gray-600">{activeStory.scenario_id.slice(0, 8)}</code> is no longer in the library.
                                    </p>
                                )}
                            </div>
                        );
                    })()}
                </div>

                <StoryOutlinePanel
                    storyId={activeStory?.id}
                    chapters={chapters}
                    activeChapterId={activeChapter?.id}
                    wordCountGoal={activeStory?.word_count_goal}
                    onOpenRevisions={onOpenRevisions}
                    onSnapshot={onSnapshotChapter}
                    isSnapshotting={isSnapshotting}
                />

                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                        <Layers size={14} /> Characters
                    </h4>
                    {characters.length === 0 ? (
                        <p className="text-sm text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">No characters</p>
                    ) : (
                        <div className="space-y-2">
                            {characters.map(char => {
                                const isActive = (activeStory?.character_ids || []).includes(char.id);
                                return (
                                    <div key={char.id} className={clsx(
                                        "w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors group",
                                        isActive ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30" : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                    )}>
                                        <button
                                            onClick={() => {
                                                const current = activeStory?.character_ids || [];
                                                const newIds = isActive ? current.filter(id => id !== char.id) : [...current, char.id];
                                                onUpdateStory({ character_ids: newIds });
                                            }}
                                            className="flex-1 text-left flex items-center gap-2 min-w-0"
                                        >
                                            {isActive ? <Check size={14} className="text-indigo-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}
                                            <div className="min-w-0">
                                                <p className="truncate font-medium">{char.name}</p>
                                            </div>
                                        </button>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onEditCharacter?.(char);
                                            }}
                                            className="p-1 rounded text-gray-500 hover:text-indigo-400 hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity"
                                            title="Edit Character"
                                        >
                                            <Edit2 size={12} />
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <div className="flex items-center justify-between mb-3">
                        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                            <Layers size={14} /> Lorebooks
                        </h4>
                        <button
                            onClick={() => onEditLorebook?.(null)}
                            className="p-1 rounded text-gray-500 hover:text-indigo-400 hover:bg-white/10 transition-colors"
                            title="New Lorebook"
                        >
                            <Plus size={14} />
                        </button>
                    </div>
                    {lorebooks.length === 0 ? (
                        <p className="text-sm text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">No lorebooks</p>
                    ) : (
                        <div className="space-y-2">
                            {lorebooks.map(lb => {
                                const isActive = (activeStory?.lorebook_ids || []).includes(lb.id);
                                return (
                                    <div key={lb.id} className={clsx(
                                        "w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors group",
                                        isActive ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30" : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                    )}>
                                        <button
                                            onClick={() => {
                                                const current = activeStory?.lorebook_ids || [];
                                                const newIds = isActive ? current.filter(id => id !== lb.id) : [...current, lb.id];
                                                onUpdateStory({ lorebook_ids: newIds });
                                            }}
                                            className="flex-1 text-left flex items-center gap-2 min-w-0"
                                        >
                                            {isActive ? <Check size={14} className="text-indigo-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}
                                            <div className="min-w-0">
                                                <p className="truncate font-medium">{lb.name}</p>
                                                {lb.description && <p className="text-xs text-gray-500 truncate">{lb.description}</p>}
                                            </div>
                                        </button>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onEditLorebook?.(lb);
                                            }}
                                            className="p-1 rounded text-gray-500 hover:text-indigo-400 hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity"
                                            title="Edit Lorebook"
                                        >
                                            <Edit2 size={12} />
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <div className="flex items-center justify-between mb-3">
                        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                            <MapPin size={14} className="text-emerald-400" /> Locations
                        </h4>
                        <button
                            onClick={() => onEditLocation?.(null)}
                            className="p-1 rounded text-gray-500 hover:text-emerald-400 hover:bg-white/10 transition-colors"
                            title="New Location"
                        >
                            <Plus size={14} />
                        </button>
                    </div>
                    {locations.length === 0 ? (
                        <p className="text-sm text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">No locations</p>
                    ) : (
                        <div className="space-y-2">
                            {locations.map(loc => {
                                const isActive = (activeStory?.location_ids || []).includes(loc.id);
                                return (
                                    <div key={loc.id} className={clsx(
                                        "w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors group",
                                        isActive ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30" : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                    )}>
                                        <button
                                            onClick={() => {
                                                const current = activeStory?.location_ids || [];
                                                const newIds = isActive ? current.filter(id => id !== loc.id) : [...current, loc.id];
                                                onUpdateStory({ location_ids: newIds });
                                            }}
                                            className="flex-1 text-left flex items-center gap-2 min-w-0"
                                        >
                                            {isActive ? <Check size={14} className="text-emerald-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}
                                            <div className="min-w-0">
                                                <p className="truncate font-medium">{loc.name}</p>
                                                {loc.description && <p className="text-xs text-gray-500 truncate">{loc.description}</p>}
                                            </div>
                                        </button>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onEditLocation?.(loc);
                                            }}
                                            className="p-1 rounded text-gray-500 hover:text-emerald-400 hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity"
                                            title="Edit Location"
                                        >
                                            <Edit2 size={12} />
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <div className="flex items-center justify-between mb-3">
                        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                            <ImageIcon size={14} /> Chapter Images
                        </h4>
                        <button
                            onClick={onShowGallery}
                            className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
                        >
                            View all ({storyImages.length})
                        </button>
                    </div>
                    {activeChapter?.image_paths?.length > 0 ? (
                        <div className="space-y-2">
                            {activeChapter.image_paths.map((path, idx) => (
                                <div key={idx} className="rounded-lg overflow-hidden border border-white/10">
                                    <img src={assetUrl(path)} alt={`Scene ${idx + 1}`} loading="lazy" decoding="async" className="w-full h-auto" />
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="h-32 border border-dashed border-gray-700 rounded-xl flex flex-col items-center justify-center text-gray-500 gap-2">
                            <ImageIcon size={24} className="opacity-50" />
                            <p className="text-xs">No illustrations yet</p>
                        </div>
                    )}
                </div>
                 <div className="bg-gray-800/50 p-4 rounded-xl border border-gray-700/50 space-y-4">
                     <div className="flex items-center gap-2 mb-2">
                         <Settings size={16} className="text-gray-400" />
                         <h3 className="font-semibold text-gray-200">AI Model Settings</h3>
                     </div>
                     <div>
                         <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider block mb-2">Text Model</label>
                         <select
                             className="w-full bg-gray-900 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-indigo-500/50"
                             value={activeStory?.llm_model || 'default'}
                             onChange={(e) => {
                                 onUpdateStory({ llm_model: e.target.value === 'default' ? null : e.target.value });
                             }}
                         >
                             <option value="default">Provider Default ({defaultLlmConfig?.model_id || 'default'})</option>
                             {llmModels.map(m => (
                                 <option key={m.id} value={m.id}>{m.name || m.id}</option>
                             ))}
                         </select>
                         <p className="text-xs text-gray-500 mt-1">Per-story model override; used for continuations and titles.</p>
                     </div>
                     <SamplingControls values={activeStory || {}} onChange={onUpdateStory} />
                      <div>
                          <div className="flex items-center justify-between mb-1.5">
                              <p className="text-xs text-gray-300 font-medium">Autonomous Illustration</p>
                              <span className="text-xs text-gray-500 font-mono">
                                  {activeStory?.max_agentic_depth != null
                                      ? (activeStory.max_agentic_depth > 0
                                          ? `${activeStory.max_agentic_depth} image${activeStory.max_agentic_depth === 1 ? '' : 's'} max`
                                          : 'Off')
                                      : 'Global default (5)'}
                              </span>
                          </div>
                          <input
                              type="range"
                              min="0"
                              max="10"
                              step="1"
                              value={activeStory?.max_agentic_depth ?? 5}
                              onChange={(e) => onUpdateStory({ max_agentic_depth: parseInt(e.target.value) })}
                              className="w-full accent-purple-500"
                              title="How many images the AI may generate on its own while continuing the story. 0 disables autonomous illustration."
                          />
                          <div className="flex justify-between text-2xs text-gray-600 mt-0.5">
                              <span>Off</span><span>5</span><span>10</span>
                          </div>
                          <p className="text-xs text-gray-500 mt-1">While continuing the story, the AI can illustrate scenes itself; generated art attaches to this chapter.</p>
                          {activeStory?.max_agentic_depth != null && (
                              <button
                                  onClick={() => onUpdateStory({ max_agentic_depth: null })}
                                  className="mt-1 text-2xs text-gray-500 hover:text-red-400 transition-colors"
                              >
                                  Reset to global default
                              </button>
                          )}
                      </div>
                 </div>
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                        <Book size={14} /> Story Info
                    </h4>
                    <div className="space-y-3 text-xs text-gray-400">
                        <p>Chapters: {chapters?.length || 0}</p>
                        <div className="flex items-center justify-between gap-2">
                            <p>Status: {activeStory?.is_archived ? 'Archived' : 'Active'}</p>
                            <button
                                onClick={() => onUpdateStory({ is_archived: !activeStory?.is_archived })}
                                disabled={!activeStory}
                                className={clsx(
                                    "text-2xs font-medium px-1.5 py-0.5 rounded transition-colors",
                                    activeStory?.is_archived
                                        ? "bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                                        : "bg-amber-500/10 text-amber-300 hover:bg-amber-500/20"
                                )}
                                title={activeStory?.is_archived ? 'Restore this story to Active' : 'Archive this story'}
                            >
                                {activeStory?.is_archived ? 'Unarchive' : 'Archive'}
                            </button>
                        </div>
                        {activeStory?.created_at && (
                            <p className="flex items-center gap-1">
                                <Calendar size={10} className="text-gray-600" />
                                Created: {new Date(activeStory.created_at).toLocaleDateString()}
                            </p>
                        )}
                    </div>
                </div>

                {/* Genre */}
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                        <Tag size={12} className="text-purple-400" /> Genre
                    </label>
                    <input
                        key={`story-genre-${activeStory?.id || 'none'}`}
                        type="text"
                        defaultValue={activeStory?.genre || ''}
                        onBlur={(e) => {
                            const value = e.target.value.trim() || null;
                            if (value !== (activeStory?.genre || null)) {
                                onUpdateStory({ genre: value });
                            }
                        }}
                        placeholder="e.g. Fantasy, Cyberpunk, Horror"
                        className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/50 transition-colors"
                    />
                    <p className="text-xs text-gray-500 mt-1">Steer story continuation tone/style.</p>
                </div>

                {/* Writing preferences */}
                <div className="glass-panel p-4 rounded-xl border border-white/5 space-y-3">
                    <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
                        <Eye size={12} className="text-sky-400" /> Writing Preferences
                    </label>
                    <div>
                        <label className="block text-xs text-gray-500 mb-1">Narration perspective</label>
                        <select
                            value={activeStory?.pov || ''}
                            onChange={(e) => {
                                onUpdateStory({ pov: e.target.value || null });
                            }}
                            className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-purple-500/50 transition-colors"
                        >
                            <option value="">Story default</option>
                            <option value="first">First person (I)</option>
                            <option value="second">Second person (You)</option>
                            <option value="third">Third person (He/She/They)</option>
                        </select>
                    </div>
                    <div>
                        <label className="block text-xs text-gray-500 mb-1">Word count goal (optional)</label>
                        <input
                            key={`story-word-count-${activeStory?.id || 'none'}`}
                            type="number"
                            min="0"
                            defaultValue={activeStory?.word_count_goal ?? ''}
                            onBlur={(e) => {
                                const value = parseInt(e.target.value, 10);
                                const nextValue = Number.isFinite(value) && value > 0 ? value : null;
                                if (nextValue !== (activeStory?.word_count_goal ?? null)) {
                                    onUpdateStory({ word_count_goal: nextValue });
                                }
                            }}
                            placeholder="e.g. 50000"
                            className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/50 transition-colors"
                        />
                        <p className="text-xs text-gray-500 mt-1"><Target size={9} className="inline mr-0.5 -mt-px" />Shows a progress bar in the editor.</p>
                    </div>
                </div>

                {/* Description */}
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                        Description
                    </label>
                    <textarea
                        key={`story-description-${activeStory?.id || 'none'}`}
                        defaultValue={activeStory?.description || ''}
                        onBlur={(e) => {
                            const value = e.target.value.trim() || null;
                            if (value !== (activeStory?.description || null)) {
                                onUpdateStory({ description: value });
                            }
                        }}
                        aria-label="Story description" placeholder="A brief description of this story world..."
                        rows={3}
                        className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/50 resize-none"
                    />
                </div>

                {/* Memory / Author's Note */}
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                        <PenTool size={12} className="text-amber-400" /> Memory (Author's Note)
                    </label>
                    <textarea
                        key={`story-memory-${activeStory?.id || 'none'}`}
                        defaultValue={activeStory?.memory || ''}
                        onBlur={(e) => {
                            const value = e.target.value.trim() || null;
                            if (value !== (activeStory?.memory || null)) {
                                onUpdateStory({ memory: value });
                            }
                        }}
                        aria-label="Persistent facts the AI should always remember" placeholder="Persistent facts the AI should always remember (e.g. the protagonist is cursed to turn to stone at midnight)..."
                        rows={3}
                        className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500/50 resize-none"
                    />
                    <p className="text-xs text-gray-500 mt-1">Injected into every story continuation prompt.</p>
                </div>
            </div>
        </>
    );
});
