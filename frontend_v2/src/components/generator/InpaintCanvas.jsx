/**
 * InpaintCanvas Component
 * 
 * Simple canvas for drawing inpainting masks.
 * Uses native canvas API for reliability.
 */

import { useRef, useEffect, useState, useCallback } from 'react';
import { Brush, Eraser, Undo2, Redo2, Trash2, ArrowLeftRight } from 'lucide-react';

export default function InpaintCanvas({
    sourceImageUrl,
    sourceWidth,
    sourceHeight,
    onMaskChange,
    className = ''
}) {
    const canvasRef = useRef(null);
    const maskCanvasRef = useRef(null);
    const containerRef = useRef(null);

    const [tool, setTool] = useState('brush');
    const [brushSize, setBrushSize] = useState(30);
    const [isDrawing, setIsDrawing] = useState(false);
    const [lastPos, setLastPos] = useState(null);
    const [scale, setScale] = useState(1);
    const [history, setHistory] = useState([]);
    const [historyIndex, setHistoryIndex] = useState(-1);
    const [imageLoaded, setImageLoaded] = useState(false);

    // Initialize canvases when image loads
    useEffect(() => {
        if (!sourceImageUrl || !canvasRef.current || !maskCanvasRef.current) return;

        const displayCanvas = canvasRef.current;
        const maskCanvas = maskCanvasRef.current;

        // Load the source image
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
            // Set canvas dimensions
            displayCanvas.width = sourceWidth;
            displayCanvas.height = sourceHeight;
            maskCanvas.width = sourceWidth;
            maskCanvas.height = sourceHeight;

            // Draw image on display canvas
            const ctx = displayCanvas.getContext('2d');
            ctx.drawImage(img, 0, 0, sourceWidth, sourceHeight);

            // Initialize mask canvas (black = keep, white = regenerate)
            const maskCtx = maskCanvas.getContext('2d');
            maskCtx.fillStyle = '#000000';
            maskCtx.fillRect(0, 0, sourceWidth, sourceHeight);

            // Initialize undo history with the blank mask state
            const initialState = maskCtx.getImageData(0, 0, sourceWidth, sourceHeight);
            setHistory([initialState]);
            setHistoryIndex(0);

            // Calculate scale to fit container
            if (containerRef.current) {
                const containerWidth = containerRef.current.clientWidth;
                const newScale = Math.min(containerWidth / sourceWidth, 1);
                setScale(newScale);
            }

            setImageLoaded(true);
        };
        img.src = sourceImageUrl;

        return () => {
            setImageLoaded(false);
        };
    }, [sourceImageUrl, sourceWidth, sourceHeight]);

    // Redraw display canvas with mask overlay
    const redrawCanvas = useCallback(() => {
        if (!canvasRef.current || !maskCanvasRef.current || !imageLoaded) return;

        const displayCanvas = canvasRef.current;
        const maskCanvas = maskCanvasRef.current;
        const ctx = displayCanvas.getContext('2d');

        // Reload source image
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
            // Clear and draw image
            ctx.clearRect(0, 0, sourceWidth, sourceHeight);
            ctx.drawImage(img, 0, 0, sourceWidth, sourceHeight);

            // Overlay mask with transparency
            ctx.globalAlpha = 0.5;
            ctx.drawImage(maskCanvas, 0, 0);
            ctx.globalAlpha = 1.0;
        };
        img.src = sourceImageUrl;
    }, [sourceImageUrl, sourceWidth, sourceHeight, imageLoaded]);

    // Save mask state to history
    const saveToHistory = useCallback(() => {
        if (!maskCanvasRef.current) return;

        const maskCanvas = maskCanvasRef.current;
        const imageData = maskCanvas.getContext('2d').getImageData(0, 0, sourceWidth, sourceHeight);

        const newHistory = history.slice(0, historyIndex + 1);
        newHistory.push(imageData);

        // Limit history
        if (newHistory.length > 30) {
            newHistory.shift();
        }

        setHistory(newHistory);
        setHistoryIndex(newHistory.length - 1);
    }, [history, historyIndex, sourceWidth, sourceHeight]);

    // Export mask as data URL
    const exportMask = useCallback(() => {
        if (!maskCanvasRef.current) return;
        const dataUrl = maskCanvasRef.current.toDataURL('image/png');
        onMaskChange?.(dataUrl);
    }, [onMaskChange]);

    // Get canvas coordinates from mouse event
    const getCanvasPos = useCallback((e) => {
        const rect = canvasRef.current.getBoundingClientRect();
        const x = (e.clientX - rect.left) / scale;
        const y = (e.clientY - rect.top) / scale;
        return { x, y };
    }, [scale]);

    // Draw on mask canvas
    const draw = useCallback((x, y) => {
        if (!maskCanvasRef.current || !canvasRef.current) return;

        const maskCtx = maskCanvasRef.current.getContext('2d');
        const displayCtx = canvasRef.current.getContext('2d');

        maskCtx.lineCap = 'round';
        maskCtx.lineJoin = 'round';
        maskCtx.lineWidth = brushSize;

        if (tool === 'brush') {
            maskCtx.strokeStyle = '#FFFFFF';
            displayCtx.strokeStyle = 'rgba(255, 255, 255, 0.7)';
        } else {
            maskCtx.strokeStyle = '#000000';
            displayCtx.strokeStyle = 'rgba(0, 0, 0, 0.7)';
        }

        if (lastPos) {
            // Draw on mask
            maskCtx.beginPath();
            maskCtx.moveTo(lastPos.x, lastPos.y);
            maskCtx.lineTo(x, y);
            maskCtx.stroke();

            // Draw visible stroke on display
            displayCtx.lineWidth = brushSize;
            displayCtx.lineCap = 'round';
            displayCtx.lineJoin = 'round';
            displayCtx.beginPath();
            displayCtx.moveTo(lastPos.x, lastPos.y);
            displayCtx.lineTo(x, y);
            displayCtx.stroke();
        }

        setLastPos({ x, y });
    }, [tool, brushSize, lastPos]);

    // Mouse event handlers
    const handleMouseDown = useCallback((e) => {
        const pos = getCanvasPos(e);
        setIsDrawing(true);
        setLastPos(pos);
        draw(pos.x, pos.y);
    }, [getCanvasPos, draw]);

    const handleMouseMove = useCallback((e) => {
        if (!isDrawing) return;
        const pos = getCanvasPos(e);
        draw(pos.x, pos.y);
    }, [isDrawing, getCanvasPos, draw]);

    const handleMouseUp = useCallback(() => {
        if (isDrawing) {
            setIsDrawing(false);
            setLastPos(null);
            saveToHistory();
            exportMask();
            redrawCanvas();
        }
    }, [isDrawing, saveToHistory, exportMask, redrawCanvas]);

    // Touch event handlers
    const handleTouchStart = useCallback((e) => {
        e.preventDefault();
        const touch = e.touches[0];
        const pos = getCanvasPos(touch);
        setIsDrawing(true);
        setLastPos(pos);
    }, [getCanvasPos]);

    const handleTouchMove = useCallback((e) => {
        e.preventDefault();
        if (!isDrawing) return;
        const touch = e.touches[0];
        const pos = getCanvasPos(touch);
        draw(pos.x, pos.y);
    }, [isDrawing, getCanvasPos, draw]);

    const handleTouchEnd = useCallback(() => {
        handleMouseUp();
    }, [handleMouseUp]);

    // Undo
    const handleUndo = useCallback(() => {
        if (historyIndex <= 0 || !maskCanvasRef.current) return;

        const newIndex = historyIndex - 1;
        const maskCtx = maskCanvasRef.current.getContext('2d');
        maskCtx.putImageData(history[newIndex], 0, 0);

        setHistoryIndex(newIndex);
        exportMask();
        redrawCanvas();
    }, [historyIndex, history, exportMask, redrawCanvas]);

    // Redo
    const handleRedo = useCallback(() => {
        if (historyIndex >= history.length - 1 || !maskCanvasRef.current) return;

        const newIndex = historyIndex + 1;
        const maskCtx = maskCanvasRef.current.getContext('2d');
        maskCtx.putImageData(history[newIndex], 0, 0);

        setHistoryIndex(newIndex);
        exportMask();
        redrawCanvas();
    }, [historyIndex, history, exportMask, redrawCanvas]);

    // Clear mask
    const handleClear = useCallback(() => {
        if (!maskCanvasRef.current) return;

        const maskCtx = maskCanvasRef.current.getContext('2d');
        maskCtx.fillStyle = '#000000';
        maskCtx.fillRect(0, 0, sourceWidth, sourceHeight);

        saveToHistory();
        onMaskChange?.(null);
        redrawCanvas();
    }, [sourceWidth, sourceHeight, saveToHistory, onMaskChange, redrawCanvas]);

    // Invert mask (toggle between regenerate and preserve areas)
    const handleInvert = useCallback(() => {
        if (!maskCanvasRef.current) return;

        const maskCtx = maskCanvasRef.current.getContext('2d');
        const imgData = maskCtx.getImageData(0, 0, sourceWidth, sourceHeight);
        const data = imgData.data;

        for (let i = 0; i < data.length; i += 4) {
            data[i] = 255 - data[i];
            data[i + 1] = 255 - data[i + 1];
            data[i + 2] = 255 - data[i + 2];
        }

        maskCtx.putImageData(imgData, 0, 0);
        saveToHistory();
        exportMask();
        redrawCanvas();
    }, [sourceWidth, sourceHeight, saveToHistory, exportMask, redrawCanvas]);

    // Keyboard shortcuts for brush size and undo
    useEffect(() => {
        function handleKeyDown(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            if (e.key === '[') {
                setBrushSize((s) => Math.max(5, s - 5));
            } else if (e.key === ']') {
                setBrushSize((s) => Math.min(150, s + 5));
            }
        }
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    if (!sourceImageUrl) {
        return (
            <div className={`flex items-center justify-center bg-gray-900 rounded-xl border border-gray-700 h-64 ${className}`}>
                <p className="text-gray-500">Load an image to start masking</p>
            </div>
        );
    }

    return (
        <div className={className}>
            {/* Toolbar */}
            <div className="flex items-center gap-2 mb-4 flex-wrap">
                {/* Tool Selection */}
                <div className="flex bg-gray-800 rounded-lg p-1">
                    <button
                        onClick={() => setTool('brush')}
                        className={`p-2 rounded ${tool === 'brush' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white'}`}
                        title="Brush (paint mask)"
                        aria-label="Brush tool (paint mask)"
                        aria-pressed={tool === 'brush'}
                    >
                        <Brush size={18} />
                    </button>
                    <button
                        onClick={() => setTool('eraser')}
                        className={`p-2 rounded ${tool === 'eraser' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white'}`}
                        title="Eraser (remove mask)"
                        aria-label="Eraser tool (remove mask)"
                        aria-pressed={tool === 'eraser'}
                    >
                        <Eraser size={18} />
                    </button>
                </div>

                {/* Brush Size */}
                <div className="flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-1">
                    <span className="text-xs text-gray-400">Size:</span>
                    <input
                        type="range"
                        min="5"
                        max="100"
                        value={brushSize}
                        onChange={(e) => setBrushSize(parseInt(e.target.value))}
                        aria-label="Brush size"
                        className="w-24"
                    />
                    <span className="text-xs text-white w-8">{brushSize}px</span>
                </div>

                {/* Undo/Redo */}
                <div className="flex bg-gray-800 rounded-lg p-1">
                    <button
                        onClick={handleUndo}
                        disabled={historyIndex <= 0}
                        className={`p-2 rounded ${historyIndex <= 0 ? 'text-gray-600' : 'text-gray-400 hover:text-white'}`}
                        title="Undo"
                        aria-label="Undo mask change"
                    >
                        <Undo2 size={18} />
                    </button>
                    <button
                        onClick={handleRedo}
                        disabled={historyIndex >= history.length - 1}
                        className={`p-2 rounded ${historyIndex >= history.length - 1 ? 'text-gray-600' : 'text-gray-400 hover:text-white'}`}
                        title="Redo"
                        aria-label="Redo mask change"
                    >
                        <Redo2 size={18} />
                    </button>
                </div>

                {/* Invert */}
                <button
                    onClick={handleInvert}
                    className="p-2 bg-gray-800 rounded-lg text-purple-400 hover:text-purple-300 hover:bg-gray-700 transition-colors"
                    title="Invert mask"
                    aria-label="Invert mask"
                >
                    <ArrowLeftRight size={18} />
                </button>

                {/* Clear */}
                <button
                    onClick={handleClear}
                    className="p-2 bg-gray-800 rounded-lg text-red-400 hover:text-red-300 hover:bg-gray-700 transition-colors"
                    title="Clear mask"
                    aria-label="Clear mask"
                >
                    <Trash2 size={18} />
                </button>

                {/* Instructions */}
                <span className="text-xs text-gray-500 ml-auto">
                    Paint white = area to regenerate
                </span>
            </div>

            {/* Canvas Container */}
            <div
                ref={containerRef}
                className="relative bg-gray-950 rounded-xl overflow-hidden border border-gray-700"
                style={{ maxHeight: '60vh' }}
            >
                {/* Hidden mask canvas */}
                <canvas
                    ref={maskCanvasRef}
                    style={{ display: 'none' }}
                />

                {/* Display canvas with image + mask overlay */}
                <canvas
                    ref={canvasRef}
                    style={{
                        width: sourceWidth * scale,
                        height: sourceHeight * scale,
                        cursor: 'crosshair'
                    }}
                    onMouseDown={handleMouseDown}
                    onMouseMove={handleMouseMove}
                    onMouseUp={handleMouseUp}
                    onMouseLeave={handleMouseUp}
                    onTouchStart={handleTouchStart}
                    onTouchMove={handleTouchMove}
                    onTouchEnd={handleTouchEnd}
                />
            </div>
        </div>
    );
}
