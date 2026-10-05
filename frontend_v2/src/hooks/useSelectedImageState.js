import { useCallback, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { assetMetadataUrl, assetPath } from '../utils/assetUrl';

export function useSelectedImageState() {
    const [selectedImage, setSelectedImage] = useState(null);

    const { data: serverMetadata, isFetching } = useQuery({
        queryKey: ['metadata', assetPath(selectedImage)],
        queryFn: async ({ signal }) => {
            const data = await api.get(assetMetadataUrl(assetPath(selectedImage)), { signal });
            return data;
        },
        enabled: !!selectedImage,
        staleTime: Infinity,
        retry: false,
    });

    const embeddedMetadata = selectedImage?.metadata && Object.keys(selectedImage.metadata).length > 0
        ? selectedImage.metadata
        : null;

    const metadata = (serverMetadata && typeof serverMetadata === 'object')
        ? { ...(embeddedMetadata || {}), ...serverMetadata }
        : embeddedMetadata;

    const loadingMeta = !!selectedImage && isFetching;

    const selectImage = useCallback((image) => {
        setSelectedImage(image);
    }, []);

    const closeSelectedImage = useCallback(() => {
        setSelectedImage(null);
    }, []);

    useEffect(() => {
        document.body.style.overflow = selectedImage ? 'hidden' : 'unset';
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [selectedImage]);

    return { selectedImage, metadata, loadingMeta, selectImage, closeSelectedImage };
}
