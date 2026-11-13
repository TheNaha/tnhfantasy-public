import { useState, useEffect } from 'react';
import { X, Loader2, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { QUERY_KEYS } from '../../constants/queryKeys';
import ModalOverlay from '../common/ModalOverlay';
import { api } from '../../api';
import { settingsApi } from '../../api/settingsApi';
import * as ws from '../../api/websocket';
import { useQueryClient } from '@tanstack/react-query';

export default function BatchResyncModal({ onClose }) {
    const [progress, setProgress] = useState(null);
    const [isProcessing, setIsProcessing] = useState(false);
    const [logs, setLogs] = useState([]);
    const queryClient = useQueryClient();

    // Check if background resync is already running on mount
    useEffect(() => {
        let mounted = true;
        settingsApi.getSchedulerStatus()
            .then(res => {
                if (!mounted) return;
                if (res?.resync_status?.in_progress) {
                    setIsProcessing(true);
                    setProgress({
                        status: 'processing',
                        processed: res.resync_status.processed || 0,
                        total: res.resync_status.total || 1,
                        current_model: res.resync_status.current_model || 'Resync in progress...',
                        results: res.resync_status.results || { success: 0, failed: 0, errors: [] },
                    });
                }
            })
            .catch((err) => {
                if (mounted) toast.error(err?.message || 'Failed to load scheduler status');
            });
        return () => { mounted = false; };
    }, []);

    useEffect(() => {
        const handleProgress = (payload) => {
            setProgress(payload);
            
            if (payload.status === 'processing') {
                setLogs(prev => [...prev, `[PROCESSING] Fetching metadata for: ${payload.current_model}`]);
            } else if (payload.status === 'completed') {
                setLogs(prev => [...prev, `[DONE] Batch resync completed! ${payload.results?.success || 0} succeeded, ${payload.results?.failed || 0} failed.`]);
                toast.success('Batch resync complete!');
                setIsProcessing(false);
                queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.MODELS] });
                // Do not auto-close so the user can read the logs.
            }
            
            if (payload.results?.errors && payload.results.errors.length > 0) {
                const latestError = payload.results.errors[payload.results.errors.length - 1];
                setLogs(prev => {
                    const errorMsg = `[ERROR] Failed to fetch: ${latestError.error}`;
                    if (!prev.includes(errorMsg)) {
                        return [...prev, errorMsg];
                    }
                    return prev;
                });
            }
        };

        ws.on('RESYNC_PROGRESS', handleProgress);
        return () => ws.off('RESYNC_PROGRESS', handleProgress);
    }, [queryClient]);

    const handleStartResync = async (mode = 'full', sampleSize = null) => {
        setIsProcessing(true);
        try {
            const res = await api.post('/api/v2/models/maintenance/resync-all', {
                mode,
                sample_size: sampleSize,
            });
            if (res.status === 'no_models') {
                toast.success('No models need resyncing.');
                setIsProcessing(false);
                onClose();
            } else if (res.status === 'already_running') {
                toast('Resync is already in progress.', { icon: 'ℹ️' });
                if (res.progress) {
                    setProgress({
                        status: 'processing',
                        processed: res.progress.processed || 0,
                        total: res.progress.total || 1,
                        current_model: res.progress.current_model || 'Continuing...',
                        results: res.progress.results || { success: 0, failed: 0, errors: [] },
                    });
                }
            } else if (res.status === 'processing') {
                setProgress({
                    status: 'processing',
                    processed: 0,
                    total: res.count,
                    current_model: `Starting ${mode === 'random' ? 'quick batch' : 'full'} resync...`,
                });
            }
        } catch (err) {
            toast.error('Failed to start batch resync: ' + err.message);
            setIsProcessing(false);
        }
    };
    return (
        <ModalOverlay onClose={onClose} className="z-[60] bg-black/80 backdrop-blur-sm">
            <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-lg flex flex-col" onClick={e => e.stopPropagation()}>
                <div className="p-5 border-b border-gray-800 flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-white flex items-center gap-2">
                            <RefreshCw size={20} className="text-blue-400" />
                            Resync All Metadata
                        </h2>
                        <p className="text-sm text-gray-400 mt-1">
                            Fetch fresh metadata for all your installed models from CivitAI.
                        </p>
                    </div>
                    <button onClick={onClose} aria-label="Close resync all metadata" className="p-2 hover:bg-gray-800 rounded-full transition-colors">
                        <X size={20} />
                    </button>
                </div>

                <div className="p-5">
                    {progress ? (
                        <div className="flex flex-col items-center justify-center py-6">
                            <RefreshCw className="text-blue-500 mb-6 animate-spin" size={48} />
                            <h3 className="text-white text-xl font-bold mb-2">Updating Metadata...</h3>
                            <p className="text-gray-400 mb-8 truncate w-full text-center px-4">{progress.current_model}</p>
                            
                            <div className="w-full bg-gray-800 rounded-full h-3 mb-2 overflow-hidden border border-gray-700">
                                <div 
                                    className="bg-blue-500 h-full transition-all duration-300"
                                    style={{ width: `${Math.max(5, (progress.processed / Math.max(1, progress.total)) * 100)}%` }}
                                ></div>
                            </div>
                            <div className="flex justify-between w-full text-xs text-gray-500">
                                <span>{progress.processed} / {progress.total} processed</span>
                                <span>{Math.round((progress.processed / Math.max(1, progress.total)) * 100)}%</span>
                            </div>

                            <div className="mt-8 flex gap-4 text-sm w-full justify-center">
                                <div className="bg-gray-800/50 px-4 py-2 rounded-lg border border-green-900/30">
                                    <span className="text-green-400 font-bold">{progress.results?.success || 0}</span> Success
                                </div>
                                <div className="bg-gray-800/50 px-4 py-2 rounded-lg border border-red-900/30">
                                    <span className="text-red-400 font-bold">{progress.results?.failed || 0}</span> Failed
                                </div>
                            </div>
                            
                            <div className="mt-6 w-full bg-[#0B0E14] rounded-lg border border-gray-800 h-48 overflow-y-auto p-3 text-xs font-mono text-gray-400 flex flex-col gap-1">
                                {logs.length === 0 ? (
                                    <span className="text-gray-600 italic">Waiting for logs...</span>
                                ) : (
                                    logs.map((log, i) => (
                                        <div key={i} className={
                                            log.startsWith('[ERROR]') ? 'text-red-400' : 
                                            log.startsWith('[DONE]') ? 'text-green-400 font-bold' : 
                                            'text-gray-300'
                                        }>
                                            {log}
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="text-center py-4 space-y-6">
                            <p className="text-gray-300 text-sm">
                                Queries CivitAI for latest names, descriptions, triggers, and tags for installed models linked to a CivitAI ID.
                            </p>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-md mx-auto">
                                <button
                                    onClick={() => handleStartResync('random', 5)}
                                    disabled={isProcessing}
                                    className="px-4 py-3 bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-600 disabled:opacity-50 text-white rounded-xl text-left transition-all group"
                                >
                                    <div className="font-semibold text-sm flex items-center justify-between">
                                        <span>Random Batch</span>
                                        <span className="text-xs text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">5 Models</span>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-1">Quick refresh of randomized installed models.</div>
                                </button>
                                <button
                                    onClick={() => handleStartResync('full')}
                                    disabled={isProcessing}
                                    className="px-4 py-3 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/40 hover:border-blue-500/60 disabled:opacity-50 text-white rounded-xl text-left transition-all group"
                                >
                                    <div className="font-semibold text-sm flex items-center justify-between">
                                        <span>Full Deep Resync</span>
                                        <span className="text-xs text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">All Models</span>
                                    </div>
                                    <div className="text-xs text-gray-400 mt-1">Deep crawl across all eligible installed models.</div>
                                </button>
                            </div>
                            <p className="text-xs text-gray-500">
                                Runs safely in the background. You can close this modal at any time.
                            </p>
                        </div>
                    )}
                </div>

                <div className="p-4 border-t border-gray-800 bg-gray-900 rounded-b-2xl flex justify-end">
                    <button onClick={onClose} className="px-5 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-xl text-sm transition-colors">
                        Close
                    </button>
                </div>
            </div>
        </ModalOverlay>
    );
}
