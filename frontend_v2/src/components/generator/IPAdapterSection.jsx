import React, { memo } from 'react';
import { Plus, Trash2, ImagePlus } from 'lucide-react';
import CollapsibleSection from '../CollapsibleSection';
import ImageUploader from './ImageUploader';
import ModelSelector from '../ModelSelector';

const IPAdapterSection = memo(function IPAdapterSection({
    ipAdapters,
    addIpAdapter,
    removeIpAdapter,
    updateIpAdapter
}) {
    return (
        <CollapsibleSection
            title="Image Prompts (IP-Adapter)"
            icon={<ImagePlus size={20} className="text-pink-400 drop-shadow-[0_0_8px_rgba(244,114,182,0.6)]" />}
            defaultOpen={ipAdapters && ipAdapters.length > 0}
        >
            <div className="space-y-4 pt-2">
                <div className="flex justify-between items-center px-1">
                    <p className="text-xs text-gray-400">
                        Use reference images to guide the generation (style, face, composition).
                    </p>
                    <button
                        onClick={addIpAdapter}
                        className="flex items-center gap-1.5 text-xs font-bold text-pink-400 hover:text-pink-300 transition-colors bg-pink-500/10 hover:bg-pink-500/20 px-3 py-1.5 rounded-lg border border-pink-500/30"
                    >
                        <Plus size={14} /> Add Image Prompt
                    </button>
                </div>

                {ipAdapters && ipAdapters.map((ip, index) => (
                    <div key={index} className="bg-[#0B0E14]/80 p-5 rounded-2xl border border-white/5 shadow-inner space-y-5 transition-all">
                        <div className="flex justify-between items-center">
                            <h4 className="text-sm font-bold text-white tracking-wide">Image Prompt {index + 1}</h4>
                            <button
                                onClick={() => removeIpAdapter(index)}
                                className="text-red-400 hover:text-red-300 p-1.5 hover:bg-red-500/10 rounded-lg transition-colors"
                                title="Remove IP Adapter"
                            >
                                <Trash2 size={16} />
                            </button>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Left: Image Uploader */}
                            <div className="space-y-2">
                                <label className="block text-[11px] font-bold text-gray-400 uppercase tracking-widest px-1">Reference Image</label>
                                <div className="h-48 border border-white/10 rounded-xl overflow-hidden bg-black/40">
                                    <ImageUploader
                                        image={ip.image}
                                        onImageSelect={(img) => updateIpAdapter(index, 'image', img)}
                                        onClear={() => updateIpAdapter(index, 'image', null)}
                                    />
                                </div>
                            </div>

                            {/* Right: Settings */}
                            <div className="space-y-4">
                                <div className="space-y-1.5">
                                    <label className="block text-[11px] font-bold text-pink-400 uppercase tracking-widest px-1">IP-Adapter Model</label>
                                    <ModelSelector
                                        label=""
                                        value={ip.model || ''}
                                        selectedModel={{name: ip.model}}
                                        onChange={(m) => updateIpAdapter(index, 'model', m.name)}
                                        directory="models/ipadapter"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <label className="block text-[11px] font-bold text-pink-400 uppercase tracking-widest px-1">CLIP Vision Model</label>
                                    <ModelSelector
                                        label=""
                                        value={ip.clipVision || ''}
                                        selectedModel={{name: ip.clipVision}}
                                        onChange={(m) => updateIpAdapter(index, 'clipVision', m.name)}
                                        directory="models/clip_vision"
                                    />
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-1.5">
                                        <div className="flex justify-between items-center px-1">
                                            <label className="text-[11px] font-bold text-pink-400 uppercase tracking-widest">Weight</label>
                                            <span className="text-[11px] text-gray-400 font-mono">{Number(ip.weight).toFixed(2)}</span>
                                        </div>
                                        <input
                                            type="range"
                                            min="0" max="2" step="0.05"
                                            value={ip.weight}
                                            onChange={(e) => updateIpAdapter(index, 'weight', parseFloat(e.target.value))}
                                            className="w-full accent-pink-500"
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <div className="flex justify-between items-center px-1">
                                            <label className="text-[11px] font-bold text-pink-400 uppercase tracking-widest">Ends At</label>
                                            <span className="text-[11px] text-gray-400 font-mono">{Number(ip.stopAt).toFixed(2)}</span>
                                        </div>
                                        <input
                                            type="range"
                                            min="0" max="1" step="0.05"
                                            value={ip.stopAt}
                                            onChange={(e) => updateIpAdapter(index, 'stopAt', parseFloat(e.target.value))}
                                            className="w-full accent-pink-500"
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </CollapsibleSection>
    );
});

export default IPAdapterSection;
