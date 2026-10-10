import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { cpSync, mkdirSync } from 'node:fs';
export default defineConfig({
 plugins:[react(),{name:'local-mathlive-assets',closeBundle(){mkdirSync('dist/mathlive',{recursive:true});cpSync('node_modules/mathlive/fonts','dist/mathlive/fonts',{recursive:true});cpSync('node_modules/mathlive/sounds','dist/mathlive/sounds',{recursive:true});}}],
 build:{rollupOptions:{output:{manualChunks:{mathlive:['mathlive'],katex:['katex'],react:['react','react-dom']}}}},
 server:{proxy:{'/api':'http://127.0.0.1:8765'},fs:{allow:['.']}},
});
