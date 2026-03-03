const fs = require('fs');

const path = 'frontend_v2/src/pages/Dashboard.jsx';
let content = fs.readFileSync(path, 'utf8');

// Inside Dashboard component, add scrollParent state
if (!content.includes('const [scrollParent, setScrollParent] = useState(null);')) {
    content = content.replace(
        'const [viewMode, setViewMode] = useState(\'grid\');',
        'const [viewMode, setViewMode] = useState(\'grid\');\n    const [scrollParent, setScrollParent] = useState(null);\n\n    useEffect(() => {\n        // On mount, find the layout main scroll container if we are on desktop.\n        // On mobile, the window itself scrolls, so we leave it null.\n        const mainContainer = document.getElementById(\'main-scroll-container\');\n        if (mainContainer) {\n            // Check if it actually has overflow (desktop mode in Layout.jsx uses lg:overflow-y-auto)\n            const style = window.getComputedStyle(mainContainer);\n            if (style.overflowY === \'auto\' || style.overflowY === \'scroll\') {\n                setScrollParent(mainContainer);\n            }\n        }\n    }, []);'
    );
}

// Update VirtuosoGrid props
content = content.replace(
    '<VirtuosoGrid\n                                    useWindowScroll',
    '{...scrollParent ? { customScrollParent: scrollParent } : { useWindowScroll: true }}\n                                    // Remove old useWindowScroll prop\n                                    // useWindowScroll is replaced by the spread above'
);
content = content.replace(
    '                                    // Remove old useWindowScroll prop\n                                    // useWindowScroll is replaced by the spread above',
    ''
);

// We need to properly replace it. Let's do a strict replace
content = content.replace(
    '<VirtuosoGrid\n                                    useWindowScroll',
    '<VirtuosoGrid\n                                    {...(scrollParent ? { customScrollParent: scrollParent } : { useWindowScroll: true })}'
);

fs.writeFileSync(path, content);
console.log("Updated Dashboard.jsx");
