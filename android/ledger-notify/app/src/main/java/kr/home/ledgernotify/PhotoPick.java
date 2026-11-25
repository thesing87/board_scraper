package kr.home.ledgernotify;

import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.ImageDecoder;
import android.graphics.Matrix;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.Build;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * 가계부 사진 붙이기 (1.28부터): 페이지의 <input type=file accept=image/*>로 사진을 고르면, 고른 사진을 앱이 직접 열어
 * 긴 쪽 MAX_SIDE px JPEG로 바꿔 캐시 폴더에 두고 그 파일을 페이지에 넘김.
 * 앱 안 화면(WebView)은 HEIC(삼성 '고효율 사진')나 아주 큰 사진을 열지 못하지만 안드로이드는 열 수 있음.
 * 바꾸지 못한 사진은 받은 그대로 넘겨 페이지가 '열 수 없어요'와 형식을 알려 줌
 */
final class PhotoPick {
    private static final int MAX_SIDE = 2000;   // 페이지가 다시 1600px로 줄임
    static final String DIR = "photo_pick";

    private PhotoPick() { }

    /** accept에 image가 있는 파일 고르기면 true */
    static boolean isImage(String[] accept) {
        if (accept == null) return false;
        for (String a : accept) if (a != null && a.startsWith("image/")) return true;
        return false;
    }

    static Intent intent(boolean multiple) {
        Intent i = new Intent(Intent.ACTION_GET_CONTENT);
        i.setType("image/*");
        i.addCategory(Intent.CATEGORY_OPENABLE);
        if (multiple) i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        return i;
    }

    /** 고르기 결과의 사진 주소들 (한 장은 getData, 여러 장은 ClipData에 오는 앱이 있음) */
    static List<Uri> uris(Intent data) {
        List<Uri> out = new ArrayList<>();
        if (data == null) return out;
        ClipData clip = data.getClipData();
        if (clip != null) for (int k = 0; k < clip.getItemCount(); k++) {
            Uri u = clip.getItemAt(k).getUri();
            if (u != null && !out.contains(u)) out.add(u);
        }
        if (data.getData() != null && !out.contains(data.getData())) out.add(data.getData());
        return out;
    }

    /** 사진마다 JPEG로 바꾼 파일 주소 (못 바꾸면 원래 주소). 오래 걸릴 수 있어 일하는 스레드에서 부름 */
    static Uri[] toJpegs(Context c, List<Uri> in) {
        File dir = new File(c.getCacheDir(), DIR);
        if (!dir.isDirectory()) dir.mkdirs();
        File[] old = dir.listFiles();
        long now = System.currentTimeMillis();
        if (old != null) for (File f : old) if (now - f.lastModified() > 3600_000L) f.delete();   // 한 시간 지난 것은 지움
        Uri[] out = new Uri[in.size()];
        for (int k = 0; k < in.size(); k++) {
            Uri u = in.get(k);
            out[k] = u;
            try {
                Bitmap b = decode(c, u);
                if (b == null) continue;
                File f = new File(dir, now + "_" + k + ".jpg");
                try (OutputStream os = new FileOutputStream(f)) {
                    if (b.compress(Bitmap.CompressFormat.JPEG, 88, os)) out[k] = PhotoProvider.uriFor(c, f);
                }
                b.recycle();
            } catch (Exception | OutOfMemoryError e) {
                // 받은 그대로 넘김
            }
        }
        return out;
    }

    private static Bitmap decode(Context c, Uri u) throws Exception {
        if (Build.VERSION.SDK_INT >= 28) {
            // ImageDecoder: HEIC도 열고, 사진의 회전(EXIF)도 맞춰 줌
            return ImageDecoder.decodeBitmap(ImageDecoder.createSource(c.getContentResolver(), u), (dec, info, src) -> {
                int w = info.getSize().getWidth(), h = info.getSize().getHeight(), m = Math.max(w, h);
                if (m > MAX_SIDE) dec.setTargetSize(Math.max(1, w * MAX_SIDE / m), Math.max(1, h * MAX_SIDE / m));
                dec.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE);
            });
        }
        // 8.x: 크기를 먼저 읽고 줄여서 열기, 회전은 EXIF로
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        try (InputStream is = c.getContentResolver().openInputStream(u)) { BitmapFactory.decodeStream(is, null, o); }
        int m = Math.max(o.outWidth, o.outHeight), sample = 1;
        while (m / (sample * 2) >= MAX_SIDE) sample *= 2;
        BitmapFactory.Options o2 = new BitmapFactory.Options();
        o2.inSampleSize = sample;
        Bitmap b;
        try (InputStream is = c.getContentResolver().openInputStream(u)) { b = BitmapFactory.decodeStream(is, null, o2); }
        if (b == null) return null;
        int deg = 0;
        try (InputStream is = c.getContentResolver().openInputStream(u)) {
            int ori = new ExifInterface(is).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL);
            deg = ori == ExifInterface.ORIENTATION_ROTATE_90 ? 90 : ori == ExifInterface.ORIENTATION_ROTATE_180 ? 180
                    : ori == ExifInterface.ORIENTATION_ROTATE_270 ? 270 : 0;
        } catch (Exception ignored) { }
        if (deg != 0) {
            Matrix mx = new Matrix();
            mx.postRotate(deg);
            Bitmap r = Bitmap.createBitmap(b, 0, 0, b.getWidth(), b.getHeight(), mx, true);
            if (r != b) b.recycle();
            b = r;
        }
        return b;
    }
}
