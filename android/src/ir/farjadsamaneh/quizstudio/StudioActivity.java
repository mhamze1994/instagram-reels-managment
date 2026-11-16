package ir.farjadsamaneh.quizstudio;
import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
public final class StudioActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView text = new TextView(this);
        text.setText("اتاق محتوا — آزمون ابزار ساخت");
        setContentView(text);
    }
}
