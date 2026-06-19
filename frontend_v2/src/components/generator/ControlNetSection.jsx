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
            <div className="space-y-4">
                <div className="flex justify-end">
                    <button onClick={() => addControlNet(controlNetModels[0]?.name)} className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300">
                        <Plus size={14} /> Add ControlNet
                    </button>
                </div>

                {controlnets.map((cn, idx) => (
                    <div key={idx} className="space-y-3 bg-gray-900/50 p-4 rounded-lg border border-gray-700 relative">
                        <button onClick={() => removeControlNet(idx)} className="absolute top-2 right-2 text-gray-500 hover:text-red-400">
                            <Trash2 size={16} />
                        </button>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs font-medium text-gray-500 mb-1">Model</label>
                                <select
                                    className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white"
                                    value={cn.name}
                                    onChange={(e) => handleControlNetChange(idx, 'name', e.target.value)}
                                >
                                    <option value="">Select Model...</option>
                                    {controlNetModels.map(m => (
                                        <option key={m.name} value={m.name}>{m.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-xs font-medium text-gray-500 mb-1">Strength</label>
                                <input
                                    type="number"
                                    step="0.1"
                                    className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white"
                                    value={cn.strength}
                                    onChange={(e) => handleControlNetChange(idx, 'strength', parseFloat(e.target.value))}
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-gray-500 mb-1">Input Image</label>
                            <div className="flex gap-2 items-center">
                                <input
                                    type="file"
                                    className="text-sm text-gray-400"
                                    onChange={(e) => e.target.files?.[0] && handleControlNetUpload(idx, e.target.files[0])}
                                />
                                {cn.image && <span className="text-xs text-green-400">Uploaded: {cn.image}</span>}
                            </div>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-gray-500 mb-1">Preprocessor</label>
                            <select
                                className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white"
                                value={cn.preprocessor}
                                onChange={(e) => handleControlNetChange(idx, 'preprocessor', e.target.value)}
                            >
                                <option value="None">None (Raw Image)</option>
                                <option value="Canny">Canny Edge</option>
                            </select>
                        </div>
                    </div>
                ))}
            </div>
        </CollapsibleSection>
    );
});

export default ControlNetSection;
