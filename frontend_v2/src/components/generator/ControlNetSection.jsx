import { memo } from 'react';
import { Settings2, Plus, Trash2 } from 'lucide-react';
import CollapsibleSection from '../CollapsibleSection';
import filesApi from '../../api/files';
import toast from 'react-hot-toast';

const ControlNetSection = memo(function ControlNetSection({
    controlnets,
    addControlNet,
    removeControlNet,
    updateControlNet,
    controlNetModels,
}) {
    const handleControlNetChange = (index, field, value) => {
        updateControlNet(index, field, value);
    };

    const handleControlNetUpload = async (index, file) => {
        const uploadPromise = filesApi.uploadInput(file);

        toast.promise(uploadPromise, {
            loading: 'Uploading image...',
            success: (data) => {
                if (data.status === 'success') {
                    handleControlNetChange(index, 'image', file.name);
                    return 'Image uploaded!';
                } else {
                    throw new Error('Upload failed');
                }
            },
            error: 'Upload failed'
        });
    };

    return (
        <CollapsibleSection
            title="ControlNet"
            icon={<Settings2 size={20} className="text-green-400" />}
            defaultOpen={controlnets.length > 0}
        >
            <div className="space-y-4 pt-4">
                <div className="flex justify-between items-center px-1">
                    <p className="text-xs text-gray-400">
                        Guide the generation using structural references like edges, poses, or depth maps.
                    </p>
                    <button onClick={() => addControlNet(controlNetModels[0]?.name)} className="text-2xs font-bold uppercase tracking-widest flex items-center gap-1.5 text-green-400 hover:text-green-300 hover:scale-105 transition-all">
                        <Plus size={14} strokeWidth={3} /> Add ControlNet
                    </button>
                </div>

                {controlnets.map((cn, idx) => (
                    <div key={idx} className="space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border border-white/10 relative shadow-inner group/card">
                        <button onClick={() => removeControlNet(idx)} className="absolute top-4 right-4 text-gray-500 hover:text-red-400 transition-colors opacity-0 group-hover/card:opacity-100">
                            <Trash2 size={18} />
                        </button>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                            <div className="space-y-1.5">
                                <label className="block text-2xs font-bold text-green-400 uppercase tracking-widest px-1">Model</label>
                                <select
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-green-500/50 focus:border-green-500/50 outline-none transition-all glow-focus"
                                    value={cn.name}
                                    onChange={(e) => handleControlNetChange(idx, 'name', e.target.value)}
                                >
                                    <option value="">Select Model...</option>
                                    {controlNetModels.map(m => (
                                        <option key={m.name} value={m.name}>{m.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-2xs font-bold text-green-400 uppercase tracking-widest px-1">Strength</label>
                                <input
                                    type="number"
                                    step="0.1"
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-green-500/50 focus:border-green-500/50 outline-none transition-all glow-focus"
                                    value={cn.strength}
                                    onChange={(e) => handleControlNetChange(idx, 'strength', parseFloat(e.target.value))}
                                />
                            </div>
                        </div>

                        <div className="space-y-1.5">
                            <label className="block text-2xs font-bold text-green-400 uppercase tracking-widest px-1">Input Image</label>
                            <div className="flex gap-3 items-center bg-black/20 p-2 rounded-xl border border-white/5">
                                <input
                                    type="file"
                                    className="text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-green-500/10 file:text-green-400 hover:file:bg-green-500/20 transition-all cursor-pointer"
                                    onChange={(e) => e.target.files?.[0] && handleControlNetUpload(idx, e.target.files[0])}
                                />
                                {cn.image && <span className="text-xs text-green-400 font-medium">Uploaded: {cn.image}</span>}
                            </div>
                        </div>

                        <div className="space-y-1.5">
                            <label className="block text-2xs font-bold text-green-400 uppercase tracking-widest px-1">Preprocessor</label>
                            <select
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-green-500/50 focus:border-green-500/50 outline-none transition-all glow-focus"
                                value={cn.preprocessor}
                                onChange={(e) => handleControlNetChange(idx, 'preprocessor', e.target.value)}
                            >
                                <option value="None">None (Raw Image)</option>
                                <option value="Canny">Canny Edge</option>
                                <option value="Depth">Depth</option>
                                <option value="Openpose">OpenPose</option>
                                <option value="Lineart">Lineart</option>
                            </select>
                        </div>
                    </div>
                ))}
            </div>
        </CollapsibleSection>
    );
});

export default ControlNetSection;
