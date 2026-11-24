package kr.home.ledgernotify;

import android.app.Activity;
import android.appwidget.AppWidgetManager;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.SeekBar;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 근무표 위젯을 홈 화면에 놓을 때(또는 길게 눌러 다시 설정할 때): 누구 근무표를 보일지, 배경 투명도(1.25부터)를 고르고 '완료'.
 * 사람이 한 명뿐이면 사람은 묻지 않음. 앱에서 로그인하지 않았으면 안내만 하고 위젯은 놓지 않음
 */
public class DutyWidgetConfig extends Activity {
    private int widgetId = AppWidgetManager.INVALID_APPWIDGET_ID;
    private LinearLayout box;
    private TextView msg;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Bundle extras = getIntent().getExtras();
        if (extras != null) widgetId = extras.getInt(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID);
        setResult(RESULT_CANCELED, new Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId));
        if (widgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            finish();
            return;
        }
        box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(18), dp(20), dp(14));
        TextView title = new TextView(this);
        title.setText("누구 근무표를 보일까요?");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        title.setTextColor(0xFF111827);
        box.addView(title);
        msg = new TextView(this);
        msg.setText("불러오는 중…");
        msg.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        msg.setTextColor(0xFF5F6673);
        msg.setPadding(0, dp(8), 0, dp(8));
        box.addView(msg);
        setContentView(box, new ViewGroup.LayoutParams(dp(300), ViewGroup.LayoutParams.WRAP_CONTENT));
        new Thread(this::load).start();
    }

    private void load() {
        try {
            JSONObject d = DutyWidgets.fetch(this, 0, DutyWidgets.thisMonth());
            JSONArray people = d.optJSONArray("people");
            ui.post(() -> show(people));
        } catch (Exception e) {
            boolean login = "login".equals(e.getMessage());
            ui.post(() -> {
                msg.setText(login ? "YeYe홈 앱에서 가계부에 먼저 로그인해 주세요." : "근무표를 불러오지 못했어요. 인터넷을 확인하고 다시 놓아 주세요.");
                addButton("앱 열기", () -> {
                    startActivity(new Intent(this, MainActivity.class).putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_DUTY)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                    finish();
                });
                addButton("닫기", this::finish);
            });
        }
    }

    private void show(JSONArray people) {
        if (people == null || people.length() == 0) {
            msg.setText("근무표에 사람이 없어요. 앱의 근무표 탭에서 먼저 더해 주세요.");
            addButton("닫기", this::finish);
            return;
        }
        int current = DutyWidgets.person(this, widgetId), first = DutyWidgets.defaultPerson(this);
        // '처음 보일 사람'(근무표 설정 > 이 휴대폰)을 맨 위에
        java.util.List<JSONObject> list = new java.util.ArrayList<>();
        for (int i = 0; i < people.length(); i++) {
            JSONObject p = people.optJSONObject(i);
            if (p.optInt("id") == first) list.add(0, p); else list.add(p);
        }
        RadioGroup group = new RadioGroup(this);
        boolean any = false;
        for (JSONObject p : list) if (p.optInt("id") == current) any = true;
        for (int i = 0; i < list.size(); i++) {
            JSONObject p = list.get(i);
            RadioButton rb = new RadioButton(this);
            rb.setId(View.generateViewId());
            rb.setTag(p.optInt("id"));
            rb.setText(p.optString("name"));
            rb.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
            rb.setTextColor(0xFF111827);
            rb.setPadding(dp(4), dp(6), 0, dp(6));
            group.addView(rb);
            if (any ? p.optInt("id") == current : i == 0) rb.setChecked(true);
        }
        if (list.size() > 1) {
            msg.setText("위젯마다 따로 고를 수 있어요. 나중에 위젯을 길게 눌러 바꿀 수도 있어요.");
            box.addView(group);
        } else {
            msg.setText("나중에 위젯을 길게 눌러 바꿀 수 있어요.");
        }

        // 배경 투명도: 0~100%, 10%씩 (흰 배경만 투명해지고 글자·근무 색은 그대로)
        LinearLayout row = new LinearLayout(this);
        row.setPadding(0, dp(14), 0, 0);
        TextView label = new TextView(this);
        label.setText("배경 투명도");
        label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        label.setTextColor(0xFF111827);
        row.addView(label, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        TextView value = new TextView(this);
        value.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        value.setTextColor(0xFF0F6E56);
        value.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        row.addView(value);
        box.addView(row);
        SeekBar bar = new SeekBar(this);
        bar.setMax(10);
        bar.setProgress(Math.round(DutyWidgets.transparency(this, widgetId) / 10f));
        value.setText(bar.getProgress() * 10 + "%");
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar s, int v, boolean user) { value.setText(v * 10 + "%"); }
            @Override public void onStartTrackingTouch(SeekBar s) {}
            @Override public void onStopTrackingTouch(SeekBar s) {}
        });
        box.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout ends = new LinearLayout(this);
        for (String t : new String[]{"불투명", "투명"}) {
            TextView e = new TextView(this);
            e.setText(t);
            e.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
            e.setTextColor(0xFF8B919C);
            e.setGravity("투명".equals(t) ? Gravity.END : Gravity.START);
            ends.addView(e, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        }
        box.addView(ends);

        int only = list.get(0).optInt("id");
        addButton("완료", () -> {
            View on = group.findViewById(group.getCheckedRadioButtonId());
            choose(on != null ? (int) on.getTag() : only, bar.getProgress() * 10);
        });
    }

    private void choose(int personId, int transparency) {
        DutyWidgets.setTransparency(this, widgetId, transparency);
        if (personId != DutyWidgets.person(this, widgetId)) DutyWidgets.setPerson(this, widgetId, personId);
        AppWidgetManager m = AppWidgetManager.getInstance(this);
        new Thread(() -> DutyWidgets.update(getApplicationContext(), m, new int[]{widgetId}, true)).start();
        setResult(RESULT_OK, new Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId));
        finish();
    }

    private void addButton(String label, Runnable on) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setGravity(Gravity.CENTER);
        b.setOnClickListener(v -> on.run());
        box.addView(b, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
