import { useState, useEffect } from 'react';
import { X, Loader2, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../api';
import * as ws from '../../api/websocket';
import { useQueryClient } from '@tanstack/react-query';

export default function BatchResyncModal({ onClose }) {
    const [progress, setProgress] = useState(null);
    const [isProcessing, setIsProcessing] = useState(false);
    const queryClient = useQueryClient();

    useEffect(() => {
        const handleProgress = (payload) => {
            setProgress(payload);
            if (payload.status === 'completed') {
                toast.success('Batch resync complete!');
                setIsProcessing(false);
                queryClient.invalidateQueries({ queryKey: ['models'] });
                setTimeout(() => {
                    onClose();
                }, 1500);
            }
        };

        ws.on('RESYNC_PROGRESS', handleProgress);
        return () => ws.off('RESYNC_PROGRESS', handleProgress);
    }, [onClose, queryClient]);

    const handleStartResync = async () => {
        setIsProcessing(true);
        try {
            const res = await api.post('/api/v2/models/maintenance/resync-all');
            if (res.status === 'no_models') {
                toast.success('No models need resyncing.');
                setIsProcessing(false);
                onClose();
            } else if (res.status === 'processing') {
                setProgress({ status: 'processing', processed: 0, total: res.count, current_model: 'Starting...' });
            }
        } catch (err) {
            toast.error('Failed to start batch resync: ' + err.message);
            setIsProcessing(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm" onClick={onClose}>
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
                    <button onClick={onClose} className="p-2 hover:bg-gray-800 rounded-full transition-colors">
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
                        </div>
                    ) : (
                        <div className="text-center py-6">
                            <p className="text-gray-300 mb-6">
                                This will query CivitAI for the latest names, descriptions, and tags for all models in your database that are linked to a CivitAI ID.
                            </p>
                            <button
                                onClick={handleStartResync}
                                disabled={isProcessing}
                                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-xl font-medium transition-colors flex items-center gap-2 mx-auto"
                            >
                                {isProcessing ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
                                Start Resync
                            </button>
                        </div>
                    )}
                </div>

                <div className="p-4 border-t border-gray-800 bg-gray-900 rounded-b-2xl flex justify-end">
                    <button onClick={onClose} className="px-5 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-xl text-sm transition-colors">
                        Close
                    </button>
                </div>
            </div>
        </div>
    );
}
