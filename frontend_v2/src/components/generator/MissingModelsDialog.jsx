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

import React, { useState } from 'react';
import './MissingModelsDialog.css';

// API for triggering downloads
const downloadModel = async (filename, directory) => {
    // This would call an API to trigger download
    // For now, we'll just open the model manager
    console.log('Download requested:', filename, directory);
    return { success: true };
};

export default function MissingModelsDialog({
    isOpen,
    onClose,
    validationResult,
    onDownloadTriggered
}) {
    const [downloading, setDownloading] = useState({});
    const [downloadStatus, setDownloadStatus] = useState({});

    if (!isOpen || !validationResult) return null;

    const {
        required_models = {},
        global_missing = {},
        missing_models = {},
        can_trigger_download = false
    } = validationResult;

    // Check if there are any missing models
    const hasGlobalMissing = Object.keys(global_missing).length > 0;
    const hasMissingByProvider = Object.keys(missing_models).length > 0;

    if (!hasGlobalMissing && !hasMissingByProvider) {
        return null;
    }

    const handleDownloadAll = async () => {
        for (const [directory, filenames] of Object.entries(global_missing)) {
            for (const filename of filenames) {
                const key = `${directory}/${filename}`;
                if (!downloading[key]) {
                    setDownloading(prev => ({ ...prev, [key]: true }));
                    try {
                        await downloadModel(filename, directory);
                        setDownloadStatus(prev => ({ ...prev, [key]: 'queued' }));
                    } catch {
                        setDownloadStatus(prev => ({ ...prev, [key]: 'error' }));
                    } finally {
                        setDownloading(prev => ({ ...prev, [key]: false }));
                    }
                }
            }
        }
        if (onDownloadTriggered) {
            onDownloadTriggered();
        }
    };

    const handleDownloadSingle = async (directory, filename) => {
        const key = `${directory}/${filename}`;
        if (downloading[key]) return;

        setDownloading(prev => ({ ...prev, [key]: true }));
        try {
            await downloadModel(filename, directory);
            setDownloadStatus(prev => ({ ...prev, [key]: 'queued' }));
            if (onDownloadTriggered) {
                onDownloadTriggered();
            }
        } catch {
            setDownloadStatus(prev => ({ ...prev, [key]: 'error' }));
        } finally {
            setDownloading(prev => ({ ...prev, [key]: false }));
        }
    };

    const getStatusIcon = (directory, filename) => {
        const key = `${directory}/${filename}`;
        if (downloading[key]) return '⏳';
        if (downloadStatus[key] === 'queued') return '✓';
        if (downloadStatus[key] === 'error') return '⚠️';
        return null;
    };

    return (
        <div className="missing-models-overlay" onClick={onClose}>
            <div className="missing-models-dialog" onClick={e => e.stopPropagation()}>
                <div className="missing-models-header">
                    <h2>⚠️ Missing Models</h2>
                    <button className="close-button" onClick={onClose}>×</button>
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
                                        {filenames.map(filename => {
                                            const key = `${directory}/${filename}`;
                                            const statusIcon = getStatusIcon(directory, filename);
                                            return (
                                                <li key={filename} className="model-item">
                                                    <span className="model-name">{filename}</span>
                                                    {statusIcon && <span className="status-icon">{statusIcon}</span>}
                                                    {can_trigger_download && !downloadStatus[key] && (
                                                        <button
                                                            className="download-btn"
                                                            onClick={() => handleDownloadSingle(directory, filename)}
                                                            disabled={downloading[key]}
                                                        >
                                                            Download
                                                        </button>
                                                    )}
                                                </li>
                                            );
                                        })}
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
                    {can_trigger_download && hasGlobalMissing && (
                        <button
                            className="download-all-btn"
                            onClick={handleDownloadAll}
                        >
                            Download All Missing Models
                        </button>
                    )}
                    <button className="open-model-manager-btn" onClick={() => {
                        window.location.hash = '#/models';
                        onClose();
                    }}>
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
