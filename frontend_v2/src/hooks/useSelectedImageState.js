import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api';

export function useSelectedImageState() {
    const [selectedImage, setSelectedImage] = useState(null);
    const [metadata, setMetadata] = useState(null);
    const [loadingMeta, setLoadingMeta] = useState(false);

    const selectImage = useCallback((image) => {
        setSelectedImage(image);

        const embeddedMetadata = image?.metadata && Object.keys(image.metadata).length > 0
            ? image.metadata
            : null;

        setMetadata(embeddedMetadata);
        setLoadingMeta(Boolean(image));
    }, []);

    const closeSelectedImage = useCallback(() => {
        setSelectedImage(null);
        setMetadata(null);
        setLoadingMeta(false);
    }, []);

    useEffect(() => {
        if (!selectedImage) {
            return;
        }

        const embeddedMetadata = selectedImage.metadata && Object.keys(selectedImage.metadata).length > 0
            ? selectedImage.metadata
            : null;

        let isCancelled = false;

        api.get(`/api/view/output/${encodeURIComponent(selectedImage.name)}.json`)
            .then((data) => {
                if (isCancelled) {
                    return;
                }

                const mergedMetadata = (data && typeof data === 'object')
                    ? { ...(embeddedMetadata || {}), ...data }
                    : embeddedMetadata;

                setMetadata(mergedMetadata);
                setLoadingMeta(false);
            })
            .catch((error) => {
                if (isCancelled) {
                    return;
                }

                if (error instanceof ApiError && error.status === 404) {
                    setMetadata(embeddedMetadata);
                } else {
                    setMetadata(embeddedMetadata);
                }

                setLoadingMeta(false);
            });

        return () => {
            isCancelled = true;
        };
    }, [selectedImage]);

    useEffect(() => {
        document.body.style.overflow = selectedImage ? 'hidden' : 'unset';
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [selectedImage]);

    return {
        selectedImage,
        metadata,
        loadingMeta,
        selectImage,
        closeSelectedImage,
    };
}