import { useState, useMemo } from 'react';
import { X, Search, Loader2, FolderDown, Link as LinkIcon, CheckSquare, Square } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { useAddModelToProviders } from '../../hooks/useProviderModels';
import { providersApi } from '../../api';
import { formatBytes, KB } from '../../utils/bytes';
import { PROVIDER_MODEL_DIRECTORIES } from '../../constants/modelDirectories';
import { createPortal } from 'react-dom';
import { useEscapeKey } from '../../hooks/useEscapeKey';

export default function AddModelToProviderModal({ providers, onClose }) {
    useEscapeKey(onClose);
    const [mode, setMode] = useState('library'); // 'library' | 'custom'
    const [selectedProviders, setSelectedProviders] = useState([]);
    
    // Custom URL Form State
    const [directory, setDirectory] = useState('models/checkpoints');
    const [modelUrl, setModelUrl] = useState('');
    const [modelName, setModelName] = useState('');
    const addModel = useAddModelToProviders();

    // Library Mode State
    const [librarySearch, setLibrarySearch] = useState('');
    const [libraryDir, setLibraryDir] = useState('all');
    const [selectedLibraryFileIds, setSelectedLibraryFileIds] = useState([]);
    const [isSubmittingLibrary, setIsSubmittingLibrary] = useState(false);

    const directories = PROVIDER_MODEL_DIRECTORIES;

    // Fetch library models manifest
    const { data: manifestData, isLoading: manifestLoading, isError: manifestError, refetch: refetchManifest } = useQuery({
        queryKey: ['global-sync-manifest'],
        queryFn: () => providersApi.getSyncManifest(),
        staleTime: 30_000,
    });

    const libraryModels = useMemo(() => manifestData?.models || [], [manifestData]);

    const filteredLibraryModels = useMemo(() => {
        return libraryModels.filter(m => {
            const q = librarySearch.trim().toLowerCase();
            const matchesSearch = !q || (
                (m.model_name && m.model_name.toLowerCase().includes(q)) ||
                (m.version_name && m.version_name.toLowerCase().includes(q)) ||
                (m.storage_filename && m.storage_filename.toLowerCase().includes(q))
            );
            const matchesDir = libraryDir === 'all' || m.directory === libraryDir;
            return matchesSearch && matchesDir;
        });
    }, [libraryModels, librarySearch, libraryDir]);

    const handleDirectoryChange = (event) => {
        setDirectory(event.target.value);
        setSelectedProviders([]);
    };

    const toggleProvider = (providerId) => {
        setSelectedProviders(prev =>
            prev.includes(providerId)
                ? prev.filter(id => id !== providerId)
                : [...prev, providerId]
        );
    };

    const toggleLibraryFile = (fileId) => {
        setSelectedLibraryFileIds(prev =>
            prev.includes(fileId)
                ? prev.filter(id => id !== fileId)
                : [...prev, fileId]
        );
    };

    const toggleSelectAllLibrary = () => {
        if (selectedLibraryFileIds.length === filteredLibraryModels.length) {
            setSelectedLibraryFileIds([]);
        } else {
            setSelectedLibraryFileIds(filteredLibraryModels.map(m => m.file_id));
        }
    };

    const isLlmDir = directory.startsWith('models/llm');
    const filteredProviders = providers.filter(p => {
        const isLlmProvider = p.worker_type === 'llm' || ['llm-local', 'llm-openai-compat', 'llm-anthropic', 'llm-google', 'openai_compat', 'anthropic', 'google', 'ollama', 'modal_llm'].includes(p.type);
        return isLlmDir ? isLlmProvider : !isLlmProvider;
    });

    const handleCustomSubmit = async (e) => {
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
            toast.error('Failed to add model: ' + error.message);
        }
    };

    const handleLibrarySubmit = async (e) => {
        e.preventDefault();

        if (selectedLibraryFileIds.length === 0 || selectedProviders.length === 0) {
            toast.error('Please select at least one model and at least one provider');
            return;
        }

        setIsSubmittingLibrary(true);
        try {
            for (const providerId of selectedProviders) {
                await providersApi.downloadModels(providerId, { file_ids: selectedLibraryFileIds });
            }
            toast.success(`Triggered download of ${selectedLibraryFileIds.length} model(s) to ${selectedProviders.length} provider(s)!`);
            onClose();
        } catch (error) {
            toast.error('Failed to trigger downloads: ' + error.message);
        } finally {
            setIsSubmittingLibrary(false);
        }
    };

    return createPortal(
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <div className="bg-gray-800 rounded-2xl border border-gray-700 max-w-2xl w-full flex flex-col max-h-[90vh] shadow-2xl overflow-hidden">
                {/* Header */}
                <div className="border-b border-gray-700 px-6 py-4 flex items-center justify-between shrink-0">
                    <div>
                        <h2 className="text-lg font-bold text-white">Add Models to Providers</h2>
                        <p className="text-xs text-gray-400 mt-0.5">Populate models to worker storage</p>
                    </div>
                    <button
                        onClick={onClose}
                        aria-label="Close add model to providers"
                        className="text-gray-400 hover:text-white transition-colors p-1 rounded-lg hover:bg-gray-700"
                    >
                        <X size={20} />
                    </button>
                </div>

                {/* Tabs */}
                <div className="flex border-b border-gray-700 bg-gray-900/60 px-6 pt-2 shrink-0">
                    <button
                        type="button"
                        onClick={() => setMode('library')}
                        className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold border-b-2 transition-all ${
                            mode === 'library'
                                ? 'border-blue-500 text-blue-400 bg-blue-500/10 rounded-t-lg'
                                : 'border-transparent text-gray-400 hover:text-gray-200'
                        }`}
                    >
                        <FolderDown size={14} />
                        <span>From Library Catalog</span>
                    </button>
                    <button
                        type="button"
                        onClick={() => setMode('custom')}
                        className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold border-b-2 transition-all ${
                            mode === 'custom'
                                ? 'border-blue-500 text-blue-400 bg-blue-500/10 rounded-t-lg'
                                : 'border-transparent text-gray-400 hover:text-gray-200'
                        }`}
                    >
                        <LinkIcon size={14} />
                        <span>Custom Download URL</span>
                    </button>
                </div>

                {/* Content */}
                <div className="overflow-y-auto p-6 flex-1 custom-scrollbar space-y-5">
                    {mode === 'library' ? (
                        <div className="space-y-4">
                            {/* Library Filters */}
                            <div className="flex gap-2.5">
                                <div className="relative flex-1">
                                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                                    <input
                                        type="text"
                                        placeholder="Search library models..."
                                        value={librarySearch}
                                        onChange={(e) => setLibrarySearch(e.target.value)}
                                        className="w-full bg-gray-900 border border-gray-700 rounded-lg pl-8 pr-3 py-2 text-xs text-white placeholder-gray-500 outline-none focus:border-blue-500"
                                    />
                                </div>
                                <select
                                    value={libraryDir}
                                    onChange={(e) => setLibraryDir(e.target.value)}
                                    className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-300 outline-none focus:border-blue-500"
                                >
                                    <option value="all">All Categories</option>
                                    <option value="checkpoints">Checkpoints</option>
                                    <option value="loras">LoRAs</option>
                                    <option value="embeddings">Embeddings</option>
                                    <option value="vae">VAE</option>
                                    <option value="controlnet">ControlNet</option>
                                </select>
                            </div>

                            {/* Select All Row */}
                            <div className="flex items-center justify-between text-xs text-gray-400 px-1">
                                <button
                                    type="button"
                                    onClick={toggleSelectAllLibrary}
                                    className="flex items-center gap-1.5 hover:text-white transition-colors"
                                >
                                    {selectedLibraryFileIds.length > 0 && selectedLibraryFileIds.length === filteredLibraryModels.length ? (
                                        <CheckSquare size={14} className="text-blue-400" />
                                    ) : (
                                        <Square size={14} />
                                    )}
                                    <span>
                                        {selectedLibraryFileIds.length === filteredLibraryModels.length && filteredLibraryModels.length > 0
                                            ? 'Deselect All'
                                            : 'Select All'}
                                    </span>
                                </button>
                                <span>{selectedLibraryFileIds.length} of {filteredLibraryModels.length} selected</span>
                            </div>

                            {/* Library List */}
                            {manifestLoading ? (
                                <div className="py-12 text-center text-gray-500 flex items-center justify-center gap-2">
                                    <Loader2 size={16} className="animate-spin text-blue-400" />
                                    <span className="text-xs">Loading library catalog...</span>
                                </div>
                            ) : manifestError ? (
                                <div className="py-8 px-4 text-center text-xs border border-dashed border-red-500/40 bg-red-500/10 rounded-xl space-y-2">
                                    <p className="text-red-400">Failed to load library catalog.</p>
                                    <button
                                        type="button"
                                        onClick={() => refetchManifest()}
                                        className="px-3 py-1 bg-gray-800 hover:bg-gray-700 text-white rounded text-xs transition-colors"
                                    >
                                        Retry
                                    </button>
                                </div>
                            ) : filteredLibraryModels.length === 0 ? (
                                <div className="py-8 text-center text-gray-500 text-xs border border-dashed border-gray-700 rounded-xl">
                                    No models matched your search.
                                </div>
                            ) : (
                                <div className="max-h-60 overflow-y-auto custom-scrollbar border border-gray-700 rounded-xl divide-y divide-gray-750 bg-gray-900/60">
                                    {filteredLibraryModels.map((item) => {
                                        const isChecked = selectedLibraryFileIds.includes(item.file_id);
                                        return (
                                            <div
                                                key={item.file_id || item.storage_filename}
                                                onClick={() => toggleLibraryFile(item.file_id)}
                                                className={`p-2.5 flex items-center gap-3 cursor-pointer hover:bg-gray-800 transition-colors ${
                                                    isChecked ? 'bg-blue-600/10' : ''
                                                }`}
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={isChecked}
                                                    onChange={() => {}} // Handled by container onClick
                                                    className="w-4 h-4 text-blue-600 bg-gray-700 border-gray-600 rounded focus:ring-blue-500 pointer-events-none"
                                                />
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center gap-2">
                                                        <span className="text-xs font-semibold text-white truncate" title={item.model_name}>
                                                            {item.model_name}
                                                        </span>
                                                        {item.version_name && (
                                                            <span className="text-2xs px-1.5 py-0.2 rounded bg-gray-700 text-gray-300">
                                                                {item.version_name}
                                                            </span>
                                                        )}
                                                        {item.directory && (
                                                            <span className="text-2xs px-1.5 py-0.2 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                                                                {item.directory}
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="text-2xs text-gray-500 truncate mt-0.5 font-mono">
                                                        {item.storage_filename} • {formatBytes((item.size_kb || 0) * KB)}
                                                    </div>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-bold text-gray-300 mb-1.5 uppercase tracking-wider">
                                    Model Name
                                </label>
                                <input
                                    type="text"
                                    value={modelName}
                                    onChange={(e) => setModelName(e.target.value)}
                                    placeholder="e.g. sd_v1.5.safetensors"
                                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-xs placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-gray-300 mb-1.5 uppercase tracking-wider">
                                    Download URL
                                </label>
                                <input
                                    type="url"
                                    value={modelUrl}
                                    onChange={(e) => setModelUrl(e.target.value)}
                                    placeholder="https://..."
                                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-xs placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-gray-300 mb-1.5 uppercase tracking-wider">
                                    Target Directory
                                </label>
                                <select
                                    value={directory}
                                    onChange={handleDirectoryChange}
                                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-xs focus:border-blue-500 focus:outline-none"
                                >
                                    {directories.map(dir => (
                                        <option key={dir} value={dir}>
                                            {dir.replace('models/', '')}
                                        </option>
                                    ))}
                                </select>
                            </div>
                        </div>
                    )}

                    {/* Target Provider Selection */}
                    <div className="pt-2">
                        <label className="block text-xs font-bold text-gray-300 mb-2 uppercase tracking-wider">
                            Target Providers ({selectedProviders.length} selected)
                        </label>
                        <div className="space-y-1.5 max-h-40 overflow-y-auto custom-scrollbar p-2.5 bg-gray-900/60 rounded-xl border border-gray-700">
                            {filteredProviders.length === 0 && (
                                <p className="text-xs text-gray-500 text-center py-4">No eligible providers found.</p>
                            )}
                            {filteredProviders.map(provider => (
                                <label
                                    key={provider.id}
                                    className="flex items-center gap-2.5 p-2 hover:bg-gray-800 rounded-lg cursor-pointer transition-colors"
                                >
                                    <input
                                        type="checkbox"
                                        checked={selectedProviders.includes(provider.id)}
                                        onChange={() => toggleProvider(provider.id)}
                                        className="w-4 h-4 text-blue-600 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                                    />
                                    <span className="text-xs text-gray-200 font-medium">{provider.id}</span>
                                    <span className="text-2xs text-gray-500 uppercase tracking-wide">({provider.type})</span>
                                </label>
                            ))}
                        </div>
                    </div>
                </div>

                {/* Footer Actions */}
                <div className="flex items-center gap-3 p-4 border-t border-gray-700 bg-gray-900/40 shrink-0">
                    <button
                        type="button"
                        onClick={onClose}
                        className="flex-1 px-4 py-2.5 bg-gray-700 hover:bg-gray-600 text-white text-xs font-bold rounded-xl transition-colors"
                    >
                        Cancel
                    </button>
                    {mode === 'library' ? (
                        <button
                            type="button"
                            onClick={handleLibrarySubmit}
                            disabled={isSubmittingLibrary || selectedLibraryFileIds.length === 0 || selectedProviders.length === 0}
                            className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md active:scale-95 flex items-center justify-center gap-2"
                        >
                            {isSubmittingLibrary ? (
                                <>
                                    <Loader2 size={14} className="animate-spin" />
                                    <span>Triggering...</span>
                                </>
                            ) : (
                                <span>Download to {selectedProviders.length} Provider(s)</span>
                            )}
                        </button>
                    ) : (
                        <button
                            type="button"
                            onClick={handleCustomSubmit}
                            disabled={addModel.isPending || selectedProviders.length === 0}
                            className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md active:scale-95"
                        >
                            {addModel.isPending ? 'Adding...' : 'Add Custom Model'}
                        </button>
                    )}
                </div>
            </div>
        </div>,
        document.body
    );
}
