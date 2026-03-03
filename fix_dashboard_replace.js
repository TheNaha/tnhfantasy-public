const fs = require('fs');
const path = 'frontend_v2/src/pages/Dashboard.jsx';
let content = fs.readFileSync(path, 'utf8');

// Add scrollParent state
let updated = content.replace(
    /const \[viewMode, setViewMode\] = useState\('grid'\);/,
    `const [viewMode, setViewMode] = useState('grid');
    const [scrollParent, setScrollParent] = useState(null);

    useEffect(() => {
        const handleResize = () => {
            const mainContainer = document.getElementById('main-scroll-container');
            if (mainContainer) {
                const style = window.getComputedStyle(mainContainer);
                if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                    setScrollParent(mainContainer);
                } else {
                    setScrollParent(null);
                }
            }
        };
        handleResize();
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);`
);

// We should replace useWindowScroll on VirtuosoGrid
updated = updated.replace(
    /<VirtuosoGrid\s+useWindowScroll/,
    `<VirtuosoGrid
                                    {...(scrollParent ? { customScrollParent: scrollParent } : { useWindowScroll: true })}`
);

fs.writeFileSync(path, updated);
console.log("Re-ran fix for Dashboard.jsx");
