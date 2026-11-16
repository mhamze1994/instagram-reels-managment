package ir.farjadsamaneh.quizstudio;
import android.app.*;
import android.os.*;
import android.content.*;
import android.net.Uri;
import android.webkit.*;
import android.widget.*;
import android.view.*;
import android.graphics.Color;
import android.util.Base64;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.concurrent.*;

public final class StudioActivity extends Activity {
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private WebView web;
    private TextView status;
    private String origin, username="quiz", password="";
    private ValueCallback<Uri[]> chooser;
    private File pendingSave;
    private boolean busy;
    @Override public void onCreate(Bundle state){super.onCreate(state);login();}
    private EditText input(LinearLayout box,String hint,String value,boolean secret){
        EditText f=new EditText(this);f.setHint(hint);f.setText(value);f.setSingleLine(true);f.setInputType(secret?129:1);box.addView(f);return f;
    }
    private void login(){
        if(web!=null){web.stopLoading();web.destroy();web=null;}password="";
        LinearLayout box=new LinearLayout(this);box.setOrientation(1);box.setPadding(24,60,24,24);
        TextView title=new TextView(this);title.setText("اتاق محتوا — ورود به پنل");title.setTextSize(23);box.addView(title);
        EditText address=input(box,"آدرس سرور",getPreferences(0).getString("origin","http://217.219.165.49"),false);
        EditText user=input(box,"نام کاربری","quiz",false),pass=input(box,"رمز پنل","",true);
        Button enter=new Button(this);enter.setText("ورود");box.addView(enter);
        TextView message=new TextView(this);box.addView(message);setContentView(box);
        enter.setOnClickListener(v->{try{
            Uri p=Uri.parse(address.getText().toString().trim());
            if(!("http".equals(p.getScheme())||"https".equals(p.getScheme()))||p.getHost()==null||p.getUserInfo()!=null||p.getQuery()!=null||p.getFragment()!=null||!(p.getPath()==null||p.getPath().isEmpty()||p.getPath().equals("/")))throw new Exception("آدرس باید مثل http://217.219.165.49 باشد");
            origin=p.getScheme()+"://"+p.getEncodedAuthority();username=user.getText().toString().trim();password=pass.getText().toString();
            enter.setEnabled(false);message.setText("در حال اتصال…");
            worker.execute(()->{try{HttpURLConnection c=connection("/api/info");try{int code=c.getResponseCode();if(code==401||code==403)throw new IOException("نام کاربری یا رمز صحیح نیست");if(code!=200)throw new IOException("خطای سرور: "+code);}finally{c.disconnect();}
                runOnUiThread(()->{getPreferences(0).edit().putString("origin",origin).apply();showPanel();});
            }catch(Exception e){runOnUiThread(()->{enter.setEnabled(true);message.setText("اتصال انجام نشد: "+e.getMessage());});}});
        }catch(Exception e){message.setText(e.getMessage());}});
    }
    private String authorization(){return "Basic "+Base64.encodeToString((username+":"+password).getBytes(java.nio.charset.StandardCharsets.UTF_8),Base64.NO_WRAP);}
    private HttpURLConnection connection(String path)throws IOException{
        HttpURLConnection c=(HttpURLConnection)new URL(origin+path).openConnection();c.setInstanceFollowRedirects(false);c.setConnectTimeout(20000);c.setReadTimeout(60000);c.setRequestProperty("Authorization",authorization());return c;
    }
    private boolean trusted(String url){try{Uri u=Uri.parse(url),o=Uri.parse(origin);return o.getScheme().equals(u.getScheme())&&o.getEncodedAuthority().equals(u.getEncodedAuthority());}catch(Exception e){return false;}}
    private void showPanel(){
        LinearLayout root=new LinearLayout(this);root.setOrientation(1);
        root.setOnApplyWindowInsetsListener((v,i)->{if(Build.VERSION.SDK_INT>=30){android.graphics.Insets b=i.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());v.setPadding(b.left,b.top,b.right,b.bottom);}else v.setPadding(0,i.getSystemWindowInsetTop(),0,i.getSystemWindowInsetBottom());return i;});
        LinearLayout bar=new LinearLayout(this);addButton(bar,"اشتراک",()->selection("share"));addButton(bar,"کپشن",()->selection("copy"));addButton(bar,"کاور",()->selection("cover"));addButton(bar,"خروج",()->{if(!busy)login();});root.addView(bar);
        status=new TextView(this);status.setPadding(12,4,12,4);status.setText("در حال بارگذاری…");root.addView(status);
        web=new WebView(this);root.addView(web,new LinearLayout.LayoutParams(-1,0,1));setContentView(root);root.requestApplyInsets();
        WebSettings s=web.getSettings();s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);s.setAllowFileAccess(false);s.setAllowContentAccess(false);s.setJavaScriptCanOpenWindowsAutomatically(false);s.setSupportMultipleWindows(false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){String url=r.getUrl().toString();if(url.startsWith("quizstudio://")&&r.isForMainFrame()&&r.hasGesture()&&trusted(v.getUrl())){String a=r.getUrl().getHost();if("share".equals(a)||"copy".equals(a)||"cover".equals(a))selection(a);return true;}return !trusted(url);}
            @Override public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r){if(!trusted(r.getUrl().toString()))return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));return null;}
            @Override public void onReceivedHttpAuthRequest(WebView v,HttpAuthHandler h,String host,String realm){if(Uri.parse(origin).getHost().equals(host))h.proceed(username,password);else h.cancel();}
            @Override public void onReceivedError(WebView v,WebResourceRequest r,WebResourceError e){if(r.isForMainFrame())status.setText("خطای اتصال: "+e.getDescription());}
            @Override public void onPageFinished(WebView v,String url){if(!trusted(url))return;status.setText("متصل • ابتدا یک ویدیو را باز کن");
                v.evaluateJavascript("(function(){if(window.quizNativeInstalled)return;window.quizNativeInstalled=true;function hook(){[['share-button','share'],['copy-caption','copy'],['download-cover','cover']].forEach(function(a){var b=document.getElementById(a[0]);if(!b)return;if(b.disabled)b.disabled=false;b.onclick=function(e){e.preventDefault();e.stopImmediatePropagation();location.href='quizstudio://'+a[1];return false;};});}new MutationObserver(hook).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled']});hook();})()",null);
            }
        });
        web.setWebChromeClient(new WebChromeClient(){@Override public boolean onShowFileChooser(WebView v,ValueCallback<Uri[]> cb,FileChooserParams p){if(chooser!=null)chooser.onReceiveValue(null);chooser=cb;Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT);i.setType("*/*");i.addCategory(Intent.CATEGORY_OPENABLE);i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);try{startActivityForResult(i,41);}catch(Exception e){chooser.onReceiveValue(null);chooser=null;}return true;}});
        web.setDownloadListener((url,ua,d,m,size)->{if(trusted(url))selection(url.contains("cover")?"cover":"save");});
        java.util.HashMap<String,String> headers=new java.util.HashMap<>();headers.put("Authorization",authorization());web.loadUrl(origin+"/",headers);
    }
    private void addButton(LinearLayout bar,String text,Runnable action){Button b=new Button(this);b.setText(text);b.setTextSize(12);b.setPadding(2,0,2,0);bar.addView(b,new LinearLayout.LayoutParams(0,-2,1));b.setOnClickListener(v->action.run());}
    private void selection(String action){
        if(busy||web==null||!trusted(web.getUrl()))return;
        web.evaluateJavascript("JSON.stringify({url:document.querySelector('#detail-video')?.getAttribute('src')||'',cover:document.querySelector('#detail-video')?.getAttribute('poster')||'',caption:document.querySelector('#edit-caption')?.value||'',open:!!document.querySelector('#video-dialog[open]')})",raw->{try{
            String decoded=new JSONArray("["+raw+"]").getString(0);JSONObject data=new JSONObject(decoded);if(!data.optBoolean("open"))throw new Exception("ابتدا یک ویدیو را از کتابخانه باز کن");String caption=data.optString("caption");if(caption.length()>10000)throw new Exception("کپشن بیش از حد طولانی است");
            if("copy".equals(action)){copy(caption);status.setText("کپشن کپی شد");return;}
            String path=data.getString("cover".equals(action)?"cover":"url");if(path.startsWith(origin+"/"))path=path.substring(origin.length());
            if(!path.matches("/media/[a-f0-9]{32}/(video\\.mp4|cover\\.jpg)"))throw new Exception("مسیر فایل نامعتبر است");download(path,action,caption);
        }catch(Exception e){status.setText(e.getMessage());}});
    }
    private void copy(String text){((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("caption",text));}
    private void download(String path,String action,String caption){
        busy=true;status.setText("در حال دریافت فایل…");worker.execute(()->{try{
            File dir=new File(getCacheDir(),"shared");dir.mkdirs();String id=path.split("/")[2];boolean image=path.endsWith(".jpg");File file=new File(dir,id+(image?".jpg":".mp4"));
            if(!file.isFile()){File part=new File(dir,file.getName()+".part");HttpURLConnection c=connection(path);try{
                if(c.getResponseCode()!=200)throw new IOException("دریافت فایل ناموفق: "+c.getResponseCode());long total=c.getContentLengthLong(),count=0,last=0;
                try(InputStream in=c.getInputStream();OutputStream out=new FileOutputStream(part)){byte[] buf=new byte[65536];int n;while((n=in.read(buf))!=-1){count+=n;if(count>512L*1024*1024)throw new IOException("فایل بزرگ‌تر از ۵۱۲ مگابایت است");out.write(buf,0,n);if(count-last>512*1024){last=count;final long done=count;runOnUiThread(()->status.setText("دریافت: "+(total>0?done*100/total+"٪":done/1048576+" MB")));}}}
                if(count==0||(total>0&&count!=total))throw new IOException("فایل کامل دریافت نشد");if(!part.renameTo(file))throw new IOException("ذخیره فایل ناموفق");
            }finally{c.disconnect();part.delete();}}
            runOnUiThread(()->{busy=false;try{
                if("cover".equals(action)||"save".equals(action)){pendingSave=file;Intent save=new Intent(Intent.ACTION_CREATE_DOCUMENT);save.addCategory(Intent.CATEGORY_OPENABLE);save.setType(image?"image/jpeg":"video/mp4");save.putExtra(Intent.EXTRA_TITLE,"quiz-"+file.getName());startActivityForResult(save,42);status.setText("محل ذخیره را انتخاب کن");return;}
                copy(caption);Uri uri=Uri.parse("content://ir.farjadsamaneh.quizstudio.files/"+file.getName());Intent send=new Intent(Intent.ACTION_SEND);send.setType("video/mp4");send.putExtra(Intent.EXTRA_STREAM,uri);send.setClipData(ClipData.newRawUri("video",uri));send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivity(Intent.createChooser(send,"اشتراک ویدیو — Instagram"));status.setText("کپشن کپی شد؛ Instagram را انتخاب کن");
            }catch(Exception e){status.setText("خطا: "+e.getMessage());}});
        }catch(Exception e){runOnUiThread(()->{busy=false;if(status!=null)status.setText("خطا: "+e.getMessage());});}});
    }
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);
        if(request==41&&chooser!=null){chooser.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result,data));chooser=null;}
        if(request==42&&result==RESULT_OK&&data!=null&&pendingSave!=null){File file=pendingSave;Uri destination=data.getData();worker.execute(()->{try(InputStream in=new FileInputStream(file);OutputStream out=getContentResolver().openOutputStream(destination)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)out.write(b,0,n);runOnUiThread(()->status.setText("فایل ذخیره شد"));}catch(Exception e){runOnUiThread(()->status.setText("ذخیره ناموفق: "+e.getMessage()));}});}
    }
    @Override public void onBackPressed(){if(web!=null&&web.canGoBack())web.goBack();else super.onBackPressed();}
    @Override protected void onDestroy(){if(chooser!=null)chooser.onReceiveValue(null);if(web!=null)web.destroy();worker.shutdown();super.onDestroy();}
}
