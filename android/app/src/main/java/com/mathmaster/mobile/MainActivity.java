package com.mathmaster.mobile;

import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import org.json.*;
import java.net.*;
import java.util.*;

public class MainActivity extends Activity {
    private WebView web;
    private TextView empty;
    private LinearLayout emptyPanel;
    private ProgressBar progress;
    private SharedPreferences prefs;
    private ValueCallback<Uri[]> fileCallback;
    private String server = "";
    private int connectionGeneration = 0;
    private static final int PICK_FILE = 42;


    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences("servers", MODE_PRIVATE);
        server = prefs.getString("active", "");
        getWindow().setStatusBarColor(Color.rgb(36,90,70));
        getWindow().setNavigationBarColor(Color.rgb(250,252,248));
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(Color.rgb(244,246,242));
        progress = new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal); root.addView(progress,new LinearLayout.LayoutParams(-1,dp(3)));
        emptyPanel = new LinearLayout(this); emptyPanel.setOrientation(LinearLayout.VERTICAL); emptyPanel.setPadding(dp(22),dp(20),dp(22),dp(20));
        empty = new TextView(this); empty.setTextSize(16); empty.setPadding(0,dp(20),0,dp(24)); empty.setText("欢迎使用 MathMaster 随身练\n\n进入设置，填写网站域名或电脑的 IP 地址和端口。\n\n网站连接成功后，可在页面底部「设置」中管理服务器地址。"); emptyPanel.addView(empty);
        Button config = new Button(this); config.setText("设置"); config.setOnClickListener(v -> showConnectionSettings()); emptyPanel.addView(config); root.addView(emptyPanel);
        web = new WebView(this); root.addView(web,new LinearLayout.LayoutParams(-1,0,1)); setContentView(root);
        WebSettings settings = web.getSettings(); settings.setUserAgentString(settings.getUserAgentString()+" MathMasterMobile/0.1.1"); settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true); settings.setAllowFileAccess(false); settings.setAllowContentAccess(true); settings.setBuiltInZoomControls(true); settings.setDisplayZoomControls(false); settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        android.webkit.CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri=request.getUrl();
                if ("mathmaster".equals(uri.getScheme()) && "settings".equals(uri.getHost()) && "/servers".equals(uri.getPath())) {
                    if (sameOrigin(Uri.parse(view.getUrl()==null?"":view.getUrl())) && "/mobile".equals(Uri.parse(view.getUrl()).getPath())) showServers();
                    return true;
                }
                if (sameOrigin(uri) && !"/".equals(uri.getPath())) return false;
                if (sameOrigin(uri)) { view.loadUrl(server+"/mobile"); return true; }
                if ("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW,uri)); } catch(ActivityNotFoundException ignored) { toast("没有可用的浏览器"); }
                }
                return true;
            }
            @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap favicon) { emptyPanel.setVisibility(View.GONE); progress.setVisibility(View.VISIBLE); }
            @Override public void onPageFinished(WebView view,String url) { progress.setVisibility(View.GONE); }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error) {
                if(request.isForMainFrame()) showError("网站连接失败："+error.getDescription()+"\n检查服务器是否在线；请进入设置修改服务器地址。");
            }
            @Override public void onReceivedHttpError(WebView view,WebResourceRequest request,WebResourceResponse response) {
                if(request.isForMainFrame()) showError("网站返回 HTTP "+response.getStatusCode()+"。检查网站版本及该域名 / IP 是否已允许访问。");
            }
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public void onProgressChanged(WebView view,int value) { progress.setProgress(value); progress.setVisibility(value<100?View.VISIBLE:View.GONE); }
            @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params) {
                if(fileCallback!=null) fileCallback.onReceiveValue(null); fileCallback=callback;
                Intent intent=new Intent(Intent.ACTION_GET_CONTENT); intent.setType("image/*"); intent.addCategory(Intent.CATEGORY_OPENABLE); intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,params.getMode()==FileChooserParams.MODE_OPEN_MULTIPLE);
                try { startActivityForResult(Intent.createChooser(intent,"选择纸上作答照片"),PICK_FILE); } catch(ActivityNotFoundException e) { fileCallback.onReceiveValue(null); fileCallback=null; toast("没有可用的图片选择器"); }
                return true;
            }
            @Override public boolean onJsBeforeUnload(WebView view,String url,String message,JsResult result) {
                new AlertDialog.Builder(MainActivity.this).setTitle("记录尚未同步").setMessage("文字仍暂存在此手机的网站存储中。离开前可返回页面上传，图片上传中请先等待完成。").setPositiveButton("离开",(d,w)->result.confirm()).setNegativeButton("返回保存",(d,w)->result.cancel()).setOnCancelListener(d->result.cancel()).show(); return true;
            }
        });
        if(server.isEmpty()) { web.setVisibility(View.GONE); progress.setVisibility(View.GONE); }
        else loadServer();
    }
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private void toast(String s){Toast.makeText(this,s,Toast.LENGTH_LONG).show();}
    private boolean sameOrigin(Uri uri){try { URI a=new URI(server),b=new URI(uri.toString()); return a.getScheme().equalsIgnoreCase(b.getScheme()) && a.getHost().equalsIgnoreCase(b.getHost()) && port(a)==port(b); }catch(Exception e){return false;}}
    private int port(URI u){return u.getPort()>=0?u.getPort():("https".equals(u.getScheme())?443:80);}
    private void showError(String s){empty.setText(s); emptyPanel.setVisibility(View.VISIBLE); progress.setVisibility(View.GONE);}
    private void loadServer(){
        android.content.pm.PackageInfo runtime=WebView.getCurrentWebViewPackage();
        try { if(runtime!=null && Integer.parseInt(runtime.versionName.split("\\.")[0])<111){web.setVisibility(View.GONE);showError("网站连接已保存。\n\n此设备的 Android System WebView 版本过旧（"+runtime.versionName+"）。请先从系统应用商店更新 Android System WebView 或 Chrome，再重新打开 App。");return;} }catch(NumberFormatException ignored){}
        emptyPanel.setVisibility(View.GONE);web.setVisibility(View.VISIBLE);web.loadUrl(server+"/mobile");
    }
    private void showConnectionSettings(){
        new AlertDialog.Builder(this).setTitle("设置").setItems(new String[]{"网站服务器","重新连接"},(d,which)->{if(which==0)showServers();else if(!server.isEmpty())loadServer();else showServers();}).setNegativeButton("关闭",null).show();
    }
    private JSONArray servers(){try{return new JSONArray(prefs.getString("list","[]"));}catch(Exception e){return new JSONArray();}}
    private void showServers(){
        JSONArray list=servers(); ArrayList<String> labels=new ArrayList<>();
        for(int i=0;i<list.length();i++) labels.add((list.optString(i).equals(server)?"✓ ":"")+list.optString(i));
        labels.add("＋ 添加 IP、端口或域名");
        new AlertDialog.Builder(this).setTitle("网站服务器 · 点击测试 / 编辑").setItems(labels.toArray(new String[0]),(d,which)->editServer(which<list.length()?which:-1)).setNegativeButton("关闭",null).show();
    }
    static String normalize(String text) throws Exception {
        String value=text.trim(); if(!value.contains("://")) value="http://"+value;
        URI uri=new URI(value); String scheme=uri.getScheme().toLowerCase(Locale.ROOT);
        if(!Arrays.asList("http","https").contains(scheme)||uri.getHost()==null||uri.getRawUserInfo()!=null||uri.getRawQuery()!=null||uri.getRawFragment()!=null||uri.getPort()>65535||uri.getPort()==0) throw new Exception("请输入有效的 http(s) 域名或 IP＋端口。");
        if(uri.getPath()!=null&&!uri.getPath().isEmpty()&&!uri.getPath().equals("/")&&!uri.getPath().equals("/mobile")) throw new Exception("填写网站根地址即可，不要附加页面路径。");
        return new URI(scheme,null,uri.getHost().toLowerCase(Locale.ROOT),uri.getPort(),null,null,null).toASCIIString();
    }
    private void editServer(int index){
        JSONArray list=servers(); LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(dp(22),dp(8),dp(22),dp(8));
        TextView hint=new TextView(this);hint.setText("输入域名或 IP:端口。IP 变化后在这里修改；域名可同时包含端口。省略协议时使用 http。"); box.addView(hint);
        EditText input=new EditText(this);input.setSingleLine(true);input.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_URI);input.setHint("https://域名 或 http://IP:8765"); if(index>=0)input.setText(list.optString(index)); box.addView(input);
        TextView status=new TextView(this); status.setPadding(0,dp(14),0,dp(10));box.addView(status);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(index>=0?"编辑 / 切换服务器":"添加服务器").setView(box).setPositiveButton("测试并连接",null).setNeutralButton(index>=0?"删除地址":"取消",null).setNegativeButton("关闭",null).create();
        dialog.setOnShowListener(d->{
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v->{if(index>=0){JSONArray next=new JSONArray();for(int i=0;i<list.length();i++)if(i!=index)next.put(list.optString(i));prefs.edit().putString("list",next.toString()).apply();}dialog.dismiss();showServers();});
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
                final String candidate;try{candidate=normalize(input.getText().toString());}catch(Exception e){status.setText(e.getMessage());return;}
                int generation=++connectionGeneration;status.setText("正在测试网站及手机页面…");dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
                new Thread(()->{String failure=null;try{probe(candidate+"/api/health",true);probe(candidate+"/mobile",false);}catch(Exception e){failure=e.getMessage();}final String result=failure;
                    runOnUiThread(()->{if(isDestroyed()||!dialog.isShowing()||generation!=connectionGeneration)return;dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true);if(result!=null){status.setText("连接失败："+result+"\n请检查网络、服务端口及网站地址访问许可。");return;}
                        JSONArray next=new JSONArray();boolean exists=false;for(int i=0;i<list.length();i++){if(i==index)continue;String s=list.optString(i);next.put(s);if(s.equals(candidate))exists=true;}if(!exists)next.put(candidate);
                        prefs.edit().putString("list",next.toString()).putString("active",candidate).apply();server=candidate;dialog.dismiss();loadServer();toast("网站连接成功");
                    });
                }).start();
            });
        }); dialog.show();
    }
    private void probe(String url,boolean health) throws Exception {
        HttpURLConnection connection=(HttpURLConnection)new URL(url).openConnection(); connection.setConnectTimeout(10000);connection.setReadTimeout(10000);connection.setInstanceFollowRedirects(false);
        try{int code=connection.getResponseCode();if(code!=200)throw new Exception("HTTP "+code+"："+(code==403?"网站尚未允许此 IP / 域名访问":code==404?"网站缺少手机页面，请更新电脑端":"请检查完整地址及协议"));
            java.io.ByteArrayOutputStream output=new java.io.ByteArrayOutputStream(); byte[] buffer=new byte[4096]; int count; try(java.io.InputStream stream=connection.getInputStream()){while(output.size()<16384 && (count=stream.read(buffer,0,Math.min(buffer.length,16384-output.size())))!=-1)output.write(buffer,0,count);} String content=output.toString("UTF-8");
            if(health&&!"ok".equals(new JSONObject(content).optString("status")))throw new Exception("地址不是可用的 MathMaster 服务");
            if(!health&&!content.contains("id=\"root\""))throw new Exception("手机页面不可用，请构建新版前端");
        }finally{connection.disconnect();}
    }
    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){super.onActivityResult(requestCode,resultCode,data);if(requestCode==PICK_FILE&&fileCallback!=null){ArrayList<Uri> uris=new ArrayList<>();if(resultCode==RESULT_OK&&data!=null){if(data.getClipData()!=null){for(int i=0;i<data.getClipData().getItemCount();i++)uris.add(data.getClipData().getItemAt(i).getUri());}else if(data.getData()!=null)uris.add(data.getData());}fileCallback.onReceiveValue(uris.isEmpty()?null:uris.toArray(new Uri[0]));fileCallback=null;}}
    @Override public void onBackPressed(){web.evaluateJavascript("(()=>{const lightbox=document.querySelector('.m-lightbox>button');if(lightbox){lightbox.click();return true;}const back=document.querySelector('.m-back');if(back){back.click();return true;}return false;})()",value->{if(!"true".equals(value))new AlertDialog.Builder(this).setTitle("退出随身练？").setMessage("未上传文字会暂存在手机。网站上的 AI 任务仍会继续执行。").setPositiveButton("退出",(d,w)->finish()).setNegativeButton("继续练习",null).show();});}
    @Override protected void onDestroy(){connectionGeneration++;if(fileCallback!=null){fileCallback.onReceiveValue(null);fileCallback=null;}if(web!=null){web.stopLoading();web.destroy();}super.onDestroy();}
}
