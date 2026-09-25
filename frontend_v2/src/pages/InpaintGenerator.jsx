/**
 * Inpainting Generator Page
 * 
 * Dedicated page for inpainting - regenerating masked areas of an image.
 * Uses a Fabric.js canvas for mask drawing.
 */

import { useEffect, useMemo } from 'react';
import { Paintbrush, Settings2, Trash2, Sparkles } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useGeneratorCore } from '../hooks/useGeneratorCore';
import { filesApi } from '../api';
import { getApiUrl } from '../api/config';
import ImageUploader from '../components/generator/ImageUploader';
import InpaintCanvas from '../components/generator/InpaintCanvas';
import PresetManager from '../components/generator/PresetManager';
import useSettingsStore from '../store/settingsStore';
import { useGeneratorJob } from '../hooks/useGeneratorJob';
import { useModelDirectories } from '../hooks/useModelDirectories';
import { GENERATOR_MODEL_REQUESTS } from '../constants/modelDirectories';
import { useWorkflowBuilder } from '../hooks/useWorkflowBuilder';
import UnifiedGeneratorLayout from '../components/generator/UnifiedGeneratorLayout';
import GenerateActionBar from '../components/generator/GenerateActionBar';

const EMPTY_MODELS = [];

export default function InpaintGenerator() {
    const location = useLocation();
    const {
        store: {
            sourceImage, denoise, maskImage, maskBlur,
            selectedCheckpoint, 
            setSourceImage, setDenoise, setMaskImage, setMaskBlur,
            clearSourceImage,
            randomizeSeed
        },
    } = useGeneratorCore();

    const { runSubmission: runWorkflowSubmission } = useWorkflowBuilder('inpaint');

    // Canvas visibility is derived from the presence of a source image (it is
    // only ever opened when an image is loaded and closed on Clear), so there is
    // no separate state to keep in sync — avoids setState-in-effect lint errors.
    const showCanvas = !!sourceImage?.filename;
    const { modelsByKey } = useModelDirectories(GENERATOR_MODEL_REQUESTS);
    const checkpoints = modelsByKey.checkpoints ?? EMPTY_MODELS;

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);

    // Check for pre-loaded image from navigation state
    useEffect(() => {
        if (location.state?.sourceImage) {
            setSourceImage(location.state.sourceImage);
        }
    }, [location.state, setSourceImage]);

    // Auto-detect inpaint model if available
    const inpaintCheckpoint = useMemo(() => {
        if (!selectedCheckpoint) return null;

        // Look for inpainting version of current model
        const baseName = selectedCheckpoint.name?.replace(/\.(safetensors|ckpt)$/, '') || '';
        const inpaintVariant = checkpoints.find(m => {
            const name = m.name?.toLowerCase() || '';
            return name.includes('inpaint') && (
                name.includes(baseName.toLowerCase()) ||
                baseName.toLowerCase().includes(name.replace('inpaint', '').replace(/-/g, '').trim())
            );
        });

        return inpaintVariant || null;
    }, [selectedCheckpoint, checkpoints]);

    const validateInpaint = () => {
        if (!sourceImage?.filename) return 'Please upload a source image first';
        if (!maskImage) return 'Please draw a mask on the image';
        if (!selectedCheckpoint?.name) return 'Please select a checkpoint';
        return null;
    };

    const runSubmission = async ({ setProgress }) => {
        const checkpointToUse = inpaintCheckpoint?.name || selectedCheckpoint.name;

        const maskResult = await filesApi.uploadMask(
            maskImage,
            sourceImage.filename,
        );

        setProgress({ value: 0, max: 100, status: 'starting', node: 'Initializing...' });

        return runWorkflowSubmission({ maskResult, checkpointToUse, inpaintCheckpoint });
    };

    const { progress, generating, handleGenerate } = useGeneratorJob({
        runSubmission,
        type: 'inpaint',
        setGeneratingOnQueue: true,
        startingNode: 'Uploading mask...',
        validate: validateInpaint,
        randomizeSeed,
        autoRandomizeSeed,
    });

    const handleClearAll = () => {
        clearSourceImage();
    };

    const canGenerate = generating || !sourceImage?.filename || !maskImage || !selectedCheckpoint?.name;

    return (
        <UnifiedGeneratorLayout
            mode="inpaint"
            accentClass="from-purple-400 to-pink-500"
            runwayTitle="Inpaint Runway"
            runwayHint="Check runtime health and workflow availability before regenerating the masked region."
            leftColumnTop={
                <div className="space-y-3 pb-4 border-b border-gray-800">
                    <div className="flex justify-between items-center">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                            <Paintbrush size={18} className="text-purple-400" />
                            {showCanvas ? 'Draw Mask' : 'Source Image'}
                        </h3>
                        {sourceImage && (
                            <button
                                onClick={handleClearAll}
                                className="text-xs text-red-400 hover:text-red-300 flex items-center gap-1"
                            >
                                <Trash2 size={14} /> Clear
                            </button>
                        )}
                    </div>

                    {!sourceImage ? (
                        <ImageUploader
                            image={sourceImage}
                            onImageSelect={(img) => {
                                setSourceImage(img);
                            }}
                            onClear={handleClearAll}
                        />
                    ) : (
                        <InpaintCanvas
                            sourceImageUrl={sourceImage.previewUrl || `${getApiUrl()}${sourceImage.localPreview}`}
                            sourceWidth={sourceImage.width}
                            sourceHeight={sourceImage.height}
                            onMaskChange={setMaskImage}
                        />
                    )}

                    {sourceImage && (
                        <p className="text-xs text-gray-500 text-center">
                            Paint over areas you want to regenerate • White = regenerate, Black = keep
                        </p>
                    )}
                </div>
            }
            leftColumnBottom={
                inpaintCheckpoint && (
                    <div className="bg-purple-900/20 border border-purple-700/50 rounded-lg p-3 flex items-center gap-3">
                        <Sparkles size={18} className="text-purple-400" />
                        <div>
                            <p className="text-sm text-purple-300 font-medium">
                                Inpaint model detected!
                            </p>
                            <p className="text-xs text-gray-400">
                                Using: {inpaintCheckpoint.display_name || inpaintCheckpoint.name}
                            </p>
                        </div>
                    </div>
                )
            }
            rightColumnMiddle={
                <>
                    <PresetManager />

                    {/* Denoise Strength */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2 text-purple-400">
                            <Paintbrush size={18} />
                            Inpaint Strength
                        </h3>
                        <div className="space-y-2">
                            <input
                                type="range"
                                min="0"
                                max="1"
                                step="0.05"
                                value={denoise}
                                onChange={(e) => setDenoise(parseFloat(e.target.value))}
                                className="w-full accent-purple-500"
                            />
                            <div className="text-center">
                                <span className="text-2xl font-bold text-purple-400">{denoise.toFixed(2)}</span>
                            </div>
                            <p className="text-xs text-gray-500 text-center">
                                Higher = more creative • 0.8-1.0 recommended for inpainting
                            </p>
                        </div>
                    </div>

                    {/* Mask Blur */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-sm font-medium text-gray-300">Mask Blur</h3>
                        <div className="flex items-center gap-4">
                            <input
                                type="range"
                                min="0"
                                max="20"
                                value={maskBlur}
                                onChange={(e) => setMaskBlur(parseInt(e.target.value))}
                                className="flex-1"
                            />
                            <span className="text-sm text-white w-12">{maskBlur}px</span>
                        </div>
                        <p className="text-xs text-gray-500">
                            Blur mask edges for smoother blending
                        </p>
                    </div>
                </>
            }
            rightColumnBottom={
                <>
                    <GenerateActionBar
                        generating={generating}
                        progress={progress}
                        disabled={canGenerate}
                        onQueue={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                        onGenerate={() => handleGenerate({ trackQueuedJob: true })}
                        label="Generate Inpaint"
                        gradientClass="bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white shadow-lg shadow-purple-900/30"
                        progressBarClass="from-purple-400 to-pink-400"
                    />

                    {/* Status */}
                    {sourceImage && !maskImage && (
                        <div className="bg-yellow-900/20 border border-yellow-700/50 rounded-lg p-3 text-center mt-4">
                            <p className="text-sm text-yellow-300">
                                Draw a mask on the image to continue
                            </p>
                        </div>
                    )}

                    {/* Quick Info */}
                    {sourceImage && (
                        <div className="bg-gray-800/30 p-4 mt-4 rounded-xl border border-gray-700/50">
                            <p className="text-xs text-gray-500 mb-2">Output Resolution</p>
                            <p className="text-lg font-bold text-gray-300">
                                {sourceImage.width} × {sourceImage.height}
                            </p>
                        </div>
                    )}
                </>
            }
            mobileActionBar={
                <GenerateActionBar
                    generating={generating}
                    progress={progress}
                    disabled={canGenerate}
                    onQueue={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                    onGenerate={() => handleGenerate({ trackQueuedJob: true })}
                    label="Generate Inpaint"
                    gradientClass="bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white shadow-lg shadow-purple-900/30"
                    progressBarClass="from-purple-400 to-pink-400"
                />
            }
        />
    );
}
