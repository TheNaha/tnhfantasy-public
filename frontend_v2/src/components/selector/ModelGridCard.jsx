import { memo } from 'react';
import { Check, Layers, ChevronDown } from 'lucide-react';
import toast from 'react-hot-toast';
import {
  availabilityTone,
  formatAvailabilityBadgeLabel,
  getModelAvailabilitySummary,
} from '../../utils/modelAvailability';
import ModelPreviewImage from './ModelPreviewImage';

const ModelGridCard = memo(function ModelGridCard({
  model,
  value,
  isExpanded,
  onExpand,
  onSelect,
  onVersionSelect,
  onAddTriggerWords,
  onApplySDXLSettings,
  showAvailabilityBadge,
  providers,
  providersLoading,
}) {
  const versions = model.versions || [];
  const hasMultipleVersions = versions.length > 1;
  const availability = getModelAvailabilitySummary(
    model.provider_statuses,
    providers,
    { providersLoading },
  );
  const shouldShowAvailability = showAvailabilityBadge && availability.hasStatusData;
  const availabilityLabel = formatAvailabilityBadgeLabel(availability.label);

  const handleClick = () => {
    if (hasMultipleVersions && !isExpanded) {
      onExpand(model.model_id);
      return;
    }
    onSelect(model);

    if (model.trained_words?.length > 0) {
      toast(
        (t) => (
          <div className="flex flex-col gap-2">
            <span className="font-medium">Found trigger words!</span>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  if (onAddTriggerWords) onAddTriggerWords(model.trained_words);
                  toast.dismiss(t.id);
                }}
                className="bg-blue-600 text-white text-xs px-2 py-1 rounded"
              >
                Add to Prompt
              </button>
              <button onClick={() => toast.dismiss(t.id)} className="text-gray-400 text-xs">
                Dismiss
              </button>
            </div>
          </div>
        ),
        { duration: 5000, icon: '💡' },
      );
    }

    if (model.base_model?.includes('SDXL') || model.base_model?.includes('Illustrious')) {
      toast(
        (t) => (
          <div className="flex flex-col gap-2">
            <span className="font-medium">SDXL-Based Model Detected</span>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  if (onApplySDXLSettings) onApplySDXLSettings();
                  toast.dismiss(t.id);
                }}
                className="bg-purple-600 text-white text-xs px-2 py-1 rounded"
              >
                Apply SDXL Settings
              </button>
              <button onClick={() => toast.dismiss(t.id)} className="text-gray-400 text-xs">
                Dismiss
              </button>
            </div>
          </div>
        ),
        { duration: 5000, icon: '⚙️' },
      );
    }
  };

  return (
    <div className="relative">
      {/* Main Model Card */}
      <button
        onClick={handleClick}
        className={`w-full group relative aspect-[2/3] rounded-xl overflow-hidden border text-left transition-all ${
          value === model.name
            ? 'border-blue-500 ring-2 ring-blue-500/50'
            : 'border-gray-800 hover:border-gray-600'
        }`}
      >
        <ModelPreviewImage model={model} size="lg" />

        {/* Overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent p-4 flex flex-col justify-end">
          <div className="font-medium text-white text-sm line-clamp-2 leading-tight">
            {model.display_name || model.name}
          </div>
          <div className="flex items-center gap-2 mt-1">
            {model.size && (
              <span className="text-xs text-gray-400">
                {(model.size / 1024 / 1024 / 1024).toFixed(2)} GB
              </span>
            )}
            {model.default_version && (
              <span className="text-xs text-gray-500">
                {model.default_version}
              </span>
            )}
          </div>
          {shouldShowAvailability && (
            <div className="mt-2">
              <span
                className={`inline-flex items-center rounded-full border px-2 py-0.5 text-2xs font-medium ${availabilityTone(availability.label)}`}
                title={availability.detail || availability.label}
              >
                {availabilityLabel}
              </span>
            </div>
          )}
        </div>

        {/* Version Badge (top-left) */}
        {hasMultipleVersions && (
          <div
            className={`absolute top-2 left-2 flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium shadow-lg transition-colors ${
              isExpanded
                ? 'bg-blue-500 text-white'
                : 'bg-gray-900/80 text-gray-300 hover:bg-gray-800'
            }`}
          >
            <Layers size={12} />
            {versions.length}
            <ChevronDown
              size={12}
              className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`}
            />
          </div>
        )}

        {/* Selected Check */}
        {value === model.name && (
          <div className="absolute top-2 right-2 bg-blue-500 text-white p-1 rounded-full shadow-lg">
            <Check size={14} />
          </div>
        )}
      </button>

      {/* Version Dropdown (expanded) */}
      {isExpanded && hasMultipleVersions && (
        <div className="absolute z-10 left-0 right-0 top-full mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden">
          <div className="p-2 border-b border-gray-700 flex justify-between items-center">
            <span className="text-xs text-gray-400">Select Version</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onExpand(null);
              }}
              className="text-gray-500 hover:text-white text-xs"
              aria-label="Close version selector"
            >
              ✕
            </button>
          </div>
          <div className="max-h-48 overflow-y-auto">
            {versions.map((version) => {
              const file = version.file || {};
              const isDefault = version.is_default;
              return (
                <button
                  key={version.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    onVersionSelect(model, version);
                    onExpand(null);
                  }}
                  className="w-full px-3 py-2 text-left hover:bg-gray-700 flex items-center justify-between gap-2"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white truncate flex items-center gap-2">
                      {version.name}
                      {isDefault && (
                        <span className="text-xs bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">
                          default
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 truncate">
                      {version.base_model || 'Unknown'} •{' '}
                      {file.size_kb
                        ? `${(file.size_kb / 1024 / 1024).toFixed(2)} GB`
                        : ''}
                    </div>
                  </div>
                  {value === file.filename && (
                    <Check size={14} className="text-blue-400 flex-shrink-0" />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
});

export default ModelGridCard;
