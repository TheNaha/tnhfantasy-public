import { useState } from 'react';
import { Download } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import useReconciliationStore from '../store/reconciliationStore';
import ReconciliationStatus from './providers/ReconciliationStatus';

export default function ReconciliationIndicator() {
    const { activeReconciliations, getActiveCount } = useReconciliationStore();
    const [selectedProviderId, setSelectedProviderId] = useState(null);
    const activeCount = getActiveCount();

    if (activeCount === 0) return null;

    const activeProviders = Object.entries(activeReconciliations);

    return (
        <>
            <AnimatePresence>
                <motion.div
                    initial={{ opacity: 0, y: -20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -20 }}
                    className="fixed top-4 right-4 z-40"
                >
                    <div className="bg-blue-600 text-white rounded-lg shadow-lg p-3 flex items-center gap-3 cursor-pointer hover:bg-blue-700 transition-colors"
                        onClick={() => setSelectedProviderId(activeProviders[0]?.[0])}
                    >
                        <Download size={20} className="animate-pulse" />
                        <div className="text-sm">
                            <div className="font-medium">
                                {activeCount} Reconciliation{activeCount > 1 ? 's' : ''} Active
                            </div>
                            <div className="text-xs text-blue-100">
                                Click to view progress
                            </div>
                        </div>
                        <div className="w-6 h-6 bg-blue-500 rounded-full flex items-center justify-center text-xs font-bold">
                            {activeCount}
                        </div>
                    </div>

                    {/* Mini status for each provider */}
                    {activeProviders.length > 0 && (
                        <div className="mt-2 space-y-2">
                            {activeProviders.map(([providerId, data]) => (
                                <MiniStatus
                                    key={providerId}
                                    providerId={providerId}
                                    data={data}
                                    onClick={() => setSelectedProviderId(providerId)}
                                />
                            ))}
                        </div>
                    )}
                </motion.div>
            </AnimatePresence>

            {/* Full Status Modal */}
            {selectedProviderId && (
                <ReconciliationStatus
                    providerId={selectedProviderId}
                    onClose={() => setSelectedProviderId(null)}
                />
            )}
        </>
    );
}

function MiniStatus({ providerId, data, onClick }) {
    const stats = data.stats || {};
    const total = stats.downloads_queued || 0;
    const completed = stats.downloads_completed || 0;
    const progress = total > 0 ? (completed / total) * 100 : 0;

    return (
        <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            className="bg-gray-800 rounded-lg border border-gray-700 p-3 cursor-pointer hover:border-blue-500 transition-colors"
            onClick={onClick}
        >
            <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-gray-400 font-medium">{providerId}</span>
                <span className="text-xs text-blue-400">
                    {completed}/{total}
                </span>
            </div>

            {/* Progress bar */}
            <div className="w-full bg-gray-700 rounded-full h-1.5 overflow-hidden">
                <motion.div
                    className="h-full bg-blue-500"
                    initial={{ width: 0 }}
                    animate={{ width: `${progress}%` }}
                    transition={{ duration: 0.3 }}
                />
            </div>

            {/* Current download */}
            {data.current_download && (
                <div className="mt-2 text-xs text-gray-400 truncate">
                    {data.current_download.name}
                </div>
            )}
        </motion.div>
    );
}
