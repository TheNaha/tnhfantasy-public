import { useState, useEffect, useRef, useCallback } from 'react';
import { X, Loader2, Check, ExternalLink, Wand2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../api';
import * as ws from '../../api/websocket';

function CandidateSelector({ model, isAllowedToFetch, onFetchComplete, onDecision }) {
    const [candidates, setCandidates] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedId, setSelectedId] = useState(null);
    const hasFetched = useRef(false);

    useEffect(() => {
        if (!isAllowedToFetch || hasFetched.current) return;
        hasFetched.current = true;
        
        api.get(`/api/v2/models/${model.id}/autopopulate-candidates`)
            .then(res => {
                setCandidates(res.candidates || []);
                if (res.candidates?.length > 0) {
                    setSelectedId(res.candidates[0].civitai_model.id);
                }
                setLoading(false);
                onFetchComplete();
            })
            .catch(err => {
                setError(err.message);
                setLoading(false);
                onFetchComplete();
            });
    }, [model.id, isAllowedToFetch, onFetchComplete]);

    if (loading) {
        return (
            <div className="flex items-center gap-3 text-gray-400 py-2">
                <Loader2 className="animate-spin" size={16} />
                <span className="text-sm">Fetching candidates for {model.name}...</span>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex items-center justify-between bg-red-900/20 border border-red-700/30 rounded p-3">
                <div>
                    <p className="text-red-400 text-sm font-medium">{model.name}</p>
                    <p className="text-red-500/70 text-xs">{error}</p>
                </div>
                <button
                    onClick={() => onDecision(model.id, null, 'skip')}
                    className="px-3 py-1 bg-gray-800 hover:bg-gray-700 rounded text-xs transition-colors"
                >
                    Skip
                </button>
            </div>
        );
    }

    if (candidates.length === 0) {
        return (
            <div className="flex items-center justify-between bg-gray-800/40 border border-gray-700/50 rounded p-3">
                <div>
                    <p className="text-gray-300 text-sm font-medium">{model.name}</p>
                    <p className="text-gray-500 text-xs">No matches found automatically.</p>
                </div>
                <button
                    onClick={() => onDecision(model.id, null, 'skip')}
                    className="px-3 py-1 bg-gray-800 hover:bg-gray-700 rounded text-xs transition-colors"
                >
                    Skip
                </button>
            </div>
        );
    }

    return (
        <div className="bg-gray-800/60 border border-gray-700 rounded p-3 space-y-3">
            <div className="flex items-start justify-between">
                <div>
                    <p className="text-white text-sm font-medium leading-tight">{model.name}</p>
                    <p className="text-gray-500 text-[10px] mt-0.5">{model.directory}</p>
                </div>
                <div className="flex gap-2 shrink-0">
                    <button
                        onClick={() => onDecision(model.id, null, 'skip')}
                        className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs transition-colors"
                    >
                        Skip
                    </button>
                    <button
                        onClick={() => onDecision(model.id, selectedId, 'approve')}
                        disabled={!selectedId}
                        className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded text-xs transition-colors flex items-center gap-1"
                    >
                        <Check size={14} /> Approve
                    </button>
                </div>
            </div>

            <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin scrollbar-thumb-gray-600">
                {candidates.map(c => {
                    const cm = c.civitai_model;
                    const isSelected = selectedId === cm.id;
                    const imageUrl = cm.modelVersions?.[0]?.images?.[0]?.url;
                    
                    return (
                        <div
                            key={cm.id}
                            onClick={() => setSelectedId(cm.id)}
                            className={`shrink-0 w-48 p-2 rounded cursor-pointer border flex flex-col gap-2 ${isSelected ? 'border-blue-500 bg-blue-500/10' : 'border-gray-700 bg-gray-800 hover:border-gray-500'}`}
                        >
                            {imageUrl && (
                                <div className="w-full aspect-square bg-gray-900 rounded overflow-hidden relative border border-gray-700/50">
                                    <img src={imageUrl} alt={cm.name} className="w-full h-full object-cover" />
                                </div>
                            )}
                            <div>
                                <p className="text-xs text-white font-medium line-clamp-1" title={cm.name}>{cm.name}</p>
                                <p className="text-[10px] text-gray-400 mt-1 flex justify-between items-center">
                                    <span>{c.score}% Match</span>
                                    <a href={`https://civitai.com/models/${cm.id}`} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline inline-flex items-center gap-1" onClick={e => e.stopPropagation()}>
                                        View <ExternalLink size={10} />
                                    </a>
                                </p>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export default function BatchAutopopulateModal({ onClose }) {
    const [pendingModels, setPendingModels] = useState([]);
    const [loading, setLoading] = useState(true);
    const [processingId, setProcessingId] = useState(null);
    const [allowedToFetchCount, setAllowedToFetchCount] = useState(1);
    const [autoProgress, setAutoProgress] = useState(null);
    const [isAutoPopulatingAll, setIsAutoPopulatingAll] = useState(false);

    useEffect(() => {
        const handleProgress = (payload) => {
            setAutoProgress(payload);
            if (payload.status === 'completed') {
                toast.success('Batch autopopulation complete!');
                setIsAutoPopulatingAll(false);
                setTimeout(() => {
                    onClose(); // close modal when done
                }, 1500);
            }
        };

        ws.on('AUTOPOPULATE_PROGRESS', handleProgress);
        return () => ws.off('AUTOPOPULATE_PROGRESS', handleProgress);
    }, [onClose]);

    useEffect(() => {
        api.get('/api/v2/models/autopopulate-pending')
            .then(res => {
                setPendingModels(res.pending || []);
                setLoading(false);
            })
            .catch(err => {
                toast.error("Failed to load pending models: " + err.message);
                setLoading(false);
            });
    }, []);

    const handleDecision = async (modelId, civitaiId, action) => {
        if (action === 'approve') {
            setProcessingId(modelId);
            try {
                await api.post(`/api/v2/models/${modelId}/autopopulate`, { civitai_id: civitaiId });
                toast.success('Metadata applied!');
            } catch (err) {
                toast.error('Failed to apply metadata: ' + err.message);
            } finally {
                setProcessingId(null);
            }
        }
        
        // Remove from list regardless of approve/skip
        setPendingModels(prev => prev.filter(m => m.id !== modelId));
        setAllowedToFetchCount(prev => Math.max(1, prev - 1));
    };

    const handleFetchComplete = useCallback(() => {
        setAllowedToFetchCount(prev => prev + 1);
    }, []);

    const handleAutoPopulateAll = async () => {
        setIsAutoPopulatingAll(true);
        try {
            const res = await api.post('/api/v2/models/autopopulate-all');
            if (res.status === 'completed') {
                toast.success('Batch autopopulation complete!');
                setIsAutoPopulatingAll(false);
                onClose();
            } else if (res.status === 'processing') {
                setAutoProgress({ status: 'processing', processed: 0, total: pendingModels.length, current_model: 'Starting...' });
            }
        } catch (err) {
            toast.error('Failed to start batch autopopulation: ' + err.message);
            setIsAutoPopulatingAll(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm" onClick={onClose}>
            <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-3xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
                <div className="p-5 border-b border-gray-800 flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-white flex items-center gap-2">
                            <Wand2 size={20} className="text-purple-400" />
                            Batch Autopopulate
                        </h2>
                        <p className="text-sm text-gray-400 mt-1">
                            Review and approve matching candidates for your auto-discovered models.
                        </p>
                    </div>
                    <div className="flex items-center gap-3">
                        {!autoProgress && pendingModels.length > 0 && (
                            <button
                                onClick={handleAutoPopulateAll}
                                disabled={isAutoPopulatingAll || loading}
                                className="px-4 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                            >
                                {isAutoPopulatingAll ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />}
                                Auto-Populate All
                            </button>
                        )}
                        <button onClick={onClose} className="p-2 hover:bg-gray-800 rounded-full transition-colors">
                            <X size={20} />
                        </button>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-5">
                    {autoProgress ? (
                        <div className="flex flex-col items-center justify-center py-12">
                            <Wand2 className="text-purple-500 mb-6 animate-pulse" size={48} />
                            <h3 className="text-white text-xl font-bold mb-2">Populating Metadata...</h3>
                            <p className="text-gray-400 mb-8">{autoProgress.current_model}</p>
                            
                            <div className="w-full max-w-md bg-gray-800 rounded-full h-3 mb-2 overflow-hidden border border-gray-700">
                                <div 
                                    className="bg-purple-500 h-full transition-all duration-300"
                                    style={{ width: `${Math.max(5, (autoProgress.processed / Math.max(1, autoProgress.total)) * 100)}%` }}
                                ></div>
                            </div>
                            <div className="flex justify-between w-full max-w-md text-xs text-gray-500">
                                <span>{autoProgress.processed} / {autoProgress.total} processed</span>
                                <span>{Math.round((autoProgress.processed / Math.max(1, autoProgress.total)) * 100)}%</span>
                            </div>

                            <div className="mt-8 flex gap-4 text-sm">
                                <div className="bg-gray-800/50 px-4 py-2 rounded-lg border border-green-900/30">
                                    <span className="text-green-400 font-bold">{autoProgress.results?.success || 0}</span> Success
                                </div>
                                <div className="bg-gray-800/50 px-4 py-2 rounded-lg border border-red-900/30">
                                    <span className="text-red-400 font-bold">{autoProgress.results?.failed || 0}</span> Failed
                                </div>
                                <div className="bg-gray-800/50 px-4 py-2 rounded-lg border border-yellow-900/30">
                                    <span className="text-yellow-400 font-bold">{autoProgress.results?.not_found || 0}</span> Not Found
                                </div>
                            </div>
                        </div>
                    ) : loading ? (
                        <div className="flex flex-col items-center justify-center py-12 text-gray-400">
                            <Loader2 className="animate-spin mb-4" size={32} />
                            <p>Finding models that need metadata...</p>
                        </div>
                    ) : pendingModels.length === 0 ? (
                        <div className="text-center py-12">
                            <Wand2 className="mx-auto mb-4 text-gray-600" size={48} />
                            <p className="text-gray-300 font-medium text-lg">All Caught Up!</p>
                            <p className="text-gray-500 mt-1">No auto-discovered models left to process.</p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <p className="text-sm text-gray-400 font-medium">{pendingModels.length} models remaining</p>
                            {pendingModels.map((model, index) => (
                                <div key={model.id} className="relative">
                                    {processingId === model.id && (
                                        <div className="absolute inset-0 z-10 bg-gray-900/50 backdrop-blur-sm flex items-center justify-center rounded">
                                            <Loader2 className="animate-spin text-blue-500" size={24} />
                                        </div>
                                    )}
                                    <CandidateSelector 
                                        model={model} 
                                        isAllowedToFetch={index < allowedToFetchCount}
                                        onFetchComplete={handleFetchComplete}
                                        onDecision={handleDecision} 
                                    />
                                </div>
                            ))}
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
