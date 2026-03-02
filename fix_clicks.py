with open('frontend_v2/src/pages/Dashboard.jsx', 'r') as f:
    content = f.read()

content = content.replace("<div onClick={handleImageClick} className=\"flex-shrink-0 w-32 bg-gray-800 rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-blue-500 transition-all\">", "<div onClick={() => handleImageClick(item)} className=\"flex-shrink-0 w-32 bg-gray-800 rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-blue-500 transition-all\">")

with open('frontend_v2/src/pages/Dashboard.jsx', 'w') as f:
    f.write(content)
