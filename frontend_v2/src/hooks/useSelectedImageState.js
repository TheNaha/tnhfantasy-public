import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api';

export function useSelectedImageState() {
    const [selectedImage, setSelectedImage] = useState(null);
    const [metadata, setMetadata] = useState(null);
    const [loadingMeta, setLoadingMeta] = useState(false);

    const selectImage = useCallback((image) => {
        setSelectedImage(image);

        if (image?.metadata && Object.keys(image.metadata).length > 0) {
            setMetadata(image.metadata);
            setLoadingMeta(false);
            return;
        }

        setMetadata(null);
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

        if (selectedImage.metadata && Object.keys(selectedImage.metadata).length > 0) {
            return;
        }

        let isCancelled = false;

        api.get(`/api/view/output/${encodeURIComponent(selectedImage.name)}.json`)
            .then((data) => {
                if (isCancelled) {
                    return;
                }
                setMetadata(data);
                setLoadingMeta(false);
            })
            .catch((error) => {
                if (isCancelled) {
                    return;
                }
                if (error instanceof ApiError && error.status === 404) {
                    setMetadata(null);
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