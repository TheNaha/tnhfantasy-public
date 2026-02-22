import { useState } from 'react';
import { ChevronDown, ChevronUp, Trash2, RefreshCw, CheckCircle, Clock, Download, XCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { useRemoveModelFromProvider } from '../../hooks/useProviderModels';
import { useConfirmation } from '../../context/ConfirmationContext';

const STATUS_ICONS = {
    installed: { icon: CheckCircle, color: 'text-green-400' },
    pending: { icon: Clock, color: 'text-yellow-400' },
    downloading: { icon: Download, color: 'text-blue-400 animate-pulse' },
    failed: { icon: XCircle, color: 'text-red-400' },
};

export default function ProviderModelList({ providerId, models }) {
    const [expanded, setExpanded] = useState(false);
    const removeModel = useRemoveModelFromProvider();
    const { confirm } = useConfirmation();

    if (!models || Object.keys(models).length === 0) {
        return null;
    }

    // Count total models
    const totalModels = Object.values(models).reduce((sum, arr) => sum + arr.length, 0);

    const handleRemove = async (directory, modelName) => {
        const confirmed = await confirm({
            title: 'Remove Model',
            message: `Remove ${modelName} from this provider?`,
            confirmText: 'Remove',
            isDangerous: true
        });
        if (!confirmed) return;

        try {
            await removeModel.mutateAsync({ directory, modelName, providerId });
            toast.success(`Removed ${modelName}`);
        } catch (error) {
            console.error('Failed to remove model:', error);
            toast.error('Failed to remove model: ' + error.message);
        }
    };

    return (
        <div className="border-t border-gray-700 pt-4 mt-4">
            <button
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between text-sm font-medium text-gray-300 hover:text-white transition-colors"
            >
                <span>Models ({totalModels})</span>
                {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>

            {expanded && (
                <div className="mt-4 space-y-4 max-h-96 overflow-y-auto custom-scrollbar">
                    {Object.entries(models).map(([directory, modelList]) => (
                        <div key={directory}>
                            <div className="text-xs text-gray-500 mb-2 font-medium">
                                {directory.replace('models/', '')}
                            </div>
                            <div className="space-y-2">
                                {modelList.map((model) => {
                                    const status = model.provider_status?.status || 'unknown';
                                    const StatusIcon = STATUS_ICONS[status]?.icon || Clock;
                                    const iconColor = STATUS_ICONS[status]?.color || 'text-gray-400';

                                    return (
                                        <div
                                            key={model.name}
                                            className="flex items-center gap-3 bg-gray-800/50 px-3 py-2 rounded border border-gray-700 hover:border-gray-600 transition-colors group"
                                        >
                                            <StatusIcon className={`${iconColor} flex-shrink-0`} size={14} />

                                            <div className="flex-1 min-w-0">
                                                <div className="text-sm text-gray-300 truncate">
                                                    {model.name}
                                                </div>
                                                {model.size && (
                                                    <div className="text-xs text-gray-500">
                                                        {(model.size / 1024 / 1024 / 1024).toFixed(2)} GB
                                                    </div>
                                                )}
                                            </div>

                                            <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                {status === 'failed' && (
                                                    <button
                                                        className="p-1 hover:bg-blue-500/20 rounded text-blue-400"
                                                        title="Retry"
                                                    >
                                                        <RefreshCw size={14} />
                                                    </button>
                                                )}
                                                <button
                                                    onClick={() => handleRemove(directory, model.name)}
                                                    className="p-1 hover:bg-red-500/20 rounded text-red-400"
                                                    title="Remove from provider"
                                                    disabled={removeModel.isPending}
                                                >
                                                    <Trash2 size={14} />
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
