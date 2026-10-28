using System;
using System.Drawing;
using System.IO;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]

class RemoteClient : Form
{
    const string Server = "http://39.129.11.4:8509";
    readonly WebView2 browser = new WebView2();
    readonly ToolStrip toolbar = new ToolStrip();
    readonly ToolStripButton compact = new ToolStripButton("小窗");
    readonly ToolStripButton pin = new ToolStripButton("置顶");
    readonly ToolStripLabel status = new ToolStripLabel("正在连接…");
    readonly ToolStripButton zoomLabel = new ToolStripButton("100%");
    readonly string settingsPath;
    double zoom = 1;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    Rectangle savedBounds;
    FormWindowState savedState;
    bool isCompact, testStarted;
    readonly string testOutput;

    [DllImport("user32.dll")] static extern IntPtr GetThreadDpiAwarenessContext();
    [DllImport("user32.dll")] static extern bool AreDpiAwarenessContextsEqual(IntPtr first, IntPtr second);
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr context);

    [STAThread]
    static void Main(string[] args)
    {
        // Select native rendering before any HWND or WebView is created.
        try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch (EntryPointNotFoundException) { }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new RemoteClient(args.Length == 2 && args[0] == "--self-test" ? args[1] : null));
    }

    RemoteClient(string output)
    {
        testOutput = output;
        settingsPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MathMasterClient", output == null ? "zoom.txt" : "acceptance-zoom.txt");
        double savedZoom;
        if (File.Exists(settingsPath) && double.TryParse(File.ReadAllText(settingsPath), NumberStyles.Float, CultureInfo.InvariantCulture, out savedZoom))
            zoom = Math.Max(.8, Math.Min(2, savedZoom));
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        Text = "MathMaster — " + Server;
        StartPosition = FormStartPosition.CenterScreen;
        Size = new Size(1200, 820);
        MinimumSize = new Size(520, 420);
        Font = new Font("Microsoft YaHei UI", 9);
        browser.Dock = DockStyle.Fill;
        toolbar.GripStyle = ToolStripGripStyle.Hidden;
        toolbar.Items.Add(compact);
        toolbar.Items.Add(pin);
        toolbar.Items.Add(new ToolStripSeparator());
        var zoomOut = toolbar.Items.Add("A−");
        toolbar.Items.Add(zoomLabel);
        var zoomIn = toolbar.Items.Add("A+");
        zoomOut.ToolTipText = "缩小页面（Ctrl + −）";
        zoomIn.ToolTipText = "放大页面（Ctrl + +）";
        zoomLabel.ToolTipText = "恢复 100% 清晰显示（Ctrl + 0）";
        zoomLabel.Text = Math.Round(zoom * 100) + "%";
        zoomOut.Click += (s, e) => SetZoom(zoom - .1);
        zoomIn.Click += (s, e) => SetZoom(zoom + .1);
        zoomLabel.Click += (s, e) => SetZoom(1);
        var reload = toolbar.Items.Add("重新连接");
        toolbar.Items.Add(new ToolStripSeparator());
        toolbar.Items.Add(status);
        Controls.Add(browser);
        Controls.Add(toolbar);
        compact.Click += async (s, e) => {
            if (browser.CoreWebView2 == null) { ChangeWindow(isCompact ? "restore" : "compact"); return; }
            // Use the page action so its autosave and layout state follow the native window.
            string result = await browser.ExecuteScriptAsync(@"(() => {
                const b = document.querySelector('[aria-label=""收缩窗口""], [aria-label=""还原窗口""]');
                if (!b) return false; b.click(); return true;
            })()");
            if (result != "true") ChangeWindow(isCompact ? "restore" : "compact");
        };
        pin.Click += (s, e) => { TopMost = !TopMost; pin.Checked = TopMost; };
        reload.Click += (s, e) => { if (browser.CoreWebView2 != null) browser.CoreWebView2.Navigate(Server); };
        Shown += async (s, e) => await Initialize();
    }

    async Task Initialize()
    {
        try
        {
            string profile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MathMasterClient", testOutput == null ? "WebView2" : "AcceptanceProfile");
            var environment = await CoreWebView2Environment.CreateAsync(null, profile);
            await browser.EnsureCoreWebView2Async(environment);
            browser.ZoomFactor = zoom;
            browser.ZoomFactorChanged += (s, e) => SetZoom(browser.ZoomFactor);
            string css;
            using (var reader = new StreamReader(typeof(RemoteClient).Assembly.GetManifestResourceStream("client.css"))) css = reader.ReadToEnd();
            await browser.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(@"(() => {
                if (location.origin !== '" + Server + @"') return;
                if (innerWidth <= 960) localStorage.setItem('mathmaster-sidebar-closed', 'true');
                const install = () => {
                    if (!document.head || document.getElementById('mathmaster-client-layout')) return;
                    const style = document.createElement('style'); style.id = 'mathmaster-client-layout';
                    style.textContent = " + json.Serialize(css) + @"; document.head.appendChild(style);
                };
                new MutationObserver(install).observe(document, {childList:true, subtree:true}); install();
            })()");
            browser.CoreWebView2.AddWebResourceRequestedFilter(Server + "/api/window", CoreWebView2WebResourceContext.All);
            browser.CoreWebView2.WebResourceRequested += WindowRequest;
            if (testOutput != null) {
                browser.CoreWebView2.AddWebResourceRequestedFilter(Server + "/*", CoreWebView2WebResourceContext.All);
                browser.CoreWebView2.WebResourceRequested += (s, e) => {
                    if (new Uri(e.Request.Uri).AbsolutePath == "/api/window" || e.Request.Method == "GET" || e.Request.Method == "HEAD" || e.Request.Method == "OPTIONS") return;
                    if (e.Request.Method == "POST" && new Uri(e.Request.Uri).AbsolutePath.StartsWith("/api/practice/") && new Uri(e.Request.Uri).AbsolutePath.EndsWith("/visit")) {
                        // Exercise real navigation without altering remote practice history.
                        e.Response = environment.CreateWebResourceResponse(new MemoryStream(Encoding.UTF8.GetBytes("{}")), 200, "OK", "Content-Type: application/json\r\n"); return;
                    }
                    e.Response = environment.CreateWebResourceResponse(new MemoryStream(Encoding.UTF8.GetBytes("{\"detail\":\"Read-only client acceptance\"}")), 409, "Read-only acceptance", "Content-Type: application/json\r\n");
                };
            }
            browser.CoreWebView2.NavigationStarting += (s, e) => {
                Uri uri;
                if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out uri) || uri.GetLeftPart(UriPartial.Authority) != Server)
                { e.Cancel = true; status.Text = "请在浏览器中打开外部链接"; }
                else status.Text = "正在连接…";
            };
            browser.CoreWebView2.NewWindowRequested += async (s, e) => {
                e.Handled = true;
                Uri uri;
                if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out uri) || uri.GetLeftPart(UriPartial.Authority) != Server) return;
                var deferral = e.GetDeferral();
                try { e.NewWindow = await OpenViewer(environment); }
                catch (Exception ex) { status.Text = "无法打开文档：" + ex.Message; }
                finally { deferral.Complete(); }
            };
            browser.CoreWebView2.NavigationCompleted += async (s, e) => {
                status.Text = e.IsSuccess ? "已连接" : "连接失败，点击重新连接";
                status.ToolTipText = e.IsSuccess ? Server : e.WebErrorStatus.ToString();
                if (testOutput != null && !testStarted) { testStarted = true; await SelfTest(e.IsSuccess); }
            };
            browser.CoreWebView2.Navigate(Server);
        }
        catch (Exception ex)
        {
            if (testOutput != null) { File.WriteAllText(testOutput, ex.ToString()); Close(); return; }
            status.Text = "客户端初始化失败";
            MessageBox.Show("无法启动网页组件。请安装 Microsoft Edge WebView2 Runtime 后重新打开。\n\n" + ex.Message, "MathMaster");
        }
    }

    void WindowRequest(object sender, CoreWebView2WebResourceRequestedEventArgs e)
    {
        if (e.Request.Method != "POST") return;
        string response;
        int code = 200;
        try
        {
            string body;
            using (var reader = new StreamReader(e.Request.Content)) body = reader.ReadToEnd();
            var data = json.Deserialize<System.Collections.Generic.Dictionary<string, string>>(body);
            ChangeWindow(data["mode"]);
            response = json.Serialize(new { mode = data["mode"], local = true });
        }
        catch (Exception ex) { code = 422; response = json.Serialize(new { detail = ex.Message }); }
        e.Response = browser.CoreWebView2.Environment.CreateWebResourceResponse(
            new MemoryStream(Encoding.UTF8.GetBytes(response)), code, code == 200 ? "OK" : "Invalid operation", "Content-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\n");
    }

    void ChangeWindow(string mode)
    {
        if (mode == "minimize") { WindowState = FormWindowState.Minimized; return; }
        if (mode == "compact")
        {
            if (!isCompact) { savedBounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds; savedState = WindowState; }
            WindowState = FormWindowState.Normal;
            var area = Screen.FromControl(this).WorkingArea;
            Size = new Size(Math.Min(LogicalToDeviceUnits(820), area.Width), Math.Min(LogicalToDeviceUnits(680), area.Height));
            Location = new Point(Math.Max(area.Left, Math.Min(Left, area.Right - Width)), Math.Max(area.Top, Math.Min(Top, area.Bottom - Height)));
            isCompact = true;
        }
        else if (mode == "restore")
        {
            if (isCompact) { WindowState = FormWindowState.Normal; Bounds = savedBounds; WindowState = savedState; }
            isCompact = false;
        }
        else throw new ArgumentException("未知窗口操作");
        compact.Text = isCompact ? "还原" : "小窗";
        compact.Checked = isCompact;
    }

    void SetZoom(double value)
    {
        zoom = Math.Round(Math.Max(.8, Math.Min(2, value)), 2);
        if (Math.Abs(browser.ZoomFactor - zoom) > .001) browser.ZoomFactor = zoom;
        zoomLabel.Text = Math.Round(zoom * 100) + "%";
        try { Directory.CreateDirectory(Path.GetDirectoryName(settingsPath)); File.WriteAllText(settingsPath, zoom.ToString(CultureInfo.InvariantCulture)); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    async Task<CoreWebView2> OpenViewer(CoreWebView2Environment environment)
    {
        var viewer = new Form { Text = "MathMaster — 原图 / 文档", AutoScaleDimensions = new SizeF(96, 96), AutoScaleMode = AutoScaleMode.Dpi, Size = new Size(1000, 760), StartPosition = FormStartPosition.CenterParent };
        var content = new WebView2 { Dock = DockStyle.Fill };
        var tools = new ToolStrip { GripStyle = ToolStripGripStyle.Hidden };
        tools.Items.Add("缩小", null, (s, e) => content.ZoomFactor = Math.Max(.5, content.ZoomFactor - .2));
        tools.Items.Add("100%", null, (s, e) => content.ZoomFactor = 1);
        tools.Items.Add("放大", null, (s, e) => content.ZoomFactor = Math.Min(4, content.ZoomFactor + .2));
        viewer.Controls.Add(content); viewer.Controls.Add(tools);
        viewer.Show(this);
        var area = Screen.FromControl(this).WorkingArea;
        viewer.Size = new Size(Math.Min(viewer.Width, area.Width), Math.Min(viewer.Height, area.Height));
        viewer.Location = new Point(Math.Max(area.Left, Math.Min(viewer.Left, area.Right - viewer.Width)), Math.Max(area.Top, Math.Min(viewer.Top, area.Bottom - viewer.Height)));
        try {
            await content.EnsureCoreWebView2Async(environment);
            content.CoreWebView2.WindowCloseRequested += (s, e) => viewer.Close();
            return content.CoreWebView2;
        }
        catch { viewer.Close(); throw; }
    }

    async Task SelfTest(bool loaded)
    {
        try
        {
            if (!loaded) throw new Exception("Remote navigation failed");
            if (!AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), new IntPtr(-4)))
                throw new Exception("Per-monitor V2 DPI awareness not active");
            SetZoom(1);
            string health = await EvaluatePromise("fetch('/api/health').then(r=>r.json()).then(v=>v.status)");
            if (health != "\"ok\"") throw new Exception("Remote API unavailable: " + health);
            // Wait for React's window button before exercising the actual UI action.
            string ready = "false";
            for (int i = 0; i < 100 && ready != "true"; i++) {
                ready = await browser.ExecuteScriptAsync("!!document.querySelector('[aria-label=\"收缩窗口\"]')");
                await Task.Delay(100);
            }
            if (ready != "true") throw new Exception("Page controls did not mount");
            Rectangle original = Bounds;
            await browser.ExecuteScriptAsync("document.querySelector('[aria-label=\"收缩窗口\"]').click()");
            for (int i = 0; i < 100 && !isCompact; i++) await Task.Delay(100);
            if (!isCompact || Width != Math.Min(LogicalToDeviceUnits(820), Screen.FromControl(this).WorkingArea.Width)) throw new Exception("Page compact action failed");
            await Task.Delay(700);
            using (var capture = File.Create(Path.ChangeExtension(testOutput, ".png")))
                await browser.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, capture);
            await browser.ExecuteScriptAsync("document.querySelector('[aria-label=\"还原窗口\"]').click()");
            for (int i = 0; i < 100 && isCompact; i++) await Task.Delay(100);
            if (isCompact || Bounds != original) throw new Exception("Page restore action failed");
            pin.PerformClick();
            if (!TopMost) throw new Exception("Pin failed");
            pin.PerformClick();
            string invalid = await EvaluatePromise("fetch('/api/window',{method:'POST',body:JSON.stringify({mode:'bad'})}).then(r=>r.status)");
            if (invalid != "422") throw new Exception("Invalid action accepted");
            var layouts = new System.Collections.Generic.List<object>();
            for (int pageIndex = 0; pageIndex < 2; pageIndex++) {
            if (pageIndex == 1) {
                SetZoom(1);
                Size = new Size(LogicalToDeviceUnits(820), LogicalToDeviceUnits(780));
                string opened = await browser.ExecuteScriptAsync(@"(() => { const b = [...document.querySelectorAll('.resume-actions button')].find(b => b.textContent.includes('继续上一道题')); if (!b) return false; b.click(); return true; })()");
                if (opened != "true") throw new Exception("No recent question available for practice acceptance");
                string practiceReady = "false";
                for (int i = 0; i < 100 && practiceReady != "true"; i++) {
                    practiceReady = await browser.ExecuteScriptAsync("!!document.querySelector('.practice-panes')"); await Task.Delay(100);
                }
                if (practiceReady != "true") throw new Exception("Practice did not open");
            }
            foreach (int width in new[] { 1200, 820, 600, 520 }) {
                Size = new Size(LogicalToDeviceUnits(width), LogicalToDeviceUnits(780));
                foreach (double factor in new[] { 1.0, 1.25, 1.5 }) {
                    SetZoom(factor);
                    await SettleViewport();
                    string layout = await browser.ExecuteScriptAsync(@"(() => {
                        const viewport = innerWidth;
                        const controls = [...document.querySelectorAll('.topbar button, .resume-actions button, .practice-tools button, .sketch .toolbar button')].filter(b=>b.getClientRects().length);
                        return {viewport, overflow:document.documentElement.scrollWidth > viewport + 2,
                            clipped:controls.filter(b=>{const r=b.getBoundingClientRect();return r.left < -1 || r.right > viewport+1}).map(b=>b.textContent),
                            style:!!document.getElementById('mathmaster-client-layout')};
                    })()");
                    var check = json.Deserialize<System.Collections.Generic.Dictionary<string, object>>(layout);
                    if ((bool)check["overflow"] || !(bool)check["style"] || ((System.Collections.ICollection)check["clipped"]).Count > 0)
                        throw new Exception("Layout failed at " + width + " / " + factor + ": " + layout);
                    layouts.Add(new { page = pageIndex == 0 ? "home" : "practice", width, zoom = factor, result = check });
                    if (pageIndex == 1 && width == 820 && factor == 1) {
                        using (var capture = File.Create(Path.ChangeExtension(testOutput, ".practice.png")))
                            await browser.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, capture);
                    }
                }
            }
            }
            SetZoom(1.25);
            if (File.ReadAllText(settingsPath) != "1.25") throw new Exception("Zoom setting not saved");
            SetZoom(1);
            await browser.ExecuteScriptAsync("window.open('/api/health', '_blank')");
            for (int i = 0; i < 100 && OwnedForms.Length == 0; i++) await Task.Delay(100);
            if (OwnedForms.Length != 1) throw new Exception("Document viewer did not open");
            var viewerBrowser = (WebView2)OwnedForms[0].Controls[0];
            for (int i = 0; i < 100 && (viewerBrowser.CoreWebView2 == null || !viewerBrowser.CoreWebView2.Source.Contains("/api/health")); i++) await Task.Delay(100);
            if (viewerBrowser.CoreWebView2 == null || !viewerBrowser.CoreWebView2.Source.Contains("/api/health")) throw new Exception("Document viewer navigation failed");
            OwnedForms[0].Close();
            if (await browser.ExecuteScriptAsync("!!document.querySelector('.practice-panes')") != "true") throw new Exception("Document viewer replaced practice page");
            await browser.ExecuteScriptAsync("document.querySelector('[aria-label=\"最小化窗口\"]').click()");
            for (int i = 0; i < 100 && WindowState != FormWindowState.Minimized; i++) await Task.Delay(100);
            if (WindowState != FormWindowState.Minimized) throw new Exception("Page minimize action failed");
            File.WriteAllText(testOutput, json.Serialize(new { success = true, server = Server, health = "ok", dpi = DeviceDpi, perMonitorV2 = true, zoomPersistence = true, documentViewer = true, layouts, compact = true, restore = true, pin = true, minimize = true, invalidRejected = true }));
        }
        catch (Exception ex) { File.WriteAllText(testOutput, ex.ToString()); }
        finally { Close(); }
    }

    async Task SettleViewport()
    {
        double expected = browser.ClientSize.Width / (DeviceDpi / 96.0) / browser.ZoomFactor;
        for (int i = 0; i < 100; i++) {
            await Task.Delay(100);
            string actual = await browser.ExecuteScriptAsync("innerWidth");
            double width;
            if (double.TryParse(actual, NumberStyles.Float, CultureInfo.InvariantCulture, out width) && Math.Abs(width - expected) < 2) {
                await Task.Delay(150); return;
            }
        }
        throw new Exception("Viewport did not settle at " + expected);
    }

    async Task<string> EvaluatePromise(string expression)
    {
        var completion = new TaskCompletionSource<string>();
        string key = Guid.NewGuid().ToString();
        EventHandler<CoreWebView2WebMessageReceivedEventArgs> handler = (s, e) => {
            var message = json.Deserialize<System.Collections.Generic.Dictionary<string, object>>(e.WebMessageAsJson);
            if (message.ContainsKey("key") && (string)message["key"] == key)
                completion.TrySetResult(json.Serialize(message["value"]));
        };
        browser.CoreWebView2.WebMessageReceived += handler;
        try {
            await browser.ExecuteScriptAsync("Promise.resolve(" + expression + ").then(value=>chrome.webview.postMessage({key:" + json.Serialize(key) + ",value}))");
            if (await Task.WhenAny(completion.Task, Task.Delay(20000)) != completion.Task) throw new TimeoutException("Script timed out");
            return await completion.Task;
        }
        finally { browser.CoreWebView2.WebMessageReceived -= handler; }
    }
}
