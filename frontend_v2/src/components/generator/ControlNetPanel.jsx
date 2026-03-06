import React from 'react';
import { Settings2, Plus, Trash2 } from 'lucide-react';
import { useGeneratorStore } from '../../store/generatorStore';
import toast from 'react-hot-toast';
import { api } from '../../api';

export default function ControlNetPanel({ controlNetModels }) {
    const {
        controlnets, addControlNet, removeControlNet, updateControlNet
    } = useGeneratorStore();

    const handleControlNetUpload = async (index, file) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('path', 'input'); // Upload to input directory

        const uploadPromise = api.post('/api/upload', formData);

        toast.promise(uploadPromise, {
            loading: 'Uploading image...',
            success: (data) => {
                if (data.status === 'success') {
                    updateControlNet(index, 'image', file.name);
                    return 'Image uploaded!';
                } else {
                    throw new Error('Upload failed');
                }
            },
            error: 'Upload failed'
        });
    };

    return (
        <div className="bg-gray-800/50 backdrop-blur-sm p-6 rounded-xl border border-gray-700/50 space-y-6 shadow-lg">
            <div className="flex justify-between items-center">
                <h3 className="text-lg font-semibold flex items-center gap-2 text-white">
                    <Settings2 size={20} className="text-green-400" />
                    ControlNet
                </h3>
                <button onClick={() => addControlNet(controlNetModels[0]?.name)} className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300 transition-colors">
                    <Plus size={14} /> Add ControlNet
                </button>
            </div>

            {controlnets.map((cn, idx) => (
                <div key={idx} className="space-y-3 bg-gray-900/30 p-4 rounded-lg border border-gray-700/50 relative hover:border-gray-600 transition-colors">
                    <button onClick={() => removeControlNet(idx)} className="absolute top-2 right-2 text-gray-500 hover:text-red-400 transition-colors">
                        <Trash2 size={16} />
                    </button>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs font-medium text-gray-500 mb-1">Model</label>
                            <select
                                className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white focus:ring-1 focus:ring-blue-500 outline-none"
                                value={cn.name}
                                onChange={(e) => updateControlNet(idx, 'name', e.target.value)}
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
                                className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white focus:ring-1 focus:ring-blue-500 outline-none"
                                value={cn.strength}
                                onChange={(e) => updateControlNet(idx, 'strength', parseFloat(e.target.value))}
                            />
                        </div>
                    </div>

                    <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Input Image</label>
                        <div className="flex gap-2 items-center">
                            <input
                                type="file"
                                className="text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-500/10 file:text-blue-400 hover:file:bg-blue-500/20"
                                onChange={(e) => e.target.files?.[0] && handleControlNetUpload(idx, e.target.files[0])}
                            />
                            {cn.image && <span className="text-xs text-green-400">Uploaded: {cn.image}</span>}
                        </div>
                    </div>

                    <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Preprocessor</label>
                        <select
                            className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white focus:ring-1 focus:ring-blue-500 outline-none"
                            value={cn.preprocessor}
                            onChange={(e) => updateControlNet(idx, 'preprocessor', e.target.value)}
                        >
                            <option value="None">None (Raw Image)</option>
                            <option value="Canny">Canny Edge</option>
                        </select>
                    </div>
                </div>
            ))}
        </div>
    );
}
