import { useEffect, useState } from 'react';
import { Download, Image as ImageIcon, Check } from 'lucide-react';
import { api } from '../../api';

export default function ModelCard({ model, onSelect, source }) {
    const [installedInfo, setInstalledInfo] = useState(null);

    useEffect(() => {
        // Check if model is already installed (CivitAI only)
        if (source === 'civitai' && model.id) {
            api.get(`/api/v2/models/check-installed/${model.id}`)
                .then(data => setInstalledInfo(data))
                .catch(() => setInstalledInfo(null));
        }
    }, [model.id, source]);

    const getPreviewImage = () => {
        if (source === 'civitai' && model.id) {
            return `/api/v2/models/preview/${model.id}`;
        }
        if (model.modelVersions?.[0]?.images?.length > 0) {
            return model.modelVersions[0].images[0].url;
        }
        return null;
    };

    const previewImage = getPreviewImage();
    const isInstalled = installedInfo?.model_installed;

    return (
        <div
            className={`group relative bg-gray-900 rounded-xl overflow-hidden border transition-all cursor-pointer ${isInstalled
                    ? 'border-green-500/50 hover:border-green-500'
                    : 'border-gray-800 hover:border-blue-500'
                }`}
            onClick={() => onSelect(model)}
        >
            <div className="aspect-[2/3] bg-gray-800 relative">
                {previewImage ? (
                    <img
                        src={previewImage}
                        alt={model.name}
                        className="absolute inset-0 w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                        loading="lazy"
                        onError={(e) => {
                            e.target.style.display = 'none';
                        }}
                    />
                ) : (
                    <div className="absolute inset-0 flex items-center justify-center text-gray-600">
                        <ImageIcon size={48} className="opacity-30" />
                    </div>
                )}

                {/* Installed badge */}
                {isInstalled && (
                    <div className="absolute top-2 right-2 bg-green-500 text-white px-2 py-1 rounded-full text-xs font-medium flex items-center gap-1 shadow-lg">
                        <Check size={12} />
                        Installed
                    </div>
                )}

                {/* Hover overlay */}
                <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center p-4">
                    <div className="text-center text-white">
                        <Download size={24} className="mx-auto mb-2" />
                        <span className="text-sm font-medium">
                            {isInstalled ? 'View / Add Version' : 'Click to View Details'}
                        </span>
                    </div>
                </div>
            </div>
            <div className="p-3">
                <h3 className="font-medium text-white truncate" title={model.name}>
                    {model.name}
                </h3>
                <div className="flex justify-between items-center mt-1">
                    <span className="text-xs text-gray-500">{model.type}</span>
                    {model.stats && (
                        <div className="flex items-center gap-1 text-xs text-yellow-500">
                            <span>★</span>
                            <span>
                                {source === 'civitai'
                                    ? (model.stats.rating?.toFixed(1) || 'N/A')
                                    : (model.stats.thumbsUpCount?.toLocaleString() || '0')}
                            </span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
