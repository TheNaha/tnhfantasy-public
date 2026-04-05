/**
 * MissingModelsDialog
 * 
 * Shows missing model information when a workflow cannot be executed
 * because required models are not available on any provider.
 * 
 * Features:
 * - Lists globally missing models (not on any provider)
 * - Shows missing models per provider
 * - Offers download triggers for models in the library
 */

import { useNavigate } from 'react-router-dom';
import './MissingModelsDialog.css';

export default function MissingModelsDialog({
    isOpen,
    onClose,
    validationResult,
    onOpenModelManager,
}) {
    const navigate = useNavigate();

    if (!isOpen || !validationResult) return null;

    const {
        required_models = {},
        global_missing = {},
        missing_models = {},
    } = validationResult;

    // Check if there are any missing models
    const hasGlobalMissing = Object.keys(global_missing).length > 0;
    const hasMissingByProvider = Object.keys(missing_models).length > 0;

    if (!hasGlobalMissing && !hasMissingByProvider) {
        return null;
    }

    const handleOpenModelManager = () => {
        onClose();
        if (onOpenModelManager) {
            onOpenModelManager();
            return;
        }
        navigate('/models');
    };

    return (
        <div className="missing-models-overlay" onClick={onClose}>
            <div className="missing-models-dialog" onClick={e => e.stopPropagation()}>
                <div className="missing-models-header">
                    <h2>⚠️ Missing Models</h2>
                    <button className="close-button" onClick={onClose} aria-label="Close dialog">×</button>
                </div>

                <div className="missing-models-content">
                    <p className="missing-models-intro">
                        The required models for this generation are not available on any provider.
                    </p>

                    {/* Globally missing models - not on ANY provider */}
                    {hasGlobalMissing && (
                        <div className="missing-section">
                            <h3>Models Not Installed</h3>
                            <p className="section-desc">
                                These models need to be downloaded to at least one provider.
                            </p>

                            {Object.entries(global_missing).map(([directory, filenames]) => (
                                <div key={directory} className="directory-group">
                                    <h4>{directory}</h4>
                                    <ul className="model-list">
                                        {filenames.map((filename) => (
                                            <li key={filename} className="model-item">
                                                <span className="model-name">{filename}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Per-provider missing models */}
                    {hasMissingByProvider && !hasGlobalMissing && (
                        <div className="missing-section">
                            <h3>Provider-Specific Issues</h3>
                            <p className="section-desc">
                                Some providers are missing models. The job will use a provider that has all required models.
                            </p>

                            {Object.entries(missing_models).map(([providerId, directories]) => (
                                <div key={providerId} className="provider-group">
                                    <h4>{providerId}</h4>
                                    {Object.entries(directories).map(([directory, filenames]) => (
                                        <div key={directory} className="directory-group">
                                            <span className="directory-label">{directory}:</span>
                                            <span className="missing-count">
                                                {filenames.length} missing
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Required models summary */}
                    {Object.keys(required_models).length > 0 && (
                        <details className="required-models-details">
                            <summary>Required Models ({
                                Object.values(required_models).flat().length
                            } total)</summary>
                            <div className="required-models-list">
                                {Object.entries(required_models).map(([directory, filenames]) => (
                                    <div key={directory}>
                                        <strong>{directory}:</strong> {filenames.join(', ')}
                                    </div>
                                ))}
                            </div>
                        </details>
                    )}
                </div>

                <div className="missing-models-footer">
                    <button className="open-model-manager-btn" onClick={handleOpenModelManager}>
                        Open Model Manager
                    </button>
                    <button className="cancel-btn" onClick={onClose}>
                        Cancel
                    </button>
                </div>
            </div>
        </div>
    );
}
