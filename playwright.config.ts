import {defineConfig} from '@playwright/test';
import {existsSync} from 'node:fs';
import {resolve} from 'node:path';
const python='"'+resolve(process.platform==='win32'?'.venv-win/Scripts/python.exe':'.venv/bin/python')+'"';
const portable=resolve('.tools/tesseract/usr/lib/x86_64-linux-gnu');
export default defineConfig({testDir:'./tests/browser',timeout:45000,workers:1,use:{baseURL:'http://127.0.0.1:8767',viewport:{width:1440,height:1000},screenshot:'only-on-failure',trace:'retain-on-failure',launchOptions:{env:{...process.env,LD_LIBRARY_PATH:existsSync(portable)?portable:(process.env.LD_LIBRARY_PATH||'')}}},webServer:{command:python+' -m uvicorn backend.app:app --host 127.0.0.1 --port 8767',url:'http://127.0.0.1:8767/api/health',reuseExistingServer:false,timeout:30000,env:{MATHMASTER_PHONEPAD_PORT:'18766',MATHMASTER_DATA:resolve('.test-data/'+process.pid),MATHMASTER_ALLOWED_ORIGINS:'http://127.0.0.1:8767'}}});
