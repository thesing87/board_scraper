package kr.home.ledgernotify;

import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

/** 홈 화면 한 달 근무표 위젯 (달력). 그리기·데이터는 DutyWidgets */
public class DutyMonthWidget extends AppWidgetProvider {
    @Override
    public void onReceive(Context c, Intent intent) {
        if (DutyWidgets.ACTION_REFRESH.equals(intent.getAction())) {
            // 자정 알람: 두 가지 위젯 모두
            PendingResult done = goAsync();
            Context app = c.getApplicationContext();
            new Thread(() -> {
                try {
                    AppWidgetManager m = AppWidgetManager.getInstance(app);
                    DutyWidgets.update(app, m, m.getAppWidgetIds(new android.content.ComponentName(app, DutyMonthWidget.class)), true);
                    DutyWidgets.update(app, m, m.getAppWidgetIds(new android.content.ComponentName(app, DutyTodayWidget.class)), true);
                } finally {
                    done.finish();
                }
            }).start();
            return;
        }
        super.onReceive(c, intent);
    }

    @Override
    public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        PendingResult done = goAsync();
        Context app = c.getApplicationContext();
        new Thread(() -> {
            try {
                DutyWidgets.update(app, m, ids, true);
            } finally {
                done.finish();
            }
        }).start();
    }

    /** 크기를 바꾸면 저장해 둔 것으로 다시 그림 */
    @Override
    public void onAppWidgetOptionsChanged(Context c, AppWidgetManager m, int id, Bundle o) {
        DutyWidgets.update(c, m, new int[]{id}, false);
    }

    @Override
    public void onDeleted(Context c, int[] ids) {
        DutyWidgets.forget(c, ids);
    }
}
