import React, { useState } from 'react';
import { Settings2, Info, Plus, Trash2 } from 'lucide-react';
import { useGeneratorStore } from '../../store/generatorStore';
import ModelSelector from '../ModelSelector';
import ModelMetadataModal from '../ModelMetadataModal';
import toast from 'react-hot-toast';

export default function ModelPanel({ checkpoints, vaeModels, embeddingModels }) {
    const {
        selectedCheckpoint, setSelectedCheckpoint,
        selectedVae, setSelectedVae,
        selectedLoras, addLora, removeLora, updateLora,
        setPrompt, setNegativePrompt
    } = useGeneratorStore();

    const [viewingMetadata, setViewingMetadata] = useState(null);

    // Helper for adding trigger words (reusing logic from original component)
    const handleAddTriggerWords = (words) => {
        const event = new CustomEvent('addTriggerWords', { detail: words });
        window.dispatchEvent(event);
    };

    return (
        <div className="bg-gray-800/50 backdrop-blur-sm p-6 rounded-xl border border-gray-700/50 space-y-6 shadow-lg">
            <h3 className="text-lg font-semibold flex items-center gap-2 text-white">
                <Settings2 size={20} className="text-purple-400" />
                Models
            </h3>

            {/* Checkpoint Selector */}
            <div className="flex gap-2 items-end">
                <div className="flex-1">
                    <ModelSelector
                        label="Checkpoint"
                        initialModels={checkpoints}
                        value={selectedCheckpoint?.name}
                        onChange={setSelectedCheckpoint}
                        directory="models/checkpoints"
                    />
                </div>
                {selectedCheckpoint?.metadata && (
                    <button
                        onClick={() => setViewingMetadata(selectedCheckpoint.metadata)}
                        className="p-3 bg-gray-800/80 rounded-lg border border-gray-700 text-gray-400 hover:text-blue-300 hover:border-blue-500/50 transition-all mb-[1px]"
                        title="View Model Details"
                    >
                        <Info size={20} />
                    </button>
                )}
            </div>

            {/* VAE Selector */}
            <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">VAE</label>
                <select
                    value={selectedVae}
                    onChange={(e) => setSelectedVae(e.target.value)}
                    className="w-full bg-gray-900/50 border border-gray-700 rounded-lg p-3 text-white text-sm focus:ring-2 focus:ring-blue-500/50 outline-none transition-all"
                >
                    <option value="Baked in">Baked in (Default)</option>
                    {vaeModels.map(v => (
                        <option key={v.name} value={v.name}>{v.name}</option>
                    ))}
                </select>
            </div>

            {/* Embeddings Quick Select */}
            {embeddingModels.length > 0 && (
                <div className="space-y-2">
                    <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">Embeddings</label>
                    <div className="flex flex-wrap gap-2">
                        {embeddingModels.map(emb => (
                            <button
                                key={emb.name}
                                onClick={() => {
                                    const isNegative = emb.name.toLowerCase().includes("negative");
                                    if (isNegative) {
                                        setNegativePrompt(prev => prev + (prev ? ", " : "") + `embedding:${emb.name}`);
                                        toast.success(`Added ${emb.name} to Negative Prompt`);
                                    } else {
                                        setPrompt(prev => prev + (prev ? ", " : "") + `embedding:${emb.name}`);
                                        toast.success(`Added ${emb.name} to Positive Prompt`);
                                    }
                                }}
                                className={`text-xs px-2 py-1 rounded border transition-colors ${emb.name.toLowerCase().includes("negative")
                                    ? 'bg-red-900/20 border-red-800 text-red-400 hover:bg-red-900/40'
                                    : 'bg-blue-900/20 border-blue-800 text-blue-400 hover:bg-blue-900/40'}`}
                                title={`Click to add to ${emb.name.toLowerCase().includes("negative") ? "Negative" : "Positive"} Prompt`}
                            >
                                {emb.name}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* LoRAs */}
            <div className="space-y-3">
                <div className="flex justify-between items-center">
                    <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider">LoRAs</label>
                    <button onClick={addLora} className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300 transition-colors">
                        <Plus size={14} /> Add LoRA
                    </button>
                </div>

                <div className="space-y-3">
                    {selectedLoras.map((lora, idx) => (
                        <div key={idx} className="bg-gray-900/30 p-3 rounded-lg border border-gray-700/50 space-y-2 hover:border-gray-600 transition-colors">
                            <div className="flex flex-col gap-3">
                                <div className="w-full">
                                    <ModelSelector
                                        label={`LoRA ${idx + 1}`}
                                        value={lora.name}
                                        preview={lora.preview}
                                        metadata={lora.metadata}
                                        onChange={(m) => updateLora(idx, 'model', m)}
                                        directory="models/loras"
                                    />
                                </div>
                                <div className="w-full flex flex-col gap-1">
                                    <div className="flex justify-between items-center">
                                        <label className="text-xs font-medium text-gray-500">Strength</label>
                                        <span className="text-xs text-gray-400 font-mono">{lora.strength}</span>
                                    </div>
                                    <div className="flex gap-2 items-center">
                                        <input
                                            type="range"
                                            min="-4"
                                            max="4"
                                            step="0.1"
                                            aria-label={`Strength for LoRA ${lora.name || idx + 1}`}
                                            className="flex-1 min-w-0 accent-blue-500 h-1 bg-gray-700 rounded-lg appearance-none cursor-pointer"
                                            value={lora.strength}
                                            onChange={(e) => updateLora(idx, 'strength', parseFloat(e.target.value))}
                                        />
                                        <input
                                            type="number"
                                            step="0.1"
                                            className="w-16 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-white focus:ring-1 focus:ring-blue-500 outline-none"
                                            value={lora.strength}
                                            onChange={(e) => updateLora(idx, 'strength', parseFloat(e.target.value))}
                                        />
                                        <button onClick={() => setViewingMetadata(lora.metadata)} className="text-gray-400 hover:text-blue-300 p-2 bg-gray-800 rounded-lg border border-gray-700 ml-2 transition-colors" title="View Metadata">
                                            <Info size={16} />
                                        </button>
                                        <button onClick={() => removeLora(idx)} className="text-red-400 hover:text-red-300 p-2 bg-gray-800 rounded-lg border border-gray-700 ml-2 transition-colors">
                                            <Trash2 size={16} />
                                        </button>
                                    </div>
                                </div>
                            </div>

                            {lora.metadata?.trainedWords && (
                                <div className="flex flex-wrap gap-2 pt-2 border-t border-gray-700/50">
                                    <span className="text-xs text-gray-500 py-1">Trigger Words:</span>
                                    {lora.metadata.trainedWords.map((word, i) => (
                                        <button
                                            key={i}
                                            onClick={() => handleAddTriggerWords([word])}
                                            className="text-xs bg-blue-900/20 text-blue-300 px-2 py-1 rounded hover:bg-blue-900/40 transition-colors border border-blue-500/20"
                                        >
                                            {word}
                                        </button>
                                    ))}
                                    <button
                                        onClick={() => handleAddTriggerWords(lora.metadata.trainedWords)}
                                        className="text-xs bg-gray-700 text-gray-300 px-2 py-1 rounded hover:bg-gray-600 transition-colors"
                                    >
                                        Add All
                                    </button>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>
            <ModelMetadataModal
                metadata={viewingMetadata}
                onClose={() => setViewingMetadata(null)}
            />
        </div>
    );
}
