package kr.home.ledgernotify;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 첫 화면 (YeYe홈): 아래쪽 탭으로 가계부(/ledger/)와 근무표(/duty/) 웹 페이지를 오감. 탭마다 웹 화면을 따로 둬서
 * 오가도 보던 곳이 그대로. 위쪽 줄(새로고침·설정)과 할 일을 알려 주는 한 줄 안내.
 * 페이지는 window.LedgerApp(Bridge)로 이 앱을 알아보고, 가계부의 '이 휴대폰 앱에 연결'을 누르면 연결 주소를 넘겨줌.
 * 다른 주소의 링크는 브라우저로 엶 (앱 안에는 가계부·근무표만)
 */
public class MainActivity extends Activity {
    private static final int PICK_FILE = 1;
    static final int TAB_LEDGER = 0, TAB_DUTY = 1;

    private Store store;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;                     // 지금 보이는 탭의 웹 화면
    private WebView webLedger, webDuty;
    private int tab = TAB_LEDGER;
    private final TextView[] tabLabels = new TextView[2];
    private final ImageView[] tabIcons = new ImageView[2];
    private TextView banner;
    private ProgressBar progress;
    private String loadedSite = "";
    private String loadedDuty = "";          // 근무표 화면에 띄운 주소 (근무표 탭을 처음 볼 때 엶)
    private volatile String pageOrigin = "";
    private ValueCallback<Uri[]> fileCallback;
    private boolean askedSite;
    private boolean loadFailed;
    private String updateText = "";
    private boolean updateNeedsPermission;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        store = new Store(this);
        setContentView(build());
        openInbox = getIntent().getBooleanExtra(Notifier.EXTRA_INBOX, false);
        // 마지막으로 본 탭부터 (금액 인식 알림을 눌러 열면 가계부)
        selectTab(openInbox ? TAB_LEDGER : store.tab());
        // 금액 인식 알림을 띄우려면 (안드로이드 13 이상) 알림 권한: 알림 읽기 권한을 켠 뒤 처음 한 번만 물음
        if (android.os.Build.VERSION.SDK_INT >= 33 && store.alertOn() && !Notifier.allowed(this)
                && !store.askedNotifyPermission() && SettingsActivity.hasAccess(this)) {
            store.setAskedNotifyPermission();
            requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, 2);
        }
    }

    /** 금액 인식 알림을 누름: 가계부를 새로 읽고 확인 대기함으로 */
    private boolean openInbox;

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (intent.getBooleanExtra(Notifier.EXTRA_INBOX, false) && !loadedSite.isEmpty()) {
            openInbox = true;
            selectTab(TAB_LEDGER);
            webLedger.reload();
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        showBanner();
    }

    /** 확인 대기함이 그려질 때까지 잠깐 기다렸다가 그리로 (대기함이 비었으면 그냥 첫 화면) */
    private void scrollToInbox() {
        if (!openInbox) return;
        openInbox = false;
        webLedger.evaluateJavascript("(function t(n){var e=document.getElementById('inbox-sec');"
                + "if(e&&!e.hidden){e.scrollIntoView({block:'start'});}else if(n>0){setTimeout(function(){t(n-1);},300);}})(20)", null);
    }

    @Override
    protected void onResume() {
        super.onResume();
        webLedger.onResume();
        webDuty.onResume();
        String site = store.site();
        if (site.isEmpty()) {
            // 처음: 가계부 주소부터 (설정 화면에서 넣으면 돌아와서 엶)
            if (!askedSite) {
                askedSite = true;
                startActivity(new Intent(this, SettingsActivity.class));
            }
        } else if (!site.equals(loadedSite)) {
            loadedSite = site;
            pageOrigin = Store.origin(site);
            webLedger.loadUrl(site);
            loadedDuty = "";
            if (tab == TAB_DUTY) loadDuty();
        }
        if (Updater.autoDue(updateNeedsPermission)) checkUpdate(true);
        showBanner();
    }

    @Override
    protected void onPause() {
        super.onPause();
        webLedger.onPause();
        webDuty.onPause();
        CookieManager.getInstance().flush();   // 가계부 로그인 쿠키를 바로 저장
    }

    /**
     * 뒤로가기: 페이지에 열린 것(설정·색 고르기·메모 목록·고치기·고른 근무)이 있으면 그것부터 닫고,
     * 근무표 탭이면 가계부 탭으로, 가계부 탭이면 '한 번 더 누르면 종료' 안내
     * → 2초 안에 한 번 더 누르면 앱을 뒤로 보냄 (다시 열면 보던 화면 그대로)
     */
    private long backAt;

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("(window.ledgerBack && window.ledgerBack()) ? 'closed' : ''", r -> {
            if (r != null && r.contains("closed")) return;
            if (web.canGoBack()) {
                web.goBack();
                return;
            }
            if (tab == TAB_DUTY) {
                selectTab(TAB_LEDGER);
                return;
            }
            long now = System.currentTimeMillis();
            if (now - backAt < 2000) {
                backAt = 0;
                moveTaskToBack(true);
            } else {
                backAt = now;
                Toast.makeText(this, "뒤로 버튼을 한 번 더 누르면 종료돼요", Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void checkUpdate(boolean auto) {
        Updater.check(this, auto, (text, needPermission) -> ui.post(() -> {
            updateText = text;
            updateNeedsPermission = needPermission;
            showBanner();
        }));
    }

    // ==========================================
    // 화면
    // ==========================================
    private View build() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(getColor(R.color.bg));

        // ---- 위쪽 줄: 제목 · 새로고침 · 설정
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(getColor(R.color.green));
        bar.setPadding(dp(16), 0, dp(4), 0);
        TextView title = new TextView(this);
        title.setText(R.string.app_name);   // 시험 앱은 'YeYe홈 테스트'
        title.setTextColor(0xFFFFFFFF);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        bar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        bar.addView(barButton("새로고침", v -> {
            loadFailed = false;
            if (loadedSite.isEmpty()) onResume();
            else if (tab == TAB_DUTY && loadedDuty.isEmpty()) loadDuty();
            else web.reload();
        }));
        bar.addView(barButton("설정", v -> startActivity(new Intent(this, SettingsActivity.class))));
        root.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));

        // ---- 할 일 한 줄 (누르면 그 화면으로)
        banner = new TextView(this);
        banner.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        banner.setTextColor(0xFF633806);
        banner.setBackgroundColor(0xFFFAEEDA);
        banner.setPadding(dp(16), dp(10), dp(16), dp(10));
        banner.setVisibility(View.GONE);
        root.addView(banner, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        progress.setVisibility(View.GONE);
        root.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)));

        // ---- 탭마다 웹 화면 하나 (로그인 쿠키는 함께 씀)
        CookieManager.getInstance().setAcceptCookie(true);
        FrameLayout pages = new FrameLayout(this);
        webLedger = newWeb();
        webDuty = newWeb();
        pages.addView(webLedger, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        pages.addView(webDuty, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        web = webLedger;
        root.addView(pages, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        // ---- 아래쪽 탭: 가계부 | 근무표
        View line = new View(this);
        line.setBackgroundColor(0xFFE5E7EB);
        root.addView(line, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1));
        LinearLayout tabs = new LinearLayout(this);
        tabs.setBackgroundColor(0xFFFFFFFF);
        tabs.addView(tabButton(TAB_LEDGER, "가계부", R.drawable.ic_tab_ledger), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1));
        tabs.addView(tabButton(TAB_DUTY, "근무표", R.drawable.ic_tab_duty), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1));
        root.addView(tabs, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(58)));
        return root;
    }

    private WebView newWeb() {
        WebView w = new WebView(this);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);           // 가계부·근무표가 localStorage를 씀
        s.setUserAgentString(s.getUserAgentString() + " LedgerNotifyApp/" + Updater.ownVersionName(this));
        w.addJavascriptInterface(new Bridge(), "LedgerApp");
        w.setWebViewClient(new Client());
        w.setWebChromeClient(new Chrome());
        w.setDownloadListener((url, ua, disposition, mime, length) -> {
            if (url.contains("/api/ledger/app.apk")) {
                // 앱 안에서는 받지 않고 바로 새 버전 확인·설치
                toast("새 버전을 확인할게요");
                checkUpdate(false);
            } else {
                openOutside(Uri.parse(url));
            }
        });
        return w;
    }

    private View tabButton(int which, String label, int icon) {
        LinearLayout b = new LinearLayout(this);
        b.setOrientation(LinearLayout.VERTICAL);
        b.setGravity(Gravity.CENTER);
        TypedValue tv = new TypedValue();
        getTheme().resolveAttribute(android.R.attr.selectableItemBackground, tv, true);
        b.setBackgroundResource(tv.resourceId);
        ImageView i = new ImageView(this);
        i.setImageResource(icon);
        b.addView(i, new LinearLayout.LayoutParams(dp(24), dp(24)));
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        t.setGravity(Gravity.CENTER);
        t.setPadding(0, dp(3), 0, 0);
        b.addView(t);
        b.setContentDescription(label);
        b.setOnClickListener(v -> {
            // 보고 있는 탭을 다시 누르면 그 페이지 맨 위로
            if (tab == which) web.evaluateJavascript("window.scrollTo({top: 0, behavior: 'smooth'})", null);
            else selectTab(which);
        });
        tabIcons[which] = i;
        tabLabels[which] = t;
        return b;
    }

    /** 탭 바꾸기: 그 탭의 웹 화면을 보이고 (근무표는 처음 볼 때 엶), 다음에 앱을 열면 이 탭부터 */
    private void selectTab(int which) {
        tab = which == TAB_DUTY ? TAB_DUTY : TAB_LEDGER;
        store.setTab(tab);
        web = tab == TAB_DUTY ? webDuty : webLedger;
        webLedger.setVisibility(tab == TAB_LEDGER ? View.VISIBLE : View.GONE);
        webDuty.setVisibility(tab == TAB_DUTY ? View.VISIBLE : View.GONE);
        for (int k = 0; k < 2; k++) {
            int color = k == tab ? getColor(R.color.green) : 0xFF8B919C;
            tabIcons[k].setColorFilter(color);
            tabLabels[k].setTextColor(color);
            tabLabels[k].setTypeface(k == tab ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        }
        if (tab == TAB_DUTY && loadedDuty.isEmpty() && !loadedSite.isEmpty()) loadDuty();
        loadFailed = false;
        progress.setVisibility(View.GONE);
        showBanner();
    }

    private void loadDuty() {
        loadedDuty = Store.origin(loadedSite) + "/duty/";
        webDuty.loadUrl(loadedDuty);
    }

    /** 할 일 한 줄: 알림 읽기 권한 → 페이지를 못 엶 → 알림 권한(금액 인식 알림) → 새 버전 설치 허용 → 앱 연결 순서로 하나만 */
    private void showBanner() {
        if (banner == null) return;
        String text = null;
        View.OnClickListener go = null;
        if (store.site().isEmpty()) {
            text = "가계부 주소를 넣어 주세요 — 눌러서 설정";
            go = v -> startActivity(new Intent(this, SettingsActivity.class));
        } else if (loadFailed) {
            text = (tab == TAB_DUTY ? "근무표" : "가계부") + "를 열지 못했어요 — 인터넷·가계부 주소를 확인하고 눌러서 다시";
            go = v -> { loadFailed = false; showBanner(); web.reload(); };
        } else if (!SettingsActivity.hasAccess(this)) {
            text = "알림 읽기 권한이 꺼져 있어 결제 알림을 못 받아요 — 눌러서 켜기";
            go = v -> startActivity(new Intent(this, SettingsActivity.class));
        } else if (store.alertOn() && store.askedNotifyPermission() && !Notifier.allowed(this)) {
            text = "알림 권한이 꺼져 있어 금액 인식 알림을 못 띄워요 — 눌러서 켜기 (설정에서 이 알림을 끌 수도 있어요)";
            go = v -> startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
        } else if (updateNeedsPermission && !getPackageManager().canRequestPackageInstalls()) {
            text = "새 버전이 있어요 — 눌러서 '이 앱의 설치 허용' 켜기";
            go = v -> startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName())));
        } else if (updateText.contains("설치 중") || updateText.contains("받는 중")) {
            text = updateText;
        } else if (store.url().isEmpty() && tab == TAB_LEDGER) {
            text = "결제 알림이 아직 가계부로 안 가요 — 로그인 뒤 '결제 알림 자동 기록' → '이 휴대폰 앱에 연결'을 누르세요";
        }
        banner.setText(text == null ? "" : text);
        banner.setOnClickListener(go);
        banner.setVisibility(text == null ? View.GONE : View.VISIBLE);
    }

    // ==========================================
    // 웹 화면
    // ==========================================
    private boolean sameSite(Uri u) {
        return Store.origin(u.toString()).equals(Store.origin(loadedSite));
    }

    private static String pathOf(Uri u) {
        return u.getPath() == null ? "" : u.getPath();
    }

    private static boolean isLedgerPage(Uri u) {
        String path = pathOf(u);
        return path.equals("/ledger") || path.startsWith("/ledger/");
    }

    private static boolean isDutyPage(Uri u) {
        String path = pathOf(u);
        return path.equals("/duty") || path.startsWith("/duty/");
    }

    private void openOutside(Uri u) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u));
        } catch (ActivityNotFoundException e) {
            toast("열 수 있는 앱이 없어요");
        }
    }

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (!sameSite(u)) {
                openOutside(u);
                return true;
            }
            // 다른 탭의 페이지로 가는 링크(근무표 로그인 화면의 '가계부에서 가입' 등)는 그 탭에서 엶
            if (isLedgerPage(u) && view == webDuty) {
                selectTab(TAB_LEDGER);
                webLedger.loadUrl(u.toString());
                return true;
            }
            if (isDutyPage(u) && view == webLedger) {
                loadedDuty = u.toString();
                webDuty.loadUrl(loadedDuty);
                selectTab(TAB_DUTY);
                return true;
            }
            // 앱에서는 가계부·근무표만: 같은 사이트라도 그 밖(대시보드·동영상 등)으로는 가지 않음
            if (!isLedgerPage(u) && !isDutyPage(u) && !pathOf(u).startsWith("/api/ledger/")) {
                toast("앱에서는 가계부·근무표만 볼 수 있어요");
                return true;
            }
            return false;
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            pageOrigin = Store.origin(url);
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            showBanner();
            if (view == webLedger) scrollToInbox();
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (req.isForMainFrame() && view == web) {
                loadFailed = true;
                showBanner();
            }
        }
    }

    private class Chrome extends WebChromeClient {
        @Override
        public void onProgressChanged(WebView view, int p) {
            if (view != web) return;
            progress.setProgress(p);
            progress.setVisibility(p < 100 ? View.VISIBLE : View.GONE);
        }

        /** 관리자 칸의 앱 파일 올리기 등 <input type=file> */
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = cb;
            try {
                startActivityForResult(params.createIntent(), PICK_FILE);
                return true;
            } catch (ActivityNotFoundException e) {
                fileCallback = null;
                return false;
            }
        }
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        if (req == PICK_FILE && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(req, result, data);
    }

    /** 가계부·근무표 페이지가 부르는 것 (window.LedgerApp). 가계부 주소의 페이지에서만 받음 */
    private class Bridge {
        private boolean fromLedger() {
            return !loadedSite.isEmpty() && pageOrigin.equals(Store.origin(loadedSite));
        }

        @JavascriptInterface
        public String version() {
            return Updater.ownVersionName(MainActivity.this);
        }

        /** 이 앱이 지금 이 가계부로 결제 알림을 보내고 있는지 */
        @JavascriptInterface
        public boolean connected() {
            String u = store.url();
            return fromLedger() && !u.isEmpty() && Store.origin(u).equals(pageOrigin);
        }

        /** 가계부에서 만든 연결 주소를 받음 (같은 가계부 주소의 /api/ledger/hook/…만) */
        @JavascriptInterface
        public boolean connect(String url) {
            if (!fromLedger() || url == null) return false;
            String prefix = pageOrigin + "/api/ledger/hook/";
            if (!url.toLowerCase(java.util.Locale.ROOT).startsWith(prefix) || url.length() < prefix.length() + 10) return false;
            store.setUrl(url);
            ui.post(() -> {
                showBanner();
                toast("이 앱에 연결했어요 — 이제 결제 알림이 확인 대기함으로 가요");
            });
            return true;
        }

        /** 가계부·근무표에 로그인됨: 로그인 전이라 새 버전을 확인하지 못했으면 바로 다시 */
        @JavascriptInterface
        public void loggedIn() {
            if (!fromLedger()) return;
            ui.post(() -> {
                if (Updater.NEED_LOGIN.equals(updateText)) {
                    updateText = "";
                    checkUpdate(true);
                }
            });
        }

        @JavascriptInterface
        public void openSettings() {
            ui.post(() -> startActivity(new Intent(MainActivity.this, SettingsActivity.class)));
        }
    }

    // ==========================================
    // 도우미
    // ==========================================
    private TextView barButton(String label, View.OnClickListener on) {
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextColor(0xFFFFFFFF);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(12), 0, dp(12), 0);
        t.setOnClickListener(on);
        t.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.MATCH_PARENT));
        TypedValue tv = new TypedValue();
        getTheme().resolveAttribute(android.R.attr.selectableItemBackground, tv, true);
        t.setBackgroundResource(tv.resourceId);
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }
}
