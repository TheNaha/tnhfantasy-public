import { X, TrendingUp, Image, CheckCircle, Clock, Sparkles, Loader2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';

const StatsPanel = ({ isOpen, onClose }) => {
    // Fetch statistics from the new API endpoint
    const { data: stats, isLoading, error } = useQuery({
        queryKey: ['statistics'],
        queryFn: async () => {
            const res = await fetch('/api/statistics');
            if (!res.ok) throw new Error('Failed to fetch statistics');
            return res.json();
        },
        enabled: isOpen, // Only fetch when panel is open
        staleTime: 30000, // Cache for 30 seconds
    });

    return (
        <AnimatePresence>
            {isOpen && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80"
                    onClick={onClose}
                >
                    <motion.div
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.9 }}
                        transition={{ duration: 0.2 }}
                        onClick={(e) => e.stopPropagation()}
                        className="glass rounded-2xl w-full max-w-3xl max-h-[80vh] overflow-hidden flex flex-col"
                    >
                        {/* Header */}
                        <div className="p-6 border-b border-gray-700/50">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className="p-2 bg-blue-500/20 rounded-lg">
                                        <TrendingUp className="text-blue-500" size={24} />
                                    </div>
                                    <div>
                                        <h2 className="text-2xl font-bold text-white">
                                            Generation Statistics
                                        </h2>
                                        <p className="text-sm text-gray-400">
                                            Based on your generated images
                                        </p>
                                    </div>
                                </div>
                                <button
                                    onClick={onClose}
                                    className="p-2 hover:bg-gray-700/50 rounded-full text-gray-400 hover:text-white transition-colors"
                                >
                                    <X size={24} />
                                </button>
                            </div>
                        </div>

                        {/* Content */}
                        <div className="flex-1 overflow-y-auto p-6 space-y-6">
                            {isLoading ? (
                                <div className="flex items-center justify-center h-64">
                                    <Loader2 className="animate-spin text-blue-500" size={48} />
                                </div>
                            ) : error || !stats ? (
                                // Graceful fallback - show zero stats with helpful message
                                <>
                                    {/* Info Message */}
                                    <div className="glass p-4 rounded-xl border border-yellow-500/30 bg-yellow-500/10">
                                        <div className="flex items-start gap-3">
                                            <Sparkles className="text-yellow-500 mt-0.5" size={20} />
                                            <div className="flex-1">
                                                <h4 className="font-semibold text-yellow-500 mb-1">
                                                    {error ? 'Statistics Temporarily Unavailable' : 'No Statistics Yet'}
                                                </h4>
                                                <p className="text-sm text-gray-300">
                                                    Generate new images to see comprehensive statistics with full metadata tracking.
                                                    {error && ' The statistics service will be available once you generate your first image.'}
                                                </p>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Empty Stats Cards */}
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                        <div className="glass p-4 rounded-xl opacity-60">
                                            <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                                <Image size={16} />
                                                <span>Total Images</span>
                                            </div>
                                            <div className="text-3xl font-bold text-white">0</div>
                                        </div>

                                        <div className="glass p-4 rounded-xl opacity-60">
                                            <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                                <CheckCircle size={16} />
                                                <span>Models Used</span>
                                            </div>
                                            <div className="text-3xl font-bold text-white">0</div>
                                        </div>

                                        <div className="glass p-4 rounded-xl opacity-60">
                                            <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                                <Sparkles size={16} />
                                                <span>LoRAs Used</span>
                                            </div>
                                            <div className="text-3xl font-bold text-purple-400">0</div>
                                        </div>

                                        <div className="glass p-4 rounded-xl opacity-60">
                                            <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                                <Clock size={16} />
                                                <span>Avg Time</span>
                                            </div>
                                            <div className="text-3xl font-bold text-blue-400">-</div>
                                        </div>
                                    </div>

                                    {/* Empty state message */}
                                    <div className="glass p-8 rounded-xl text-center">
                                        <TrendingUp className="mx-auto mb-3 text-gray-600" size={48} />
                                        <p className="text-gray-400 mb-2">Start generating images to build your statistics</p>
                                        <p className="text-sm text-gray-500">Each new generation will contribute to your analytics</p>
                                    </div>
                                </>
                            ) : stats ? (
                                <>
                                    {/* Overview Cards */}
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                        <div className="glass p-4 rounded-xl">
                                            <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                                <Image size={16} />
                                                <span>Total Images</span>
                                            </div>
                                            <div className="text-3xl font-bold text-white">{stats.total_images || 0}</div>
                                            {stats.enriched_metadata_count > 0 && (
                                                <div className="text-xs text-green-400 mt-1">
                                                    {stats.enriched_metadata_count} with full metadata
                                                </div>
                                            )}
                                        </div>

                                        <div className="glass p-4 rounded-xl">
                                            <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                                <CheckCircle size={16} />
                                                <span>Models Used</span>
                                            </div>
                                            <div className="text-3xl font-bold text-white">
                                                {Object.keys(stats.models || {}).length}
                                            </div>
                                        </div>

                                        <div className="glass p-4 rounded-xl">
                                            <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                                <Sparkles size={16} />
                                                <span>LoRAs Used</span>
                                            </div>
                                            <div className="text-3xl font-bold text-purple-400">
                                                {Object.keys(stats.loras || {}).length}
                                            </div>
                                        </div>

                                        <div className="glass p-4 rounded-xl">
                                            <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                                <Clock size={16} />
                                                <span>Avg Time</span>
                                            </div>
                                            <div className="text-3xl font-bold text-blue-400">
                                                {stats.avg_generation_time || 0}s
                                            </div>
                                        </div>
                                    </div>

                                    {/* Top Models */}
                                    {Object.keys(stats.models || {}).length > 0 && (
                                        <div className="glass p-6 rounded-xl">
                                            <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                                                <Sparkles size={18} />
                                                Most Used Models
                                            </h3>
                                            <div className="space-y-3">
                                                {Object.entries(stats.models || {}).slice(0, 5).map(([name, count]) => (
                                                    <div key={name}>
                                                        <div className="flex justify-between text-sm mb-2">
                                                            <span className="text-gray-300 truncate flex-1 pr-2">{name}</span>
                                                            <span className="text-blue-400 font-medium">{count}</span>
                                                        </div>
                                                        <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                                                            <div
                                                                className="h-full bg-blue-500"
                                                                style={{
                                                                    width: `${(count / Object.values(stats.models).reduce((a, b) => Math.max(a, b), 1)) * 100}%`
                                                                }}
                                                            />
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* Popular Settings */}
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        {/* Steps */}
                                        {Object.keys(stats.popular_settings?.steps || {}).length > 0 && (
                                            <div className="glass p-4 rounded-xl">
                                                <h4 className="font-semibold text-white mb-3 text-sm">Popular Steps</h4>
                                                <div className="space-y-2">
                                                    {Object.entries(stats.popular_settings.steps).slice(0, 3).map(([steps, count]) => (
                                                        <div key={steps} className="flex justify-between text-sm">
                                                            <span className="text-gray-400">{steps} steps</span>
                                                            <span className="text-white font-medium">{count}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* CFG */}
                                        {Object.keys(stats.popular_settings?.cfg || {}).length > 0 && (
                                            <div className="glass p-4 rounded-xl">
                                                <h4 className="font-semibold text-white mb-3 text-sm">Popular CFG</h4>
                                                <div className="space-y-2">
                                                    {Object.entries(stats.popular_settings.cfg).slice(0, 3).map(([cfg, count]) => (
                                                        <div key={cfg} className="flex justify-between text-sm">
                                                            <span className="text-gray-400">CFG {cfg}</span>
                                                            <span className="text-white font-medium">{count}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Resolution */}
                                        {Object.keys(stats.popular_settings?.resolution || {}).length > 0 && (
                                            <div className="glass p-4 rounded-xl">
                                                <h4 className="font-semibold text-white mb-3 text-sm">Popular Resolutions</h4>
                                                <div className="space-y-2">
                                                    {Object.entries(stats.popular_settings.resolution).slice(0, 3).map(([res, count]) => (
                                                        <div key={res} className="flex justify-between text-sm">
                                                            <span className="text-gray-400">{res}</span>
                                                            <span className="text-white font-medium">{count}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* Top LoRAs */}
                                    {Object.keys(stats.loras || {}).length > 0 && (
                                        <div className="glass p-6 rounded-xl">
                                            <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                                                <Sparkles size={18} />
                                                Most Used LoRAs
                                            </h3>
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                                {Object.entries(stats.loras || {}).slice(0, 6).map(([name, count]) => (
                                                    <div key={name} className="flex justify-between items-center">
                                                        <span className="text-gray-300 truncate flex-1 pr-2 text-sm">{name}</span>
                                                        <span className="text-purple-400 font-medium text-sm">{count}</span>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </>
                            ) : (
                                <div className="flex items-center justify-center h-64">
                                    <p className="text-gray-500">No statistics available</p>
                                </div>
                            )}
                        </div>
                    </motion.div>
                </div>
            )}
        </AnimatePresence>
    );
};

export default StatsPanel;
