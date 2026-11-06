/**
 * ImageUploader Component
 * 
 * Drag-and-drop or click-to-upload component for source images.
 * Used in Img2Img and Inpainting pages.
 * Supports uploading from file or selecting from gallery.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, X, Image as ImageIcon, Folder, Loader2 } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { filesApi } from '../../api';
import { getApiUrl } from '../../api/config';

export default function ImageUploader({
    onImageSelect,
    onClear,
    image,
    providerId = null,
    className = ''
}) {
    const [uploading, setUploading] = useState(false);

    const onDrop = useCallback(async (acceptedFiles) => {
        if (acceptedFiles.length === 0) return;

        const file = acceptedFiles[0];

        // Validate file type
        if (!file.type.startsWith('image/')) {
            toast.error('Please upload an image file');
            return;
        }

        // Validate file size (max 20MB)
        if (file.size > 20 * 1024 * 1024) {
            toast.error('Image too large. Max size is 20MB.');
            return;
        }

        setUploading(true);

        try {
            // Upload to backend (and optionally sync to provider)
            const result = await filesApi.uploadInput(file, providerId);

            // Create preview URL from the uploaded file
            const previewUrl = URL.createObjectURL(file);

            // Notify parent with image data
            onImageSelect?.({
                filename: result.filename,
                path: result.path,
                previewUrl,
                width: result.width,
                height: result.height,
                syncStatus: result.sync_status,
                needsSync: result.sync_status === 'local_only'
            });

            if (result.sync_status === 'synced') {
                toast.success('Image uploaded and synced');
            } else if (result.sync_status === 'sync_failed') {
                toast.error('Image uploaded but sync failed - will retry on generate');
            } else {
                toast.success('Image uploaded');
            }

        } catch (error) {
            toast.error('Failed to upload image: ' + (error.message || 'Unknown error'));
        } finally {
            setUploading(false);
        }
    }, [onImageSelect, providerId]);

    const onDropRejected = useCallback((fileRejections) => {
        if (fileRejections.length > 0) {
            const hasTooMany = fileRejections.some(r => r.errors?.some(e => e.code === 'too-many-files'));
            if (hasTooMany) {
                toast.error('Only one image can be uploaded at a time');
            } else {
                toast.error(fileRejections[0]?.errors?.[0]?.message || 'File upload rejected');
            }
        }
    }, []);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        onDropRejected,
        accept: {
            'image/*': ['.png', '.jpg', '.jpeg', '.webp']
        },
        maxFiles: 1,
        disabled: uploading
    });

    const handleClear = (e) => {
        e.stopPropagation();
        // Revoke object URL to prevent memory leaks
        if (image?.previewUrl?.startsWith('blob:')) {
            URL.revokeObjectURL(image.previewUrl);
        }
        onClear?.();
    };

    // Revoke the previous preview on change and on unmount. Each upload creates
    // a new blob URL that pins the whole file in memory; only handleClear used
    // to revoke, so dropping a second image (or unmounting with one loaded)
    // leaked the earlier blob for the lifetime of the page. Same pattern as
    // Characters.jsx (previewUrlRef).
    const previewUrlRef = useRef(null);
    useEffect(() => {
        const url = image?.previewUrl;
        const previous = previewUrlRef.current;
        previewUrlRef.current = url && url.startsWith('blob:') ? url : null;
        // Revoke the URL this effect was replacing, not the one currently held.
        // The previous version compared `previous !== url`, and on every
        // transition both sides were the same value, so it revoked nothing and
        // each replaced image leaked its blob for the page's lifetime.
        if (previous && previous !== url) {
            URL.revokeObjectURL(previous);
        }
    }, [image?.previewUrl]);

    useEffect(() => () => {
        if (previewUrlRef.current) {
            URL.revokeObjectURL(previewUrlRef.current);
            previewUrlRef.current = null;
        }
    }, []);

    // If we have an image, show it with a clear button
    if (image) {
        return (
            <div className={`relative rounded-xl overflow-hidden border border-gray-700 bg-gray-900 ${className}`}>
                <img
                    src={image.previewUrl || `${getApiUrl()}${image.localPreview}`}
                    alt="Source"
                    className="w-full h-auto max-h-[400px] object-contain bg-gray-950"
                />

                {/* Clear button */}
                <button
                    onClick={handleClear}
                    className="absolute top-3 right-3 p-2 bg-red-600/90 hover:bg-red-500 
                             rounded-full shadow-lg transition-colors"
                    title="Remove image"
                >
                    <X size={16} />
                </button>

                {/* Dimensions badge */}
                {image.width && image.height && (
                    <div className="absolute bottom-3 left-3 bg-black/70 backdrop-blur-sm 
                                  px-3 py-1.5 rounded-lg text-xs font-medium">
                        {image.width} × {image.height}
                    </div>
                )}

                {/* Sync status badge */}
                {image.needsSync && (
                    <div className="absolute bottom-3 right-3 bg-yellow-600/80 backdrop-blur-sm 
                                  px-3 py-1.5 rounded-lg text-xs font-medium">
                        Will sync on generate
                    </div>
                )}
            </div>
        );
    }

    // Upload zone
    return (
        <div className={className}>
            <div
                {...getRootProps()}
                className={`
                    border-2 border-dashed rounded-xl p-8 text-center cursor-pointer
                    transition-all duration-200
                    ${isDragActive
                        ? 'border-purple-500 bg-purple-500/10'
                        : 'border-gray-700 hover:border-gray-500 bg-gray-900/50'}
                    ${uploading ? 'opacity-50 pointer-events-none' : ''}
                `}
            >
                <input {...getInputProps()} />

                {uploading ? (
                    <>
                        <Loader2 className="w-12 h-12 mx-auto mb-4 text-purple-400 animate-spin" />
                        <p className="text-gray-300 font-medium">Uploading...</p>
                    </>
                ) : isDragActive ? (
                    <>
                        <Upload className="w-12 h-12 mx-auto mb-4 text-purple-400" />
                        <p className="text-purple-300 font-medium">Drop image here</p>
                    </>
                ) : (
                    <>
                        <ImageIcon className="w-12 h-12 mx-auto mb-4 text-gray-400" />
                        <p className="text-gray-300 font-medium">
                            Drop image here or click to upload
                        </p>
                        <p className="text-gray-500 text-sm mt-1">
                            PNG, JPG, WEBP up to 20MB
                        </p>
                    </>
                )}
            </div>
        </div>
    );
}
