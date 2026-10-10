import {createHash} from 'node:crypto';
import {readdirSync,readFileSync,writeFileSync} from 'node:fs';
function files(dir){return readdirSync(dir,{withFileTypes:true}).flatMap(f=>f.isDirectory()?files(dir+'/'+f.name):[dir+'/'+f.name]);}
const paths=[...files('web'),'index.html','vite.config.ts','tsconfig.json','package.json','package-lock.json'].sort();
const signature=paths.map(p=>p+'\n'+createHash('sha256').update(readFileSync(p)).digest('hex')+'\n').join('');
writeFileSync('dist/.source-hash',createHash('sha256').update(signature).digest('hex'));
