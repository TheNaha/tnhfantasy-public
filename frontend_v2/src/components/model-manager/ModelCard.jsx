import { Download, Image as ImageIcon, Check, Heart } from 'lucide-react';

export default function ModelCard({ model, onSelect, source, installedInfo = null }) {

    const directPreviewImage = model.modelVersions?.[0]?.images?.[0]?.url || null;
    const cachedPreviewImage = (source === 'civitai' && model.id)
        ? `/api/v2/models/preview/${model.id}?image_index=0`
        : null;
    const previewImage = directPreviewImage || cachedPreviewImage;
    const isInstalled = installedInfo?.model_installed;

    return (
        <div
            className={`group relative bg-[#0B0E14]/80 rounded-2xl overflow-hidden border transition-all duration-300 cursor-pointer ${isInstalled
                    ? 'border-green-500/30 hover:border-green-500/80 hover:shadow-[0_0_20px_rgba(34,197,94,0.3)]'
                    : 'border-white/5 hover:border-blue-500/50 hover:shadow-[0_0_20px_rgba(59,130,246,0.2)]'
                }`}
            onClick={() => onSelect(model)}
        >
            <div className="aspect-[2/3] bg-[#0B0E14] relative">
                {previewImage ? (
                    <img
                        src={previewImage}
                        alt={model.name}
                        className="absolute inset-0 w-full h-full object-cover group-hover:scale-110 transition-transform duration-700"
                        loading="lazy"
                        decoding="async"
                        fetchPriority="low"
                        onError={(e) => {
                            if (cachedPreviewImage && e.currentTarget.src !== cachedPreviewImage) {
                                e.currentTarget.src = cachedPreviewImage;
                                return;
                            }
                            e.target.style.display = 'none';
                        }}
                    />
                ) : (
                    <div className="absolute inset-0 flex items-center justify-center text-gray-600/50 bg-gradient-to-br from-black/60 to-black/20">
                        <ImageIcon size={48} className="opacity-30" />
                    </div>
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-[#0B0E14] via-[#0B0E14]/60 to-transparent opacity-90 transition-opacity duration-300 group-hover:opacity-75" />

                {/* Installed badge */}
                {isInstalled && (
                    <div className="absolute top-3 right-3 bg-green-500/20 text-green-400 px-3 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-widest border border-green-500/30 shadow-lg flex items-center gap-1.5 backdrop-blur-md">
                        <Check size={14} strokeWidth={3} />
                        Installed
                    </div>
                )}

                {/* Hover overlay */}
                <div className="absolute inset-0 bg-blue-900/40 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center p-4 backdrop-blur-sm">
                    <div className="text-center text-white transform translate-y-4 group-hover:translate-y-0 transition-transform duration-300 drop-shadow-lg">
                        <Download size={32} className="mx-auto mb-3" />
                        <span className="text-sm font-bold tracking-wide">
                            {isInstalled ? 'View / Add Version' : 'Click to View Details'}
                        </span>
                    </div>
                </div>
            </div>
            <div className="absolute bottom-0 left-0 right-0 p-4 transform translate-y-2 group-hover:translate-y-0 transition-transform duration-300">
                <h3 className="font-bold text-white truncate drop-shadow-md tracking-wide" title={model.name}>
                    {model.name}
                </h3>
                <div className="flex justify-between items-center mt-2">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">{model.type}</span>
                    {model.stats && (
                        <div className="flex items-center gap-3 text-xs font-medium text-gray-400">
                            {source === 'civitai' && model.stats.downloadCount !== undefined && (
                                <div className="flex items-center gap-1" title="Downloads">
                                    <Download size={14} className="text-gray-500" />
                                    <span>{model.stats.downloadCount > 1000 ? `${(model.stats.downloadCount / 1000).toFixed(1)}k` : model.stats.downloadCount}</span>
                                </div>
                            )}
                            <div className="flex items-center gap-1.5" title="Likes">
                                <Heart size={14} fill="currentColor" className="text-pink-500" />
                                <span>
                                    {model.stats?.thumbsUpCount?.toLocaleString() || '0'}
                                </span>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
