const fs = require('fs');

const path = 'frontend_v2/src/components/Layout.jsx';
let content = fs.readFileSync(path, 'utf8');

content = content.replace(
  '<main className="flex-1 lg:overflow-y-auto px-2 py-3 sm:p-4 lg:p-8">',
  '<main id="main-scroll-container" className="flex-1 lg:overflow-y-auto px-2 py-3 sm:p-4 lg:p-8">'
);

fs.writeFileSync(path, content);
console.log("Updated Layout.jsx with id='main-scroll-container'");
