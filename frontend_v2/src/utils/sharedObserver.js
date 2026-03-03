/**
 * A shared IntersectionObserver instance for lazy loading images.
 * This prevents creating hundreds of individual observers when rendering
 * large grids of images (like in the gallery view).
 */
let observer = null;
const callbacks = new WeakMap();

/**
 * Initializes the shared observer if it hasn't been created yet.
 */
function getObserver() {
    if (!observer && typeof IntersectionObserver !== 'undefined') {
        observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        const callback = callbacks.get(entry.target);
                        if (callback) {
                            callback();
                            // Once intersecting, we can stop observing
                            observer.unobserve(entry.target);
                            callbacks.delete(entry.target);
                        }
                    }
                });
            },
            {
                rootMargin: '200px', // Start loading 200px before entering viewport
            }
        );
    }
    return observer;
}

/**
 * Registers an element to be observed for intersection.
 *
 * @param {Element} element The DOM element to observe.
 * @param {Function} callback The function to call when the element intersects.
 */
export function observeIntersection(element, callback) {
    if (!element) return;

    callbacks.set(element, callback);
    const obs = getObserver();
    if (obs) {
        obs.observe(element);
    } else {
        // Fallback if IntersectionObserver is not supported
        callback();
    }
}

/**
 * Unregisters an element from the shared observer.
 *
 * @param {Element} element The DOM element to stop observing.
 */
export function unobserveIntersection(element) {
    if (!element) return;

    callbacks.delete(element);
    if (observer) {
        observer.unobserve(element);
    }
}
