import { useState } from 'react';
import { X, ArrowLeftRight, ZoomIn, ZoomOut, Maximize2, Minimize2 } from 'lucide-react';

export const ImageComparison = ({ images, onClose }) => {
    const [sliderPosition, setSliderPosition] = useState(50);
    const [zoom, setZoom] = useState(1);
    const [mode, setMode] = useState(images.length === 2 ? 'slider' : 'grid'); // 'slider' or 'grid'

    if (!images || images.length < 2) return null;

    const handleSliderChange = (e) => {
        setSliderPosition(e.target.value);
    };

    // Metadata keys to compare
    const metaKeys = ['model', 'sampler', 'steps', 'cfg', 'seed', 'scheduler'];

    return (
        <div className="fixed inset-0 z-50 bg-gray-950 flex flex-col">
            {/* Header */}
            <div className="p-4 border-b border-gray-800 flex justify-between items-center bg-gray-900">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <ArrowLeftRight className="text-blue-400" />
                    Image Comparison ({images.length})
                </h2>
                <div className="flex items-center gap-4">
                    {images.length === 2 && (
                        <div className="flex bg-gray-800 rounded-lg p-1">
                            <button
                                onClick={() => setMode('slider')}
                                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${mode === 'slider' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                                aria-label="Slider comparison view"
                                aria-pressed={mode === 'slider'}
                            >
                                Slider
                            </button>
                            <button
                                onClick={() => setMode('grid')}
                                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${mode === 'grid' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                                aria-label="Side-by-side comparison view"
                                aria-pressed={mode === 'grid'}
                            >
                                Side-by-Side
                            </button>
                        </div>
                    )}
                    <button onClick={onClose} className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white" aria-label="Close image comparison">
                        <X size={24} />
                    </button>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-hidden flex flex-col lg:flex-row">
                {/* Image Area */}
                <div className="flex-1 bg-black/50 relative overflow-hidden flex items-center justify-center p-4">
                    {mode === 'slider' && images.length === 2 ? (
                        <div className="relative w-full max-w-4xl aspect-square max-h-[80vh] select-none group">
                            {/* Image B (Background) */}
                            <img
                                src={`/api/view/output/${images[1].name}`}
                                alt="B"
                                className="absolute inset-0 w-full h-full object-contain"
                            />
                            {/* Image A (Foreground with clip-path) */}
                            <div
                                className="absolute inset-0 w-full h-full overflow-hidden"
                                style={{ clipPath: `inset(0 ${100 - sliderPosition}% 0 0)` }}
                            >
                                <img
                                    src={`/api/view/output/${images[0].name}`}
                                    alt="A"
                                    className="absolute inset-0 w-full h-full object-contain"
                                />
                            </div>

                            {/* Slider Handle */}
                            <div
                                className="absolute inset-y-0 w-1 bg-white cursor-ew-resize shadow-[0_0_10px_rgba(0,0,0,0.5)] hover:bg-blue-400 transition-colors"
                                style={{ left: `${sliderPosition}%` }}
                            >
                                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-8 h-8 bg-white rounded-full shadow-lg flex items-center justify-center text-gray-900">
                                    <ArrowLeftRight size={16} />
                                </div>
                            </div>

                            {/* Invisible Range Input for Interaction */}
                            <input
                                type="range"
                                min="0"
                                max="100"
                                value={sliderPosition}
                                onChange={handleSliderChange}
                                className="absolute inset-0 w-full h-full opacity-0 cursor-ew-resize z-10"
                            />

                            {/* Labels */}
                            <div className="absolute top-4 left-4 bg-black/70 text-white px-2 py-1 rounded text-sm pointer-events-none">
                                A: {images[0].name.slice(0, 15)}...
                            </div>
                            <div className="absolute top-4 right-4 bg-black/70 text-white px-2 py-1 rounded text-sm pointer-events-none">
                                B: {images[1].name.slice(0, 15)}...
                            </div>
                        </div>
                    ) : (
                        <div className={`grid gap-4 w-full h-full ${images.length === 2 ? 'grid-cols-2' : 'grid-cols-2 grid-rows-2'}`}>
                            {images.map((img, idx) => (
                                <div key={idx} className="relative border border-gray-800 rounded-lg overflow-hidden bg-gray-900/50 flex items-center justify-center">
                                    <img
                                        src={`/api/view/output/${img.name}`}
                                        alt={img.name}
                                        className="max-w-full max-h-full object-contain"
                                    />
                                    <div className="absolute top-2 left-2 bg-black/60 text-white px-2 py-1 rounded text-xs">
                                        {img.name}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Metadata Sidebar */}
                <div className="w-full lg:w-80 bg-gray-900 border-l border-gray-800 overflow-y-auto p-4">
                    <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-4">Parameters</h3>

                    <div className="space-y-6">
                        {metaKeys.map(key => (
                            <div key={key}>
                                <div className="text-xs text-gray-500 uppercase mb-1">{key}</div>
                                <div className="grid grid-cols-2 gap-2">
                                    {images.map((img, idx) => {
                                        const val = img.metadata?.[key];
                                        // Highlight differences
                                        const isDiff = images.some(other => other.metadata?.[key] !== val);

                                        return (
                                            <div
                                                key={idx}
                                                className={`text-sm p-2 rounded ${isDiff ? 'bg-yellow-900/20 text-yellow-200 border border-yellow-900/50' : 'bg-gray-800 text-gray-300'}`}
                                            >
                                                <span className="text-xs text-gray-500 mr-2">#{idx + 1}</span>
                                                {val !== undefined ? String(val) : '-'}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-8 pt-4 border-t border-gray-800">
                        <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-2">Prompts</h3>
                        <div className="space-y-4">
                            {images.map((img, idx) => (
                                <div key={idx} className="bg-gray-800 p-3 rounded-lg text-sm text-gray-300">
                                    <div className="text-xs text-gray-500 mb-1">Image #{idx + 1}</div>
                                    {img.metadata?.prompt || 'No prompt data'}
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
