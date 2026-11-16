package ir.farjadsamaneh.quizstudio;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

public final class ShareProvider extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    private File resolve(Uri uri) throws FileNotFoundException {
        String name = uri.getLastPathSegment();
        if (uri.getPathSegments().size() != 1 || name == null || !name.matches("[a-f0-9]{32}\\.(mp4|jpg)")) throw new FileNotFoundException();
        File file = new File(new File(getContext().getCacheDir(), "shared"), name);
        if (!file.isFile()) throw new FileNotFoundException();
        return file;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read only");
        return ParcelFileDescriptor.open(resolve(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public String getType(Uri uri) { return uri.getPath().endsWith(".mp4") ? "video/mp4" : "image/jpeg"; }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        try {
            File f = resolve(uri);
            String[] names = projection == null ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection;
            MatrixCursor cursor = new MatrixCursor(names, 1);
            Object[] values = new Object[names.length];
            for (int i = 0; i < names.length; i++) values[i] = OpenableColumns.DISPLAY_NAME.equals(names[i]) ? "quiz-" + f.getName() : OpenableColumns.SIZE.equals(names[i]) ? f.length() : null;
            cursor.addRow(values); return cursor;
        } catch (FileNotFoundException e) { return null; }
    }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String where, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String where, String[] args) { throw new UnsupportedOperationException(); }
}
