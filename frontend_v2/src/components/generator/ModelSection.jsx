import { memo, useState, useEffect } from 'react';
import { Settings2, Plus, Trash2, ChevronDown, Sparkles, Info, ImageIcon, Search, X } from 'lucide-react';
import ModelSelector from '../../components/ModelSelector';
import { isFluxModel, isAuraFlowModel, isPonyModel, isUnetModel } from '../../utils/modelType';
import { formatBytes } from '../../utils/bytes';
import {
    getShortEmbeddingName,
    getEmbeddingWeight,
    toggleEmbeddingInPrompt,
    setEmbeddingWeightInPrompt,
    removeEmbeddingFromPrompt,
} from '../../utils/embeddingHelpers';
import { getModelWithVersion } from '../../utils/modelDisplay';
import toast from 'react-hot-toast';

const ModelSection = memo(function ModelSection({
    selectedCheckpoint,
    setSelectedCheckpoint,
    selectedVae,
    setSelectedVae,
    selectedClip,
    setSelectedClip,
    selectedClip2,
    setSelectedClip2,
    selectedLoras,
    addLora,
    removeLora,
    updateLora,
    addTriggerWords,
    prompt,
    negativePrompt,
    setPrompt,
    setNegativePrompt,
    checkpoints,
    unetModels,
    vaeModels,
    clipModels,
    embeddingModels,
    promptShortcuts,
    setViewingMetadata,
    providers,
    providersLoading,
    autoOpenLoraIndex,
    setAutoOpenLoraIndex,
}) {
    const [expandedTriggerGroups, setExpandedTriggerGroups] = useState({});
    const [embeddingSearch, setEmbeddingSearch] = useState('');
    const [activeWeightPopup, setActiveWeightPopup] = useState(null); // { name, target: 'pos' | 'neg' }

    useEffect(() => {
        function handleClickOutside(event) {
            if (activeWeightPopup && !event.target.closest('.embedding-pill-container')) {
                setActiveWeightPopup(null);
            }
        }
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [activeWeightPopup]);

    const handleAddLora = () => {
        addLora();
        setAutoOpenLoraIndex(selectedLoras.length);
    };

    const handleLoraChange = (index, field, value) => {
        updateLora(index, field, value);
    };

    const handleAddTriggerWordsUI = (words) => {
        addTriggerWords(words);
        toast.success("Added trigger words!");
    };

    const handleApplySDXLSettingsUI = () => {
        addTriggerWords([]);
        toast.success("Applied SDXL Settings!");
    };

    return (
        <div className="glass-panel p-5 rounded-2xl border border-white/5 shadow-xl space-y-4 lg:space-y-5 mb-4">
            <h3 className="text-base lg:text-lg font-bold flex items-center gap-2 text-white">
                <Settings2 size={20} className="text-purple-400 drop-shadow-[0_0_8px_rgba(168,85,247,0.6)]" />
                Models
            </h3>

            <div className="flex gap-2 items-end">
                <div className="flex-1 min-w-0">
                    <ModelSelector
                        label="Checkpoint / UNET"
                        initialModels={[...checkpoints, ...unetModels]}
                        value={selectedCheckpoint?.name}
                        selectedModel={selectedCheckpoint}
                        onChange={setSelectedCheckpoint}
                        onVersionChange={setSelectedCheckpoint}
                        onInfoClick={(model) => setViewingMetadata(model)}
                        onAddTriggerWords={handleAddTriggerWordsUI}
                        onApplySDXLSettings={handleApplySDXLSettingsUI}
                        showAvailabilityBadge={true}
                        providers={providers}
                        providersLoading={providersLoading}
                    />
                </div>
            </div>

            <div className="space-y-1.5 group">
                <label className="text-2xs font-bold text-purple-400 uppercase tracking-widest px-1">VAE</label>
                <select
                    value={selectedVae}
                    onChange={(e) => setSelectedVae(e.target.value)}
                    className="w-full bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3 text-white text-sm focus:ring-2 focus:ring-purple-500/50 focus:border-purple-500/50 outline-none transition-all shadow-inner glow-focus"
                >
                    <option value="Baked in">Baked in (Default)</option>
                    {vaeModels.map(v => (
                        <option key={v.name} value={v.name}>{v.name}</option>
                    ))}
                </select>
            </div>

            {isUnetModel(selectedCheckpoint) && clipModels.length > 0 && (
                <div className="space-y-3 p-4 bg-purple-900/10 rounded-xl border border-purple-500/20 shadow-inner">
                    <div className="flex items-center gap-2">
                        <Sparkles size={16} className="text-purple-400 drop-shadow-[0_0_5px_rgba(168,85,247,0.5)]" />
                        <label className="text-xs font-medium text-purple-300">
                            {isFluxModel(selectedCheckpoint) ? "Flux Text Encoders" : "Text Encoder (CLIP)"}
                        </label>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="space-y-1">
                            <label className="text-xs uppercase text-gray-500 font-bold tracking-wider">
                                {isFluxModel(selectedCheckpoint) ? "T5XXL Encoder" : "Primary Encoder"}
                            </label>
                            <select
                                value={selectedClip || ""}
                                onChange={(e) => setSelectedClip(e.target.value)}
                                className="w-full bg-gray-900/80 border border-gray-700/50 rounded px-2 py-1.5 text-xs text-gray-300 focus:border-purple-500 focus:ring-1 focus:ring-purple-500 outline-none"
                            >
                                <option value="">Select CLIP...</option>
                                {clipModels
                                    .filter(m => {
                                        const n = m.name.toLowerCase();
                                        if (isFluxModel(selectedCheckpoint) || isAuraFlowModel(selectedCheckpoint)) {
                                            return n.includes('t5') || n.includes('fp16') || n.includes('fp8');
                                        }
                                        if (isPonyModel(selectedCheckpoint)) {
                                            return n.includes('clip_g') || n.includes('sdxl') || n.includes('vit-g') || (!n.includes('t5') && !n.includes('flux'));
                                        }
                                        return true;
                                    })
                                    .map(m => (
                                        <option key={m.name} value={m.name}>{m.name} ({formatBytes(m.size)})</option>
                                    ))}
                                {clipModels.some(m => !m.name.toLowerCase().includes('t5') && !m.name.toLowerCase().includes('fp16')) && (
                                    <optgroup label="Other">
                                        {clipModels.filter(m => isFluxModel(selectedCheckpoint) ? (!m.name.toLowerCase().includes('t5') && !m.name.toLowerCase().includes('fp16')) : false).map(m => (
                                            <option key={m.name} value={m.name}>{m.name}</option>
                                        ))}
                                    </optgroup>
                                )}
                            </select>
                        </div>

                        {(isFluxModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint)) && (
                            <div className="space-y-1">
                                <label className="text-xs uppercase text-gray-500 font-bold tracking-wider">CLIP-L Encoder</label>
                                <select
                                    value={selectedClip2 || ""}
                                    onChange={(e) => setSelectedClip2(e.target.value)}
                                    className="w-full bg-gray-900/80 border border-gray-700/50 rounded px-2 py-1.5 text-xs text-gray-300 focus:border-purple-500 focus:ring-1 focus:ring-purple-500 outline-none"
                                >
                                    <option value="">Select CLIP...</option>
                                    {clipModels
                                        .filter(m => m.name.toLowerCase().includes('clip_l') || m.name.toLowerCase().includes('vit-l') || m.name.toLowerCase().includes('sdxl_clip_l'))
                                        .map(m => (
                                            <option key={m.name} value={m.name}>{m.name} ({formatBytes(m.size)})</option>
                                        ))}
                                </select>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {embeddingModels.length > 0 && (() => {
                const filteredEmbeddings = embeddingSearch.trim()
                    ? embeddingModels.filter((emb) =>
                          emb.name.toLowerCase().includes(embeddingSearch.toLowerCase()) ||
                          getShortEmbeddingName(emb.name).toLowerCase().includes(embeddingSearch.toLowerCase())
                      )
                    : embeddingModels;

                return (
                    <div className="space-y-2.5 pt-2 border-t border-white/5">
                        <div className="flex items-center justify-between gap-2">
                            <label className="text-xs font-semibold text-gray-300 flex items-center gap-1.5">
                                <Sparkles size={13} className="text-purple-400" />
                                <span>Embeddings</span>
                                <span className="text-2xs text-gray-500 font-normal">
                                    ({embeddingModels.length} installed)
                                </span>
                            </label>

                            {/* Search filter if more than 3 embeddings */}
                            {embeddingModels.length > 3 && (
                                <div className="relative">
                                    <Search size={11} className="absolute left-2 top-2 text-gray-500" />
                                    <input
                                        type="text"
                                        value={embeddingSearch}
                                        onChange={(e) => setEmbeddingSearch(e.target.value)}
                                        placeholder="Filter embeddings..."
                                        className="bg-gray-900/80 border border-gray-700/50 rounded-lg pl-6 pr-5 py-0.5 text-2xs text-gray-300 placeholder-gray-500 focus:border-purple-500 outline-none w-36 lg:w-44 transition-all"
                                    />
                                    {embeddingSearch && (
                                        <button
                                            type="button"
                                            onClick={() => setEmbeddingSearch('')}
                                            className="absolute right-1.5 top-1.5 text-gray-500 hover:text-gray-300"
                                            title="Clear search"
                                        >
                                            <X size={10} />
                                        </button>
                                    )}
                                </div>
                            )}
                        </div>

                        <div className="flex flex-wrap gap-2">
                            {filteredEmbeddings.length === 0 ? (
                                <p className="text-2xs text-gray-500 py-1">No embeddings match &ldquo;{embeddingSearch}&rdquo;</p>
                            ) : (
                                filteredEmbeddings.map((emb) => {
                                    const shortName = getShortEmbeddingName(emb.name);
                                    const posWeight = getEmbeddingWeight(prompt, emb.name);
                                    const negWeight = getEmbeddingWeight(negativePrompt, emb.name);
                                    const isInPos = posWeight !== null;
                                    const isInNeg = negWeight !== null;
                                    const isPopupOpen = activeWeightPopup?.name === emb.name;

                                    return (
                                        <div
                                            key={emb.name}
                                            className={`embedding-pill-container relative inline-flex items-center rounded-lg border text-xs transition-all shadow-sm ${
                                                isInPos || isInNeg
                                                    ? 'bg-purple-950/30 border-purple-500/50 ring-1 ring-purple-500/30 text-white'
                                                    : 'bg-gray-900/60 border-gray-700/60 text-gray-300 hover:border-gray-600'
                                            }`}
                                        >
                                            {/* Short name with full filename on hover */}
                                            <span
                                                className="px-2.5 py-1.5 font-medium cursor-default select-none truncate max-w-[170px]"
                                                title={`${emb.name} (${formatBytes(emb.size)})`}
                                            >
                                                {shortName}
                                            </span>

                                            {/* Action / Status Controls */}
                                            <div className="flex items-center border-l border-white/10 pr-1 gap-1">
                                                {/* Positive Toggle / Weight */}
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        if (isInPos) {
                                                            setActiveWeightPopup(
                                                                isPopupOpen && activeWeightPopup?.target === 'pos'
                                                                    ? null
                                                                    : { name: emb.name, target: 'pos' }
                                                            );
                                                        } else {
                                                            const next = toggleEmbeddingInPrompt(prompt, emb.name);
                                                            setPrompt(next);
                                                            toast(`Added ${shortName} to Positive Prompt`, { icon: '✨' });
                                                        }
                                                    }}
                                                    className={`px-1.5 py-0.5 text-2xs rounded font-semibold transition-all flex items-center gap-0.5 ${
                                                        isInPos
                                                            ? 'bg-blue-600/30 border border-blue-500/50 text-blue-300 hover:bg-blue-600/50'
                                                            : 'text-gray-400 hover:text-blue-300 hover:bg-white/5'
                                                    }`}
                                                    title={isInPos ? `Active in Positive (${posWeight.toFixed(1)}). Click to adjust weight.` : `Add ${shortName} to Positive Prompt`}
                                                >
                                                    <span>+Pos</span>
                                                    {isInPos && (
                                                        <span className="font-mono text-2xs underline ml-0.5">
                                                            {posWeight.toFixed(1)}
                                                        </span>
                                                    )}
                                                </button>

                                                {/* Remove from Pos button when active */}
                                                {isInPos && (
                                                    <button
                                                        type="button"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            const next = removeEmbeddingFromPrompt(prompt, emb.name);
                                                            setPrompt(next);
                                                            if (activeWeightPopup?.name === emb.name && activeWeightPopup?.target === 'pos') {
                                                                setActiveWeightPopup(null);
                                                            }
                                                            toast(`Removed ${shortName} from Positive Prompt`, { icon: '🗑️' });
                                                        }}
                                                        className="text-gray-400 hover:text-red-400 p-0.5 transition-colors"
                                                        title={`Remove ${shortName} from Positive Prompt`}
                                                        aria-label={`Remove ${shortName} from Positive Prompt`}
                                                    >
                                                        <X size={10} />
                                                    </button>
                                                )}

                                                {/* Negative Toggle / Weight */}
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        if (isInNeg) {
                                                            setActiveWeightPopup(
                                                                isPopupOpen && activeWeightPopup?.target === 'neg'
                                                                    ? null
                                                                    : { name: emb.name, target: 'neg' }
                                                            );
                                                        } else {
                                                            const next = toggleEmbeddingInPrompt(negativePrompt, emb.name);
                                                            setNegativePrompt(next);
                                                            toast(`Added ${shortName} to Negative Prompt`, { icon: '🚫' });
                                                        }
                                                    }}
                                                    className={`px-1.5 py-0.5 text-2xs rounded font-semibold transition-all flex items-center gap-0.5 ${
                                                        isInNeg
                                                            ? 'bg-pink-600/30 border border-pink-500/50 text-pink-300 hover:bg-pink-600/50'
                                                            : 'text-gray-400 hover:text-pink-300 hover:bg-white/5'
                                                    }`}
                                                    title={isInNeg ? `Active in Negative (${negWeight.toFixed(1)}). Click to adjust weight.` : `Add ${shortName} to Negative Prompt`}
                                                >
                                                    <span>+Neg</span>
                                                    {isInNeg && (
                                                        <span className="font-mono text-2xs underline ml-0.5">
                                                            {negWeight.toFixed(1)}
                                                        </span>
                                                    )}
                                                </button>

                                                {/* Remove from Neg button when active */}
                                                {isInNeg && (
                                                    <button
                                                        type="button"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            const next = removeEmbeddingFromPrompt(negativePrompt, emb.name);
                                                            setNegativePrompt(next);
                                                            if (activeWeightPopup?.name === emb.name && activeWeightPopup?.target === 'neg') {
                                                                setActiveWeightPopup(null);
                                                            }
                                                            toast(`Removed ${shortName} from Negative Prompt`, { icon: '🗑️' });
                                                        }}
                                                        className="text-gray-400 hover:text-red-400 p-0.5 transition-colors"
                                                        title={`Remove ${shortName} from Negative Prompt`}
                                                        aria-label={`Remove ${shortName} from Negative Prompt`}
                                                    >
                                                        <X size={10} />
                                                    </button>
                                                )}
                                            </div>

                                            {/* Weight Slider Popover */}
                                            {isPopupOpen && (
                                                <div
                                                    className="absolute top-full mt-1.5 left-0 z-50 p-2.5 bg-gray-900/95 backdrop-blur-md border border-white/15 rounded-xl shadow-2xl min-w-[200px] space-y-2 animate-in fade-in zoom-in-95 duration-100"
                                                >
                                                    <div className="flex justify-between items-center text-2xs text-gray-300">
                                                        <span className="font-semibold">
                                                            {activeWeightPopup.target === 'pos' ? 'Positive Weight:' : 'Negative Weight:'}
                                                        </span>
                                                        <span className="font-mono text-purple-400">
                                                            {(activeWeightPopup.target === 'pos' ? posWeight : negWeight)?.toFixed(2)}
                                                        </span>
                                                    </div>

                                                    <input
                                                        type="range"
                                                        min="0.4"
                                                        max="1.8"
                                                        step="0.05"
                                                        value={activeWeightPopup.target === 'pos' ? (posWeight ?? 1.0) : (negWeight ?? 1.0)}
                                                        onChange={(e) => {
                                                            const w = parseFloat(e.target.value);
                                                            if (activeWeightPopup.target === 'pos') {
                                                                const next = setEmbeddingWeightInPrompt(prompt, emb.name, w);
                                                                setPrompt(next);
                                                            } else {
                                                                const next = setEmbeddingWeightInPrompt(negativePrompt, emb.name, w);
                                                                setNegativePrompt(next);
                                                            }
                                                        }}
                                                        className="w-full accent-purple-500 cursor-pointer h-1.5 bg-gray-700 rounded-lg"
                                                    />

                                                    <div className="flex justify-between gap-1 pt-1">
                                                        {[0.8, 0.9, 1.0, 1.1, 1.2].map((preset) => {
                                                            const currentW = activeWeightPopup.target === 'pos' ? posWeight : negWeight;
                                                            const isSelected = Math.abs((currentW ?? 1.0) - preset) < 0.01;
                                                            return (
                                                                <button
                                                                    key={preset}
                                                                    type="button"
                                                                    onClick={() => {
                                                                        if (activeWeightPopup.target === 'pos') {
                                                                            const next = setEmbeddingWeightInPrompt(prompt, emb.name, preset);
                                                                            setPrompt(next);
                                                                        } else {
                                                                            const next = setEmbeddingWeightInPrompt(negativePrompt, emb.name, preset);
                                                                            setNegativePrompt(next);
                                                                        }
                                                                    }}
                                                                    className={`px-1.5 py-0.5 text-2xs rounded border transition-colors ${
                                                                        isSelected
                                                                            ? 'bg-purple-600 border-purple-500 text-white font-bold'
                                                                            : 'bg-black/30 border-white/10 text-gray-300 hover:bg-white/10'
                                                                    }`}
                                                                >
                                                                    {preset}
                                                                </button>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </div>
                );
            })()}

            {Object.keys(promptShortcuts).length > 0 && (
                <div className="space-y-2">
                    <label className="text-xs font-medium text-gray-500 flex items-center gap-2">
                        Prompt Shortcuts
                        <span className="text-xs text-gray-600">(Click to insert token)</span>
                    </label>
                    <div className="flex flex-wrap gap-2">
                        {Object.entries(promptShortcuts).map(([name, expansion]) => {
                            const token = name;
                            const isInPositive = prompt.includes(token);
                            const isInNegative = negativePrompt.includes(token);
                            const isActive = isInPositive || isInNegative;
                            return (
                                <button
                                    key={name}
                                    onClick={() => {
                                        if (isInNegative) {
                                            setNegativePrompt(negativePrompt ? `${negativePrompt}, ${token}` : token);
                                            toast.success(`Added ${token} to Negative Prompt`, { icon: '✨' });
                                        } else {
                                            setPrompt(prompt ? `${prompt}, ${token}` : token);
                                            toast.success(`Added ${token} to Positive Prompt`, { icon: '✨' });
                                        }
                                    }}
                                    className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${isActive
                                        ? 'bg-purple-900/40 border-purple-700 text-purple-300 ring-1 ring-purple-500/50'
                                        : 'bg-purple-900/20 border-purple-800 text-purple-400 hover:bg-purple-900/40'}`}
                                    title={`“${name}” → ${expansion}
Click to insert “${token}” into ${isActive ? "the prompt (already added)" : "positive prompt"}`}
                                    type="button"
                                >
                                    {name}
                                    {isActive && <span className="ml-1">✓</span>}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

            <div className="space-y-3">
                <div className="flex justify-between items-center">
                    <label className="block text-xs font-medium text-gray-500">LoRAs</label>
                    <button onClick={handleAddLora} className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300">
                        <Plus size={14} /> Add LoRA
                    </button>
                </div>

                <div className="space-y-2">
                    {selectedLoras.map((lora, idx) => {
                        const activeTriggerGroups = (lora.trained_words || []).map(group => {
                            const individualTags = group.split(',').map(t => t.trim()).filter(Boolean);
                            const promptLower = (prompt || '').toLowerCase();
                            const unusedTags = individualTags.filter(tag => !promptLower.includes(tag.toLowerCase()));

                            return {
                                fullGroup: group,
                                individualTags,
                                unusedTags,
                                previewText: group.length > 25 ? group.slice(0, 25) + '…' : group
                            };
                        }).filter(g => g.unusedTags.length > 0);

                        return (
                            <div key={idx} className="bg-gray-900/30 rounded-lg border border-gray-700/50 overflow-hidden flex">
                                {lora.preview ? (
                                    <img
                                        src={lora.preview}
                                        alt={lora.name}
                                        className="w-16 h-auto min-h-full object-cover flex-shrink-0 cursor-pointer"
                                        onClick={() => setAutoOpenLoraIndex(idx)}
                                        onError={(e) => { e.target.style.display = 'none'; }}
                                    />
                                ) : (
                                    <div
                                        className="w-16 min-h-full bg-gray-800 flex items-center justify-center text-gray-600 flex-shrink-0 cursor-pointer"
                                        onClick={() => setAutoOpenLoraIndex(idx)}
                                    >
                                        <ImageIcon size={20} />
                                    </div>
                                )}

                                <div className="flex-1 min-w-0 p-2 space-y-1.5">
                                    <div className="flex items-start gap-1">
                                        <button
                                            onClick={() => setAutoOpenLoraIndex(idx)}
                                            className="flex-1 min-w-0 text-left hover:text-blue-400 transition-colors"
                                        >
                                            <div className="text-sm font-medium text-white line-clamp-2 leading-tight">
                                                {lora.display_name || lora.name || 'Select LoRA...'}
                                            </div>
                                            <div className="flex items-center gap-1.5 flex-wrap">
                                                {lora.base_model && (
                                                    <span className="text-2xs text-gray-500">{lora.base_model}</span>
                                                )}
                                                {(() => {
                                                    const ckptBase = selectedCheckpoint?.base_model || selectedCheckpoint?.baseModel || (isFluxModel(selectedCheckpoint) ? 'Flux' : (isPonyModel(selectedCheckpoint) ? 'Pony' : null));
                                                    const loraBase = lora.base_model || lora.baseModel;
                                                    if (!ckptBase || !loraBase) return null;
                                                    const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
                                                    const c = norm(ckptBase);
                                                    const l = norm(loraBase);
                                                    const isSdxlFam = (s) => s.includes('sdxl') || s.includes('pony') || s.includes('illustrious') || s.includes('noob');
                                                    if (isSdxlFam(c) && isSdxlFam(l)) return null;
                                                    if (c === l) return null;

                                                    return (
                                                        <span
                                                            className="text-3xs bg-amber-950/60 text-amber-300 border border-amber-800/80 px-1 py-0.2 rounded font-medium inline-flex items-center gap-0.5"
                                                            title={`Architecture mismatch: LoRA is ${loraBase}, but checkpoint is ${ckptBase}`}
                                                        >
                                                            ⚠️ {loraBase} on {ckptBase}
                                                        </span>
                                                    );
                                                })()}
                                            </div>

                                            {lora.versions && lora.versions.length > 1 && (
                                                <div className="flex items-center gap-1.5 mt-1">
                                                    <span className="text-3xs uppercase tracking-wider text-gray-500 font-semibold">Outfit:</span>
                                                    <select
                                                        aria-label="Select outfit or version"
                                                        value={lora.selectedVersionId || (lora.versions.find(v => v.is_default) || lora.versions[0])?.id}
                                                        onChange={(e) => {
                                                            const targetId = e.target.value;
                                                            const targetVer = lora.versions.find(v => String(v.id) === targetId || String(v.civitai_version_id) === targetId);
                                                            if (targetVer) {
                                                                const original = lora._originalModel || lora;
                                                                const updated = getModelWithVersion(original, targetVer);
                                                                updateLora(idx, 'model', updated);
                                                                if (targetVer.trained_words?.length > 0) {
                                                                    toast.success(`Switched outfit to "${targetVer.name}"`, { icon: '👗' });
                                                                }
                                                            }
                                                        }}
                                                        className="text-2xs bg-gray-900 border border-gray-700/80 rounded px-1.5 py-0.5 text-gray-200 outline-none focus:border-blue-500 cursor-pointer max-w-[210px] truncate"
                                                        onClick={(e) => e.stopPropagation()}
                                                    >
                                                        {lora.versions.map((ver) => (
                                                            <option key={ver.id} value={ver.id}>
                                                                {ver.name}{ver.base_model ? ` (${ver.base_model})` : ''}
                                                            </option>
                                                        ))}
                                                    </select>
                                                </div>
                                            )}
                                        </button>

                                        <button
                                            onClick={() => setViewingMetadata(lora)}
                                            className="p-1 text-gray-500 hover:text-blue-400 transition-colors flex-shrink-0"
                                            title="View info"
                                        >
                                            <Info size={14} />
                                        </button>

                                        <button
                                            onClick={() => removeLora(idx)}
                                            className="p-1 text-gray-500 hover:text-red-400 transition-colors flex-shrink-0"
                                            title="Remove"
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </div>

                                    <div className="flex items-center gap-2">
                                        <input
                                            type="range"
                                            min="-2"
                                            max="2"
                                            step="0.1"
                                            className="flex-1 min-w-0 h-1.5 accent-blue-500 touch-none"
                                            onTouchStart={(e) => e.stopPropagation()}
                                            onTouchMove={(e) => e.stopPropagation()}
                                            value={Math.max(-2, Math.min(2, lora.strength))}
                                            onChange={(e) => handleLoraChange(idx, 'strength', parseFloat(e.target.value))}
                                        />
                                        <input
                                            type="number"
                                            step="0.1"
                                            className="w-12 bg-gray-800 border border-gray-600 rounded px-1.5 py-0.5 text-xs text-white text-center flex-shrink-0"
                                            value={lora.strength}
                                            onChange={(e) => handleLoraChange(idx, 'strength', parseFloat(e.target.value) || 0)}
                                        />
                                    </div>

                                    {activeTriggerGroups.length > 0 && (
                                        <div className="space-y-1 pt-1 border-t border-gray-700/50">
                                            {activeTriggerGroups.map((group, groupIdx) => {
                                                const groupKey = `${idx}-${groupIdx}`;
                                                const isExpanded = expandedTriggerGroups[groupKey];

                                                return (
                                                    <div key={groupIdx} className="space-y-1">
                                                        <button
                                                            onClick={() => setExpandedTriggerGroups(prev => ({
                                                                ...prev,
                                                                [groupKey]: !isExpanded
                                                            }))}
                                                            className="w-full text-left text-2xs bg-gray-800/50 hover:bg-gray-700/50 text-gray-400 px-1.5 py-1 rounded flex items-center gap-1 transition-colors"
                                                        >
                                                            <ChevronDown
                                                                size={10}
                                                                className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                                            />
                                                            <span className="truncate">{group.previewText}</span>
                                                            <span className="text-gray-600 flex-shrink-0">({group.individualTags.length})</span>
                                                        </button>

                                                        {isExpanded && (
                                                            <div className="flex flex-wrap gap-1 pl-2">
                                                                <button
                                                                    onClick={() => handleAddTriggerWordsUI([group.fullGroup])}
                                                                    className="text-2xs bg-green-900/30 text-green-300 px-1.5 py-0.5 rounded hover:bg-green-900/50 transition-colors"
                                                                >
                                                                    + All
                                                                </button>
                                                                {group.unusedTags.map((tag, tagIdx) => (
                                                                    <button
                                                                        key={tagIdx}
                                                                        onClick={() => setPrompt(prompt ? `${prompt}, ${tag}` : tag)}
                                                                        className="text-2xs bg-blue-900/30 text-blue-300 px-1.5 py-0.5 rounded hover:bg-blue-900/50 transition-colors"
                                                                    >
                                                                        +{tag}
                                                                    </button>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}

                    {autoOpenLoraIndex !== null && selectedLoras[autoOpenLoraIndex] && (
                        <ModelSelector
                            label="Select LoRA"
                            value={selectedLoras[autoOpenLoraIndex]?.name}
                            selectedModel={selectedLoras[autoOpenLoraIndex]}
                            preview={selectedLoras[autoOpenLoraIndex]?.preview}
                            metadata={selectedLoras[autoOpenLoraIndex]?.metadata}
                            onChange={(m) => handleLoraChange(autoOpenLoraIndex, 'model', m)}
                            onInfoClick={(model) => setViewingMetadata(model)}
                            onAddTriggerWords={handleAddTriggerWordsUI}
                            directory="models/loras"
                            autoOpen={true}
                            onAutoOpenComplete={() => setAutoOpenLoraIndex(null)}
                            showAvailabilityBadge={true}
                            providers={providers}
                            providersLoading={providersLoading}
                        />
                    )}
                </div>
            </div>
        </div>
    );
});

export default ModelSection;
