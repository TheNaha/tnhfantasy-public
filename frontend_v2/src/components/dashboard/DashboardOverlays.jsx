import ImageLightbox from './ImageLightbox';
import JobDetailsModal from './JobDetailsModal';
import { ImageComparison } from './ImageComparison';
import CollectionsPanel from '../collections/CollectionsPanel';
import SelectCollectionModal from '../collections/SelectCollectionModal';
/**
 * DashboardOverlays Component
 * @param {object} props
 * @param {object} props.selectedImage - The currently selected image for lightbox
 * @param {array} props.lightboxImages - Sibling images to navigate in the lightbox
 * @param {(index: number) => void} props.onLightboxNavigate - Callback to navigate inside lightbox
 * @param {object} props.metadata - Image metadata
 * @param {boolean} props.loadingMeta - Whether metadata is loading
 * @param {() => void} props.onLightboxClose - Callback to close lightbox
 * @param {(filename: string) => void} props.onLightboxDelete - Callback to delete image
 * @param {() => void} props.onLightboxReuseParameters - Callback to reuse generation parameters
 * @param {boolean} props.reuseInProgress - Whether reuse parameters operation is in progress
 * 
 * @param {object} props.selectedJob - The currently selected job for job details modal
 * @param {() => void} props.onJobDetailsClose - Callback to close job details modal
 * @param {(jobId: string) => void} props.onJobCancel - Callback to cancel a running job
 * @param {(jobId: string) => void} props.onJobDelete - Callback to delete a job
 * @param {(jobId: string) => void} props.onJobRetry - Callback to retry a job
 * 
 * @param {boolean} props.showComparison - Whether to show the comparison slider
 * @param {() => void} props.onComparisonClose - Callback to close comparison slider
 * @param {array} props.comparisonImages - Images to compare
 * 
 * @param {boolean} props.showCollectionsPanel - Whether to show collections panel
 * @param {() => void} props.onCollectionsPanelClose - Callback to close collections panel
 * 
 * @param {boolean} props.showSelectCollection - Whether to show selection collection modal
 * @param {() => void} props.onSelectCollectionClose - Callback to close selection collection modal
 * @param {object} props.collections - Active collections data
 * @param {(collectionId: string) => void} props.onSelectCollection - Callback when a collection is selected
 * 
 * @param {object} props.keyboardShortcutsRef - Ref for keyboard shortcuts modal
 */
export default function DashboardOverlays({
    selectedImage,
    lightboxImages,
    onLightboxNavigate,
    metadata,
    loadingMeta,
    onLightboxClose,
    onLightboxDelete,
    onLightboxReuseParameters,
    reuseInProgress,

    selectedJob,
    onJobDetailsClose,
    onJobCancel,
    onJobDelete,
    onJobRetry,

    showComparison,
    onComparisonClose,
    comparisonImages,

    showCollectionsPanel,
    onCollectionsPanelClose,

    showSelectCollection,
    onSelectCollectionClose,
    collections,
    onSelectCollection,
}) {
    return (
        <>
            {selectedImage && (
                <ImageLightbox
                    image={selectedImage}
                    images={lightboxImages}
                    currentIndex={selectedImage.siblingImages?.findIndex(img => img.name === selectedImage.name) || 0}
                    onNavigate={onLightboxNavigate}
                    metadata={metadata}
                    loadingMeta={loadingMeta}
                    job={selectedImage.associatedJob}
                    onClose={onLightboxClose}
                    onDelete={onLightboxDelete}
                    onReuseParameters={onLightboxReuseParameters}
                    reuseInProgress={reuseInProgress}
                />
            )}

            {selectedJob && (
                <JobDetailsModal
                    job={selectedJob}
                    onClose={onJobDetailsClose}
                    onCancel={onJobCancel}
                    onDelete={onJobDelete}
                    onRetry={onJobRetry}
                />
            )}

            {showComparison && (
                <ImageComparison
                    images={comparisonImages}
                    onClose={onComparisonClose}
                />
            )}

            <CollectionsPanel
                isOpen={showCollectionsPanel}
                onClose={onCollectionsPanelClose}
            />

            <SelectCollectionModal
                isOpen={showSelectCollection}
                onClose={onSelectCollectionClose}
                collections={collections}
                onSelect={onSelectCollection}
            />

        </>
    );
}
