/**
 * Img2Img Generator Page
 * 
 * Dedicated page for image-to-image generation.
 * Uses a source image and transforms it based on prompts and denoise setting.
 */

import { useEffect } from 'react';
import { ImageIcon, Settings2, Link as LinkIcon } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useGeneratorCore } from '../hooks/useGeneratorCore';

import ImageUploader from '../components/generator/ImageUploader';
import ModelMetadataModal from '../components/ModelMetadataModal';
import GeneratorReadinessPanel from '../components/generator/GeneratorReadinessPanel';
import ModelSection from '../components/generator/ModelSection';
import ControlNetSection from '../components/generator/ControlNetSection';
import IPAdapterSection from '../components/generator/IPAdapterSection';
import EnhancementsSection from '../components/generator/EnhancementsSection';
import PromptPanel from '../components/generator/PromptPanel';
import SamplingSettings from '../components/generator/SamplingSettings';
import PresetManager from '../components/generator/PresetManager';
import useSettingsStore from '../store/settingsStore';
import { useGeneratorJob } from '../hooks/useGeneratorJob';
import { useWorkflowBuilder } from '../hooks/useWorkflowBuilder';
import UnifiedGeneratorLayout from '../components/generator/UnifiedGeneratorLayout';
import GenerateActionBar from '../components/generator/GenerateActionBar';
import ResolutionSettings from '../components/generator/ResolutionSettings';

const EMPTY_MODELS = [];

export default function Img2ImgGenerator() {
    const location = useLocation();
    const {
        store: {
            sourceImage, denoise, setSourceImage, setDenoise, clearSourceImage,
            selectedCheckpoint, randomizeSeed
        },
    } = useGeneratorCore();

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);
    const { runSubmission } = useWorkflowBuilder('img2img');

    // Check for pre-loaded image from navigation state
    useEffect(() => {
        if (location.state?.sourceImage) {
            setSourceImage(location.state.sourceImage);
        }
    }, [location.state, setSourceImage]);

    const validateImg2Img = () => {
        if (!sourceImage?.filename) return 'Please upload a source image first';
        if (!selectedCheckpoint?.name) return 'Please select a checkpoint';
        return null;
    };

    const { progress, generating, handleGenerate } = useGeneratorJob({
        runSubmission,
        type: 'img2img',
        setGeneratingOnQueue: true,
        validate: validateImg2Img,
        randomizeSeed,
        autoRandomizeSeed,
    });

    const canGenerate = generating || !sourceImage?.filename || !selectedCheckpoint?.name;

    return (
        <UnifiedGeneratorLayout
            mode="img2img"
            accentClass="from-orange-400 to-red-500"
            runwayTitle="Img2Img Runway"
            runwayHint="Check provider health and model availability before transforming the source image."
            leftColumnTop={
                <div className="space-y-3 pb-4 border-b border-gray-800">
                    <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                        <ImageIcon size={18} className="text-orange-400" />
                        Source Image
                    </h3>
                    <ImageUploader
                        image={sourceImage}
                        onImageSelect={setSourceImage}
                        onClear={clearSourceImage}
                    />
                </div>
            }
            rightColumnMiddle={
                <>
                    <PresetManager />

                    {/* Denoise Strength - KEY Img2Img Parameter */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2 text-orange-400">
                            <LinkIcon size={18} />
                            Denoise Strength
                        </h3>
                        <div className="space-y-2">
                            <div className="flex justify-between text-sm">
                                <span className="text-gray-400">Preserve Original</span>
                                <span className="text-gray-400">Full Regeneration</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="1"
                                step="0.05"
                                value={denoise}
                                onChange={(e) => setDenoise(parseFloat(e.target.value))}
                                className="w-full accent-orange-500"
                            />
                            <div className="text-center">
                                <span className="text-2xl font-bold text-orange-400">{denoise.toFixed(2)}</span>
                            </div>
                            <p className="text-xs text-gray-500 text-center">
                                Lower = More like original • Higher = More creative
                            </p>
                        </div>
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
                        onGenerate={() => handleGenerate({ shouldRedirect: true, trackQueuedJob: true })}
                        label="Generate Img2Img"
                        gradientClass="bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-500 hover:to-red-500 text-white shadow-lg shadow-orange-900/30"
                        progressBarClass="from-orange-400 to-yellow-400"
                    />

                    {/* Quick Info */}
                    {sourceImage && (
                        <div className="bg-gray-800/30 p-4 mt-4 rounded-xl border border-gray-700/50 hidden md:block">
                            <p className="text-xs text-gray-500 mb-2">Output Resolution</p>
                            <p className="text-lg font-bold text-gray-300">
                                {sourceImage.width} × {sourceImage.height}
                            </p>
                            <p className="text-xs text-gray-500 mt-2">
                                Output will match source image dimensions
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
                    onGenerate={() => handleGenerate({ shouldRedirect: true, trackQueuedJob: true })}
                    label="Generate Img2Img"
                    gradientClass="bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-500 hover:to-red-500 text-white shadow-lg shadow-orange-900/30"
                    progressBarClass="from-orange-400 to-yellow-400"
                />
            }
        />
    );
}
