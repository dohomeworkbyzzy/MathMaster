"""Same-origin helper window for browsers that block public HTTP -> loopback fetch."""
HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>MathMaster Touchpad</title><style>body{font:16px system-ui;margin:30px;line-height:1.8}button{padding:8px 18px}#status{white-space:pre-wrap}</style><h2>MathMaster 本机触控板</h2><p id="status">正在连接本机触控板…</p><p>保持此窗口开启，返回题目页面，用外接鼠标选择草稿落笔位置。</p><button id="stop">断开连接</button><script>
'use strict';
const params=new URLSearchParams(location.hash.slice(1)),target=params.get('origin'),nonce=params.get('nonce'),code=params.get('code');
history.replaceState(null,'','/connect');
const status=document.getElementById('status');
let token=null,source=null,ended=false,stopping=null;
function send(data){if(window.opener)window.opener.postMessage({...data,nonce},target);}
function stop(){if(stopping)return stopping;ended=true;source?.close();stopping=token?fetch('/api/touchpad/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token}),keepalive:true}).catch(()=>{}):Promise.resolve();status.textContent='已断开，可以关闭此窗口。';return stopping;}
window.addEventListener('message',async e=>{if(e.source===window.opener&&e.origin===target&&e.data?.nonce===nonce&&e.data?.type==='stop'){await stop();window.close();}});
window.addEventListener('pagehide',stop);
document.getElementById('stop').onclick=()=>{send({type:'error',message:'本机助手已断开。'});stop();};
(async()=>{try{
 const parsed=new URL(target);if(!['http:','https:'].includes(parsed.protocol)||parsed.origin!==target||!window.opener||!nonce||!/^[0-9]{8}$/.test(code||''))throw new Error('请从 MathMaster 页面点击连接。');
 const response=await fetch('/api/touchpad/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});
 const session=await response.json();if(!response.ok)throw new Error(session.detail||'连接失败');token=session.token;
 if(ended){stopping=null;await stop();return;}
 source=new EventSource('/api/touchpad/events?token='+encodeURIComponent(token));
 source.onmessage=e=>{try{send({type:'ink',event:JSON.parse(e.data)});}catch{}};
 source.onerror=()=>{send({type:'error',message:'本机触控板连接已断开，请重新连接。'});stop();};
 send({type:'ready',session});status.textContent='已连接 '+target+'\n请返回题目页面书写。';window.opener.focus();
}catch(error){status.textContent=error.message;try{send({type:'error',message:error.message});}catch{}stop();}})();
</script></html>'''
