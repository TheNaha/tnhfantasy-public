const fs = require('fs');

const path = 'src/pages/SimpleGenerator.jsx';
let content = fs.readFileSync(path, 'utf8');

content = content.replace(
    /className="flex-1 min-w-0 h-1\.5 accent-blue-500"/g,
    `className="flex-1 min-w-0 h-1.5 accent-blue-500 touch-none"
                                                        onTouchStart={(e) => e.stopPropagation()}
                                                        onTouchMove={(e) => e.stopPropagation()}`
);

fs.writeFileSync(path, content);
