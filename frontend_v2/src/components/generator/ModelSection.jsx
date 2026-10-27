import { memo, useState } from 'react';
import { Settings2, Plus, Trash2, ChevronDown, Sparkles, Info, ImageIcon } from 'lucide-react';
import ModelSelector from '../../components/ModelSelector';
import { isFluxModel, isAuraFlowModel, isPonyModel, isUnetModel } from '../../utils/modelType';
import { formatBytes } from '../../utils/bytes';
import { isNegativeEmbedding, toggleEmbeddingInPrompt, hasEmbedding } from '../../utils/embeddingHelpers';
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

            {embeddingModels.length > 0 && (
                <div className="space-y-2">
                    <label className="text-xs font-medium text-gray-500 flex items-center gap-2">
                        Embeddings
                        <span className="text-xs text-gray-600">(Click to add to prompt)</span>
                    </label>
                    <div className="flex flex-wrap gap-2">
                        {embeddingModels.map(emb => {
                            const isNegative = isNegativeEmbedding(emb.name);
                            const isInPositive = hasEmbedding(prompt, emb.name);
                            const isInNegative = hasEmbedding(negativePrompt, emb.name);
                            const isActive = isInPositive || isInNegative;

                            return (
                                <button
                                    key={emb.name}
                                    onClick={() => {
                                        if (isNegative) {
                                            const next = toggleEmbeddingInPrompt(negativePrompt, emb.name);
                                            setNegativePrompt(next);
                                            const wasAdded = hasEmbedding(next, emb.name);
                                            toast(wasAdded ? `Added ${emb.name} to Negative Prompt` : `Removed ${emb.name} from Negative Prompt`, { icon: '🚫' });
                                        } else {
                                            const next = toggleEmbeddingInPrompt(prompt, emb.name);
                                            setPrompt(next);
                                            const wasAdded = hasEmbedding(next, emb.name);
                                            toast(wasAdded ? `Added ${emb.name} to Positive Prompt` : `Removed ${emb.name} from Positive Prompt`, { icon: '✨' });
                                        }
                                    }}
                                    className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${isActive
                                        ? isNegative
                                            ? 'bg-red-900/40 border-red-700 text-red-300 ring-1 ring-red-500/50'
                                            : 'bg-blue-900/40 border-blue-700 text-blue-300 ring-1 ring-blue-500/50'
                                        : isNegative
                                            ? 'bg-red-900/20 border-red-800 text-red-400 hover:bg-red-900/40'
                                            : 'bg-blue-900/20 border-blue-800 text-blue-400 hover:bg-blue-900/40'
                                        }`}
                                    title={`Click to toggle in ${isNegative ? "Negative" : "Positive"} Prompt${isActive ? " (Active)" : ""}`}
                                    type="button"
                                >
                                    {emb.name}
                                    {isActive && <span className="ml-1">✓</span>}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

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
