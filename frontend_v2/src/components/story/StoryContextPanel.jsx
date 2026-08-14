import React from 'react';
import { ImageIcon, X, Layers, Check, Settings, Book, Calendar, Tag, PenTool, Edit2 } from 'lucide-react';
import clsx from 'clsx';
import { assetUrl } from '../../utils/assetUrl';

export default React.memo(function StoryContextPanel({
    activeStory,
    activeChapter,
    characters,
    lorebooks,
    storyImages,
    chapters,
    llmModels,
    defaultLlmConfig,
    onClose,
    onShowGallery,
    onUpdateStory,
    onEditCharacter,
    onEditLorebook
}) {
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
                                        "w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors",
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
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                        <Layers size={14} /> Lorebooks
                    </h4>
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
                                                {lb.description && <p className="text-[10px] text-gray-500 truncate">{lb.description}</p>}
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
                            <ImageIcon size={14} /> Chapter Images
                        </h4>
                        <button
                            onClick={onShowGallery}
                            className="text-[10px] text-indigo-400 hover:text-indigo-300 transition-colors"
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
                         <p className="text-[10px] text-gray-500 mt-1">Per-story model override; used for continuations and titles.</p>
                     </div>
                     <div>
                         <div className="flex items-center justify-between mb-1.5">
                             <p className="text-xs text-gray-300 font-medium">Agentic Loop Depth</p>
                             <span className="text-[10px] text-gray-500 font-mono">
                                 {activeStory?.max_agentic_depth
                                     ? `${activeStory.max_agentic_depth} steps`
                                     : 'Global default (5)'}
                             </span>
                         </div>
                         <input
                             type="range"
                             min="1"
                             max="10"
                             step="1"
                             value={activeStory?.max_agentic_depth || 5}
                             onChange={(e) => onUpdateStory({ max_agentic_depth: parseInt(e.target.value) })}
                             className="w-full accent-purple-500"
                             title="Max agentic tool-call loops per continuation. Higher = more autonomous but slower."
                         />
                         <div className="flex justify-between text-[9px] text-gray-600 mt-0.5">
                             <span>1</span><span>5</span><span>10</span>
                         </div>
                         {activeStory?.max_agentic_depth && (
                             <button
                                 onClick={() => onUpdateStory({ max_agentic_depth: null })}
                                 className="mt-1 text-[9px] text-gray-500 hover:text-red-400 transition-colors"
                             >
                                 Reset to global default
                             </button>
                         )}
                     </div>
                 </div>
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                        <Book size={14} /> Story Info
                    </h4>
                    <div className="space-y-3 text-xs text-gray-400">
                        <p>Chapters: {chapters?.length || 0}</p>
                        <p>Status: {activeStory?.is_archived ? 'Archived' : 'Active'}</p>
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
                    <label className="block text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                        <Tag size={12} className="text-purple-400" /> Genre
                    </label>
                    <input
                        type="text"
                        value={activeStory?.genre || ''}
                        onChange={(e) => {
                            onUpdateStory({ genre: e.target.value.trim() || null });
                        }}
                        placeholder="e.g. Fantasy, Cyberpunk, Horror"
                        className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/50 transition-colors"
                    />
                    <p className="text-[10px] text-gray-500 mt-1">Steer story continuation tone/style.</p>
                </div>

                {/* Description */}
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <label className="block text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">
                        Description
                    </label>
                    <textarea
                        value={activeStory?.description || ''}
                        onChange={(e) => {
                            onUpdateStory({ description: e.target.value.trim() || null });
                        }}
                        placeholder="A brief description of this story world..."
                        rows={3}
                        className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/50 resize-none"
                    />
                </div>

                {/* Memory / Author's Note */}
                <div className="glass-panel p-4 rounded-xl border border-white/5">
                    <label className="block text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                        <PenTool size={12} className="text-amber-400" /> Memory (Author's Note)
                    </label>
                    <textarea
                        value={activeStory?.memory || ''}
                        onChange={(e) => {
                            onUpdateStory({ memory: e.target.value.trim() || null });
                        }}
                        placeholder="Persistent facts the AI should always remember (e.g. the protagonist is cursed to turn to stone at midnight)..."
                        rows={3}
                        className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500/50 resize-none"
                    />
                    <p className="text-[10px] text-gray-500 mt-1">Injected into every story continuation prompt.</p>
                </div>
            </div>
        </>
    );
});
