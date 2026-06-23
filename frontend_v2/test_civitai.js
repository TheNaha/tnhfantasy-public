const url = "https://image.civitai.com/x/cache/x/y/z.jpeg";
console.log(url.replace(/(\.jpeg|\.png|\.webp)/, '/width=450$1'));
