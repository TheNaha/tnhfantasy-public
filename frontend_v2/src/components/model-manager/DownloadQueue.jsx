import { useEffect } from 'react';
import { X, Loader2, Check, AlertCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { useDownloadStore } from '../../store/downloadStore';

export default function DownloadQueue() {
    const { downloads, connect, disconnect, clearDownload } = useDownloadStore();

    // Connect to SSE on mount
    useEffect(() => {
        connect();
        return () => disconnect();
    }, [connect, disconnect]);

    const handleClear = async (id) => {
        await clearDownload(id);
    };

    const handleRetry = async (download) => {
        try {
            toast.loading('Retrying download...');
            await handleClear(download.id);
            toast.success('Cleared failed download. Please try downloading again.');
        } catch (e) {
            toast.error('Failed to retry');
        }
    };

    const formatBytes = (bytes) => {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    };

    const formatTime = (seconds) => {
        if (!seconds || seconds < 0 || !isFinite(seconds)) return '--';
        if (seconds < 60) return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
        return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    };

    const calculateETA = (download) => {
        if (!download.speed || download.percent >= 100 || download.status !== 'downloading') return null;

        const speedMatch = download.speed?.match(/([\d.]+)\s*(KB|MB|GB)\/s/i);
        if (!speedMatch) return null;

        const speedValue = parseFloat(speedMatch[1]);
        const speedUnit = speedMatch[2].toUpperCase();

        let bytesPerSecond = speedValue;
        if (speedUnit === 'KB') bytesPerSecond *= 1024;
        else if (speedUnit === 'MB') bytesPerSecond *= 1024 * 1024;
        else if (speedUnit === 'GB') bytesPerSecond *= 1024 * 1024 * 1024;

        const totalBytes = download.total_size || 0;
        const downloadedBytes = (download.percent / 100) * totalBytes;
        const remainingBytes = totalBytes - downloadedBytes;

        if (bytesPerSecond <= 0) return null;

        const etaSeconds = remainingBytes / bytesPerSecond;
        return formatTime(etaSeconds);
    };

    return (
        <div className="flex-1 overflow-y-auto space-y-3 pr-2 min-h-0">
            {downloads.length === 0 ? (
                <div className="text-center text-gray-500 py-10 text-sm">
                    No active downloads
                </div>
            ) : (
                downloads.map(d => {
                    const eta = calculateETA(d);
                    const downloaded = d.total_size ? formatBytes((d.percent / 100) * d.total_size) : null;
                    const total = d.total_size ? formatBytes(d.total_size) : null;

                    return (
                        <div key={d.id} className="bg-gray-900 p-3 rounded-lg border border-gray-700 text-sm overflow-hidden">
                            <div className="flex justify-between items-start mb-2 gap-2">
                                <div className="flex-1 min-w-0">
                                    <span className="font-medium truncate block" title={d.name}>{d.name}</span>
                                    <div className="flex items-center gap-2 mt-1">
                                        {d.status === 'downloading' && (
                                            <span className="text-xs text-blue-400 flex items-center gap-1">
                                                <Loader2 className="animate-spin" size={10} />
                                                Downloading
                                            </span>
                                        )}
                                        {d.status === 'success' && (
                                            <span className="text-xs text-green-400 flex items-center gap-1">
                                                <Check size={10} />
                                                Completed
                                            </span>
                                        )}
                                        {d.status === 'error' && (
                                            <span className="text-xs text-red-400 flex items-center gap-1">
                                                <AlertCircle size={10} />
                                                Failed
                                            </span>
                                        )}
                                    </div>
                                </div>
                                {(d.status === 'success' || d.status === 'error') && (
                                    <button
                                        onClick={() => handleClear(d.id)}
                                        className="text-gray-500 hover:text-white flex-shrink-0"
                                        title="Clear"
                                        aria-label="Clear download task"
                                    >
                                        <X size={14} />
                                    </button>
                                )}
                            </div>

                            {d.status === 'error' ? (
                                <>
                                    <div className="text-red-400 text-xs break-words mb-2">{d.message}</div>
                                    <button
                                        onClick={() => handleRetry(d)}
                                        className="text-xs bg-red-900/30 hover:bg-red-900/50 text-red-300 px-2 py-1 rounded border border-red-800 transition-colors"
                                        aria-label="Retry download"
                                    >
                                        Retry
                                    </button>
                                </>
                            ) : (
                                <>
                                    <div className="w-full bg-gray-800 rounded-full h-1.5 mb-2 overflow-hidden">
                                        <div
                                            className={`h-full transition-all duration-300 ${d.status === 'success' ? 'bg-green-500' : 'bg-blue-500'}`}
                                            style={{ width: `${d.percent}%` }}
                                        />
                                    </div>
                                    <div className="flex justify-between text-xs text-gray-400 mb-1">
                                        <span className="font-medium">{d.percent}%</span>
                                        <span>{d.status === 'success' ? 'Complete' : d.speed || 'Calculating...'}</span>
                                    </div>
                                    {d.status === 'downloading' && (
                                        <div className="flex justify-between text-xs text-gray-500 mt-1 pt-1 border-t border-gray-800">
                                            {downloaded && total && (
                                                <span>{downloaded} / {total}</span>
                                            )}
                                            {eta && (
                                                <span title="Estimated time remaining">ETA: {eta}</span>
                                            )}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    );
                })
            )}
        </div>
    );
}
