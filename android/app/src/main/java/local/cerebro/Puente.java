package local.cerebro;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import java.io.File;
import java.io.FileInputStream;
import java.util.Collections;
import java.util.Locale;
import org.json.JSONObject;

/** Lo que la interfaz web puede pedir al teléfono: window.CerebroNativo.* */
final class Puente {
    private final Principal app;
    private final WebView web;
    private TextToSpeech voz;

    Puente(Principal app, WebView web) {
        this.app = app;
        this.web = web;
        voz = new TextToSpeech(app, estado -> {
            if (estado == TextToSpeech.SUCCESS) voz.setLanguage(new Locale("es", "ES"));
        });
        voz.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            @Override public void onStart(String id) { }
            @Override public void onDone(String id) { avisar("fin_voz", "null"); }
            @Override public void onError(String id) { avisar("fin_voz", "null"); }
        });
    }

    @JavascriptInterface
    public boolean empezar(String tipo) {
        if (app.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            app.runOnUiThread(app::pedirPermisos);
            return false;
        }
        if (Grabacion.activa != null) return true;
        Intent i = new Intent(app, Grabacion.class).putExtra("tipo", tipo);
        app.startForegroundService(i);
        return true;
    }

    @JavascriptInterface
    public String estado() {
        Grabacion g = Grabacion.activa;
        try {
            return new JSONObject()
                    .put("grabando", g != null)
                    .put("segundos", g == null ? 0 : g.segundos())
                    .put("nivel", g == null ? 0 : g.nivel())
                    .toString();
        } catch (Exception e) { return "{}"; }
    }

    @JavascriptInterface
    public void parar(String receta) {
        Grabacion g = Grabacion.activa;
        if (g == null) { avisar("error", JSONObject.quote("No había ninguna grabación en marcha")); return; }
        String tipo = g.tipo();
        File f = g.parar();
        if (f == null) { avisar("error", JSONObject.quote("La grabación salió vacía")); return; }
        new Thread(() -> {
            try {
                String r;
                if ("pregunta".equals(tipo)) {
                    r = Envio.subir(app.servidor(), "/api/preguntar_audio", "audio", new FileInputStream(f), f.getName(), "audio/mp4", null);
                    avisar("respuesta", r);
                } else {
                    r = Envio.subir(app.servidor(), "/api/subir", "archivo", new FileInputStream(f), f.getName(), "audio/mp4",
                            receta == null || receta.isEmpty() ? null : Collections.singletonMap("receta", receta));
                    avisar("subido", r);
                }
                //noinspection ResultOfMethodCallIgnored
                f.delete();
            } catch (Exception e) {
                // Se conserva el audio en caché para no perder la reunión; se reintenta al abrir la app.
                avisar("error", JSONObject.quote("No se pudo enviar (se reintentará): " + e.getMessage()));
            }
        }).start();
    }

    @JavascriptInterface
    public void hablar(String texto) {
        voz.speak(texto, TextToSpeech.QUEUE_FLUSH, null, "cerebro");
    }

    @JavascriptInterface
    public void configurar() { app.runOnUiThread(app::pedirServidor); }

    @JavascriptInterface
    public String servidor() { return app.servidor(); }

    void avisar(String evento, String json) {
        String js = "window.cerebroNativo && window.cerebroNativo(" + JSONObject.quote(evento) + "," + json + ")";
        web.post(() -> web.evaluateJavascript(js, null));
    }

    void cerrar() { voz.shutdown(); }
}
