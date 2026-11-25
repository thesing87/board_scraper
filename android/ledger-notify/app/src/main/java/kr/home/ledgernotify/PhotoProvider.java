package kr.home.ledgernotify;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * PhotoPick이 JPEG로 바꾼 사진(캐시의 photo_pick 폴더)을 앱 안 화면(WebView)의 파일 고르기에 content:// 주소로 넘김.
 * 밖으로 열지 않음 (exported=false), 읽기만
 */
public class PhotoProvider extends ContentProvider {
    static Uri uriFor(android.content.Context c, File f) {
        return new Uri.Builder().scheme("content").authority(c.getPackageName() + ".photos").appendPath(f.getName()).build();
    }

    private File fileOf(Uri u) throws FileNotFoundException {
        String name = u.getLastPathSegment();
        if (name == null || !name.matches("[0-9_]+\\.jpg")) throw new FileNotFoundException(String.valueOf(u));
        File f = new File(new File(getContext().getCacheDir(), PhotoPick.DIR), name);
        if (!f.isFile()) throw new FileNotFoundException(String.valueOf(u));
        return f;
    }

    @Override public boolean onCreate() { return true; }

    @Override public String getType(Uri u) { return "image/jpeg"; }

    @Override public ParcelFileDescriptor openFile(Uri u, String mode) throws FileNotFoundException {
        return ParcelFileDescriptor.open(fileOf(u), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override public Cursor query(Uri u, String[] projection, String sel, String[] args, String sort) {
        File f;
        try { f = fileOf(u); } catch (FileNotFoundException e) { return null; }
        MatrixCursor c = new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE});
        c.addRow(new Object[]{f.getName(), f.length()});
        return c;
    }

    @Override public Uri insert(Uri u, ContentValues v) { return null; }
    @Override public int delete(Uri u, String s, String[] a) { return 0; }
    @Override public int update(Uri u, ContentValues v, String s, String[] a) { return 0; }
}
