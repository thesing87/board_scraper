package kr.home.ledgernotify;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;

/** 업데이트 설치 결과. 확인이 필요하면 시스템의 '업데이트' 창을 띄우고, 취소·실패는 화면에 보일 글로 남김 */
public class InstallReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent intent) {
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        Store s = new Store(c);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                try {
                    c.startActivity(confirm);
                } catch (RuntimeException e) {
                    s.setUpdateMessage("업데이트 확인 창을 열지 못했어요 — '새 버전 확인'을 다시 눌러 주세요");
                }
            }
            return;
        }
        if (status == PackageInstaller.STATUS_SUCCESS) {
            s.setUpdateMessage("");
            return;
        }
        if (status == PackageInstaller.STATUS_FAILURE_ABORTED) {
            s.setUpdateDeclinedAt(System.currentTimeMillis());
            s.setUpdateMessage("업데이트를 취소했어요 — 하루 동안은 자동으로 묻지 않아요");
            return;
        }
        String why = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
        s.setUpdateMessage(status == PackageInstaller.STATUS_FAILURE_CONFLICT || status == PackageInstaller.STATUS_FAILURE_INCOMPATIBLE
                ? "업데이트하지 못했어요 — 서명이 달라요. 앱을 지우고 새로 설치해 주세요"
                : "업데이트하지 못했어요" + (why == null ? "" : " (" + why + ")"));
    }
}
