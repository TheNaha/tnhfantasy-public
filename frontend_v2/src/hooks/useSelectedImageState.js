import { useCallback, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

export function useSelectedImageState() {
    const [selectedImage, setSelectedImage] = useState(null);

    const { data: serverMetadata, isFetching } = useQuery({
        queryKey: ['metadata', selectedImage?.name],
        queryFn: async () => {
            const data = await api.get(`/api/view/output/${encodeURIComponent(selectedImage.name)}.json`);
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

    return {
        selectedImage,
        metadata,
        loadingMeta,
        selectImage,
        closeSelectedImage,
    };
}