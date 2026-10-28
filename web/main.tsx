import { createRoot } from 'react-dom/client';
import App from './App';
import {InkWorkspace} from './InkWorkspace';
import './styles.css';
import './skins.css';
if(location.pathname==='/mobile'){
 document.body.classList.add('mobile-body');
 void import('./mobile/MobileApp').then(({default:MobileApp})=>createRoot(document.getElementById('root')!).render(<MobileApp/>));
}else createRoot(document.getElementById('root')!).render(<InkWorkspace><App/></InkWorkspace>);
