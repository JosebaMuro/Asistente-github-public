package local.cerebro;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import java.io.File;

/**
 * Servicio en primer plano: graba aunque se apague la pantalla o cambies de app.
 * Formato AAC mono 16 kHz (lo que necesita el reconocedor; ~15 MB por hora).
 */
public class Grabacion extends Service {
    static volatile Grabacion activa;
    private MediaRecorder rec;
    private File archivo;
    private String tipo;
    private long inicio;
    private PowerManager.WakeLock cerrojo;

    @Override public IBinder onBind(Intent i) { return null; }

    @Override
    public int onStartCommand(Intent intent, int flags, int id) {
        tipo = intent != null && intent.getStringExtra("tipo") != null ? intent.getStringExtra("tipo") : "nota_voz";
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("grabacion", "Grabación", NotificationManager.IMPORTANCE_LOW));
        PendingIntent abrir = PendingIntent.getActivity(this, 0, new Intent(this, Principal.class), PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(this, "grabacion")
                .setContentTitle("reunion".equals(tipo) ? "Grabando reunión" : "Grabando")
                .setContentText("Toca para volver a Cerebro y pararla")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setOngoing(true)
                .setContentIntent(abrir)
                .build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        else startForeground(1, n);
        try {
            archivo = new File(getCacheDir(), tipo + "_" + System.currentTimeMillis() + ".m4a");
            rec = Build.VERSION.SDK_INT >= 31 ? new MediaRecorder(this) : new MediaRecorder();
            rec.setAudioSource("pregunta".equals(tipo) ? MediaRecorder.AudioSource.VOICE_RECOGNITION : MediaRecorder.AudioSource.MIC);
            rec.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            rec.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            rec.setAudioChannels(1);
            rec.setAudioSamplingRate(16000);
            rec.setAudioEncodingBitRate(32000);
            rec.setOutputFile(archivo.getAbsolutePath());
            rec.prepare();
            rec.start();
            inicio = System.currentTimeMillis();
            cerrojo = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "cerebro:grabacion");
            cerrojo.acquire(4 * 60 * 60 * 1000L);
            activa = this;
        } catch (Exception e) {
            activa = null;
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    float nivel() {
        try { return rec == null ? 0 : Math.min(1f, rec.getMaxAmplitude() / 20000f); } catch (Exception e) { return 0; }
    }

    long segundos() { return (System.currentTimeMillis() - inicio) / 1000; }

    String tipo() { return tipo; }

    /** Para la grabación y devuelve el archivo (o null si falló). */
    File parar() {
        File f = archivo;
        try { rec.stop(); } catch (Exception e) { f = null; }
        try { rec.release(); } catch (Exception ignorado) { }
        rec = null;
        if (cerrojo != null && cerrojo.isHeld()) cerrojo.release();
        activa = null;
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
        return f;
    }

    @Override
    public void onDestroy() {
        if (rec != null) { try { rec.stop(); } catch (Exception ignorado) { } rec.release(); }
        if (cerrojo != null && cerrojo.isHeld()) cerrojo.release();
        activa = null;
        super.onDestroy();
    }
}
