import { memo, useState } from 'react';
import { Check, ChevronDown, Layers, Info, Star } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../api';
import ModelPreviewImage from './ModelPreviewImage';

const TriggerBox = memo(function TriggerBox({
  label,
  selectedModel,
  isOpen,
  onOpen,
  onChange,
  onVersionChange,
  getModelWithVersion,
  onInfoClick,
  onAddTriggerWords,
  directory,
  refetch,
}) {
  const [showVersionDropdown, setShowVersionDropdown] = useState(false);

  if (!selectedModel) return null;

  const hasVersions = selectedModel.versions && selectedModel.versions.length > 1;

  return (
    <div className="relative">
      <div className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 flex items-center gap-3 hover:border-blue-500 transition-colors text-left group">
        {/* Clickable main area */}
        <button
          onClick={onOpen}
          className="flex items-center gap-3 flex-1 min-w-0"
          aria-label={`Select ${label}`}
          aria-haspopup="dialog"
          aria-expanded={isOpen}
        >
          <ModelPreviewImage model={selectedModel} size="sm" />

          {/* Model Name */}
          <div className="flex-1 min-w-0 text-left">
            <div
              className="text-sm font-medium text-white truncate"
              title={selectedModel?.display_name || selectedModel?.name}
            >
              {selectedModel?.display_name || selectedModel?.name || 'Select a model...'}
            </div>
            {selectedModel?.base_model && (
              <div className="text-xs text-gray-500">
                {selectedModel.base_model}
              </div>
            )}
          </div>
        </button>

        {/* Version Selector */}
        {hasVersions && (
          <div className="relative">
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowVersionDropdown(!showVersionDropdown);
              }}
              className={`px-2 py-1 rounded text-xs font-medium flex items-center gap-1 transition-colors ${
                showVersionDropdown
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/50'
                  : 'bg-gray-800 text-gray-400 border border-gray-700 hover:border-purple-500/50 hover:text-purple-300'
              }`}
              title="Switch version"
              aria-label={`Switch version for ${selectedModel.name}`}
              aria-haspopup="true"
              aria-expanded={showVersionDropdown}
            >
              <Layers size={12} />
              <span>{selectedModel.default_version || 'v1'}</span>
              <ChevronDown
                size={12}
                className={`transition-transform ${showVersionDropdown ? 'rotate-180' : ''}`}
              />
            </button>

            {/* Version Dropdown */}
            {showVersionDropdown && (
              <div className="absolute z-50 top-full mt-1 right-0 min-w-[280px] bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden">
                <div className="p-2 border-b border-gray-700 flex justify-between items-center">
                  <span className="text-xs text-gray-400 font-medium">Select Version</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowVersionDropdown(false);
                    }}
                    className="text-gray-500 hover:text-white"
                    aria-label="Close version selector"
                  >
                    ✕
                  </button>
                </div>
                <div className="max-h-64 overflow-y-auto">
                  {selectedModel.versions.map((version) => {
                    const file = version.file || {};
                    const isSelected =
                      selectedModel.selectedVersionId === version.id ||
                      (version.is_default && !selectedModel.selectedVersionId);
                    return (
                      <button
                        key={version.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          const modelWithVersion = getModelWithVersion(
                            selectedModel._originalModel || selectedModel,
                            version,
                          );
                          if (onVersionChange) {
                            onVersionChange(modelWithVersion);
                          } else {
                            onChange(modelWithVersion);
                          }
                          setShowVersionDropdown(false);

                          if (version.trained_words?.length > 0) {
                            toast(
                              (t) => (
                                <div className="flex flex-col gap-2">
                                  <span className="font-medium">Found trigger words!</span>
                                  <div className="flex gap-2">
                                    <button
                                      onClick={() => {
                                        if (onAddTriggerWords) onAddTriggerWords(version.trained_words);
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
                        }}
                        className={`w-full px-3 py-2 text-left hover:bg-gray-700 flex items-center justify-between gap-2 ${isSelected ? 'bg-gray-700/50' : ''}`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-white truncate flex items-center gap-2">
                            {version.name}
                            {version.is_default && (
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
                        <div className="flex items-center gap-1 flex-shrink-0">
                          {!version.is_default && (
                            <button
                              onClick={async (e) => {
                                e.stopPropagation();
                                const baseModel = selectedModel._originalModel || selectedModel;
                                try {
                                  await api.put(
                                    `/api/v2/models/${baseModel.model_id}/default-version`,
                                    { version_id: version.id },
                                  );
                                  toast.success(`Set "${version.name}" as default`);
                                  if (directory) {
                                    if (refetch) await refetch();
                                    // If we need the updated model, we fetch it locally or just pass the current version
                                    if (onChange) {
                                      onChange({ ...baseModel, default_version: version.name });
                                    }
                                  }
                                  setShowVersionDropdown(false);
                                } catch {
                                  toast.error('Failed to set default version');
                                }
                              }}
                              className="p-1 hover:bg-gray-600 rounded text-gray-500 hover:text-yellow-400 transition-colors"
                              title="Set as default version"
                              aria-label="Set as default version"
                            >
                              <Star size={14} />
                            </button>
                          )}
                          {isSelected && <div className="text-blue-400">✓</div>}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Info Button */}
        {onInfoClick && selectedModel?.civitai_id && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onInfoClick(selectedModel);
            }}
            className="p-2 rounded text-gray-400 hover:text-blue-300 hover:bg-gray-800 border border-transparent hover:border-gray-700 transition-colors"
            title="View Model Details"
            aria-label={`View details for ${selectedModel.name}`}
          >
            <Info size={18} />
          </button>
        )}
      </div>
    </div>
  );
});

export default TriggerBox;
