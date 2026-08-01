import { useState } from 'react';
import { Plus, X, Search } from 'lucide-react';
import toast from 'react-hot-toast';
import { useAddModelToProviders } from '../../hooks/useProviderModels';
import { PROVIDER_MODEL_DIRECTORIES } from '../../constants/modelDirectories';
import { createPortal } from 'react-dom';

export default function AddModelToProviderModal({ providers, onClose }) {
    const [selectedProviders, setSelectedProviders] = useState([]);
    const [directory, setDirectory] = useState('models/checkpoints');
    const [modelUrl, setModelUrl] = useState('');
    const [modelName, setModelName] = useState('');
    const addModel = useAddModelToProviders();

    const directories = PROVIDER_MODEL_DIRECTORIES;

    const toggleProvider = (providerId) => {
        setSelectedProviders(prev =>
            prev.includes(providerId)
                ? prev.filter(id => id !== providerId)
                : [...prev, providerId]
        );
    };

    const isLlmDir = directory.startsWith('models/llm');
    const filteredProviders = providers.filter(p => {
        const isLlmProvider = p.type === 'llm-local';
        return isLlmDir ? isLlmProvider : !isLlmProvider;
    });

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!modelName || !modelUrl || selectedProviders.length === 0) {
            toast.error('Please fill all fields and select at least one provider');
            return;
        }

        try {
            await addModel.mutateAsync({
                directory,
                modelData: {
                    name: modelName,
                    url: modelUrl,
                    type: directory.split('/')[1],
                },
                providerIds: selectedProviders
            });

            toast.success(`Model added to ${selectedProviders.length} provider(s)!`);
            onClose();
        } catch (error) {
            console.error('Failed to add model:', error);
            toast.error('Failed to add model: ' + error.message);
        }
    };

    return createPortal(
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <div className="bg-gray-800 rounded-xl border border-gray-700 max-w-2xl w-full">
                <div className="border-b border-gray-700 px-6 py-4 flex items-center justify-between">
                    <h2 className="text-xl font-semibold text-white">Add Model to Providers</h2>
                    <button
                        onClick={onClose}
                        className="text-gray-400 hover:text-white transition-colors"
                    >
                        <X size={20} />
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="p-6 space-y-4 md:space-y-6">
                    {/* Model Info */}
                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-2">
                            Model Name
                        </label>
                        <input
                            type="text"
                            value={modelName}
                            onChange={(e) => setModelName(e.target.value)}
                            placeholder="sd_v1.5.safetensors"
                            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-2">
                            Model URL
                        </label>
                        <input
                            type="url"
                            value={modelUrl}
                            onChange={(e) => setModelUrl(e.target.value)}
                            placeholder="https://..."
                            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-2">
                            Directory
                        </label>
                        <select
                            value={directory}
                            onChange={(e) => setDirectory(e.target.value)}
                            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-blue-500 focus:outline-none"
                        >
                            {directories.map(dir => (
                                <option key={dir} value={dir}>
                                    {dir.replace('models/', '')}
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* Provider Selection */}
                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-2">
                            Select Providers
                        </label>
                        <div className="space-y-2 max-h-48 overflow-y-auto custom-scrollbar p-3 bg-gray-900 rounded-lg border border-gray-700">
                            {filteredProviders.length === 0 && (
                                <p className="text-sm text-gray-500 text-center py-4">No eligible providers found for this model type.</p>
                            )}
                            {filteredProviders.map(provider => (
                                <label
                                    key={provider.id}
                                    className="flex items-center gap-3 p-2 hover:bg-gray-800 rounded cursor-pointer transition-colors"
                                >
                                    <input
                                        type="checkbox"
                                        checked={selectedProviders.includes(provider.id)}
                                        onChange={() => toggleProvider(provider.id)}
                                        className="w-4 h-4 text-blue-600 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                                    />
                                    <span className="text-gray-300">{provider.id}</span>
                                    <span className="text-xs text-gray-500">({provider.type})</span>
                                </label>
                            ))}
                        </div>
                        {selectedProviders.length > 0 && (
                            <p className="text-sm text-gray-400 mt-2">
                                {selectedProviders.length} provider(s) selected
                            </p>
                        )}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-3 pt-4 border-t border-gray-700">
                        <button
                            type="button"
                            onClick={onClose}
                            className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={addModel.isPending || selectedProviders.length === 0}
                            className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {addModel.isPending ? 'Adding...' : 'Add Model'}
                        </button>
                    </div>
                </form>
            </div>
        </div>,
        document.body
    );
}
