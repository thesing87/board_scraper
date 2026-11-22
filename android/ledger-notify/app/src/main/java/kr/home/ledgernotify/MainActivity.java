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
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 첫 화면: 가계부 페이지(웹)를 앱 안에서 띄움. 위쪽 줄(새로고침·설정)과 할 일을 알려 주는 한 줄 안내.
 * 가계부 페이지는 window.LedgerApp(Bridge)로 이 앱을 알아보고 '이 휴대폰 앱에 연결'을 누르면 연결 주소를 넘겨줌.
 * 가계부와 다른 주소의 링크는 브라우저로 엶 (이 화면에는 가계부만)
 */
public class MainActivity extends Activity {
    private static final int PICK_FILE = 1;

    private Store store;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;
    private TextView banner;
    private ProgressBar progress;
    private String loadedSite = "";
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
        if (b != null) web.restoreState(b);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
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
            web.loadUrl(site);
        }
        if (Updater.autoDue(updateNeedsPermission)) checkUpdate(true);
        showBanner();
    }

    @Override
    protected void onPause() {
        super.onPause();
        web.onPause();
        CookieManager.getInstance().flush();   // 가계부 로그인 쿠키를 바로 저장
    }

    /**
     * 뒤로가기: 가계부 페이지에 열린 것(색 고르기·메모 목록·고치기·펼친 칸)이 있으면 그것부터 닫고,
     * 없으면 '한 번 더 누르면 종료' 안내 → 2초 안에 한 번 더 누르면 앱을 뒤로 보냄 (다시 열면 보던 화면 그대로)
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
        title.setText("YeYe가계부");
        title.setTextColor(0xFFFFFFFF);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        bar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        bar.addView(barButton("새로고침", v -> { loadFailed = false; if (loadedSite.isEmpty()) onResume(); else web.reload(); }));
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

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);           // 가계부가 localStorage를 씀
        s.setUserAgentString(s.getUserAgentString() + " LedgerNotifyApp/" + Updater.ownVersionName(this));
        CookieManager.getInstance().setAcceptCookie(true);
        web.addJavascriptInterface(new Bridge(), "LedgerApp");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        web.setDownloadListener((url, ua, disposition, mime, length) -> {
            if (url.contains("/api/ledger/app.apk")) {
                // 앱 안에서는 받지 않고 바로 새 버전 확인·설치
                toast("새 버전을 확인할게요");
                checkUpdate(false);
            } else {
                openOutside(Uri.parse(url));
            }
        });
        root.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        return root;
    }

    /** 할 일 한 줄: 알림 읽기 권한 → 페이지를 못 엶 → 새 버전 설치 허용 → 앱 연결 순서로 하나만 */
    private void showBanner() {
        String text = null;
        View.OnClickListener go = null;
        if (store.site().isEmpty()) {
            text = "가계부 주소를 넣어 주세요 — 눌러서 설정";
            go = v -> startActivity(new Intent(this, SettingsActivity.class));
        } else if (loadFailed) {
            text = "가계부를 열지 못했어요 — 인터넷·가계부 주소를 확인하고 눌러서 다시";
            go = v -> { loadFailed = false; showBanner(); web.reload(); };
        } else if (!SettingsActivity.hasAccess(this)) {
            text = "알림 읽기 권한이 꺼져 있어 결제 알림을 못 받아요 — 눌러서 켜기";
            go = v -> startActivity(new Intent(this, SettingsActivity.class));
        } else if (updateNeedsPermission && !getPackageManager().canRequestPackageInstalls()) {
            text = "새 버전이 있어요 — 눌러서 '이 앱의 설치 허용' 켜기";
            go = v -> startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName())));
        } else if (updateText.contains("설치 중") || updateText.contains("받는 중")) {
            text = updateText;
        } else if (store.url().isEmpty()) {
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

    /** 가계부 페이지와 가계부 API(받기 등)만 */
    private static boolean inLedger(Uri u) {
        String path = u.getPath() == null ? "" : u.getPath();
        return path.equals("/ledger") || path.startsWith("/ledger/") || path.startsWith("/api/ledger/");
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
            // 앱에서는 가계부만: 같은 사이트라도 /ledger/ 밖(대시보드·동영상 등)으로는 가지 않음
            if (!inLedger(u)) {
                toast("앱에서는 가계부만 볼 수 있어요");
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
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (req.isForMainFrame()) {
                loadFailed = true;
                showBanner();
            }
        }
    }

    private class Chrome extends WebChromeClient {
        @Override
        public void onProgressChanged(WebView view, int p) {
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

    /** 가계부 페이지가 부르는 것 (window.LedgerApp). 가계부 주소의 페이지에서만 받음 */
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

        /** 가계부에 로그인됨: 로그인 전이라 새 버전을 확인하지 못했으면 바로 다시 */
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
