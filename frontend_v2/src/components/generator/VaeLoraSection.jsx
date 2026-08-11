import { Plus, Trash2 } from 'lucide-react';
import ModelSelector from '../ModelSelector';

/**
 * VAE selector + LoRA list shared by the Img2Img and Inpaint pages
 * (identical markup, only accent accents differed historically).
 */
export default function VaeLoraSection({
    selectedVae,
    setSelectedVae,
    vaeModels,
    selectedLoras,
    addLora,
    removeLora,
    updateLora,
    autoOpenLoraIndex,
    setAutoOpenLoraIndex,
}) {
    return (
        <>
            {/* VAE Selector */}
            <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500">VAE</label>
                <select
                    value={selectedVae}
                    onChange={(e) => setSelectedVae(e.target.value)}
                    className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-white text-sm"
                >
                    <option value="Baked in">Baked in (Default)</option>
                    {vaeModels.map(v => (
                        <option key={v.name} value={v.name}>{v.name}</option>
                    ))}
                </select>
            </div>

            {/* LoRAs */}
            <div className="space-y-3">
                <div className="flex justify-between items-center">
                    <label className="block text-xs font-medium text-gray-500">LoRAs</label>
                    <button
                        onClick={() => {
                            addLora();
                            setAutoOpenLoraIndex(selectedLoras.length);
                        }}
                        className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300"
                    >
                        <Plus size={14} /> Add LoRA
                    </button>
                </div>

                {selectedLoras.map((lora, idx) => (
                    <div key={idx} className="bg-gray-900/50 p-3 rounded-lg border border-gray-700 space-y-2">
                        <ModelSelector
                            label={`LoRA ${idx + 1}`}
                            value={lora.name}
                            selectedModel={lora}
                            onChange={(m) => updateLora(idx, 'model', m)}
                            directory="models/loras"
                            autoOpen={autoOpenLoraIndex === idx}
                            onAutoOpenComplete={() => setAutoOpenLoraIndex(null)}
                        />
                        <div className="flex gap-2 items-center">
                            <div className="flex-1">
                                <label className="text-xs text-gray-500">Strength</label>
                                <div className="flex gap-2 items-center">
                                    <input
                                        type="range"
                                        min="-4"
                                        max="4"
                                        step="0.1"
                                        className="flex-1"
                                        value={lora.strength}
                                        onChange={(e) => updateLora(idx, 'strength', parseFloat(e.target.value))}
                                    />
                                    <input
                                        type="number"
                                        step="0.1"
                                        className="w-16 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-white text-center"
                                        value={lora.strength}
                                        onChange={(e) => updateLora(idx, 'strength', parseFloat(e.target.value))}
                                    />
                                </div>
                            </div>
                            <button
                                onClick={() => removeLora(idx)}
                                className="text-red-400 hover:text-red-300 p-2 bg-gray-800 rounded-lg self-end"
                                title="Remove LoRA"
                            >
                                <Trash2 size={16} />
                            </button>
                        </div>
                    </div>
                ))}
            </div>
        </>
    );
}
