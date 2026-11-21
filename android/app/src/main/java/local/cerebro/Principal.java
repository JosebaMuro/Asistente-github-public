package local.cerebro;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.List;

/**
 * Cerebro para Android: la misma interfaz web del PC dentro de una WebView,
 * más lo que el navegador no deja hacer por http: grabar en segundo plano,
 * recibir lo que compartes desde otras apps y leer en voz alta.
 */
public class Principal extends Activity {
    private static final int ELEGIR = 1;
    private WebView web;
    private Puente puente;
    private SharedPreferences prefs;
    private ValueCallback<Uri[]> eleccion;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("cerebro", MODE_PRIVATE);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        puente = new Puente(this, web);
        web.addJavascriptInterface(puente, "CerebroNativo");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) v.loadUrl("file:///android_asset/sin_conexion.html");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (eleccion != null) eleccion.onReceiveValue(null);
                eleccion = cb;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, p.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                String[] tipos = p.getAcceptTypes();
                if (tipos != null && tipos.length > 0 && !tipos[0].isEmpty()) i.setType(tipos[0]);
                try { startActivityForResult(Intent.createChooser(i, "Elegir archivos"), ELEGIR); }
                catch (Exception e) { eleccion = null; return false; }
                return true;
            }
        });
        pedirPermisos();
        reenviarPendientes();
        if (servidor().isEmpty()) pedirServidor();
        else if (!recibir(getIntent())) web.loadUrl(servidor() + "/");
    }

    @Override
    protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        recibir(i);
    }

    String servidor() { return prefs.getString("servidor", ""); }

    void pedirPermisos() {
        List<String> p = new ArrayList<>();
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != 0) p.add(Manifest.permission.RECORD_AUDIO);
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != 0)
            p.add(Manifest.permission.POST_NOTIFICATIONS);
        if (!p.isEmpty()) requestPermissions(p.toArray(new String[0]), 2);
    }

    void pedirServidor() {
        EditText campo = new EditText(this);
        campo.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        campo.setText(servidor().isEmpty() ? "http://192.168.1.10:8765" : servidor());
        new AlertDialog.Builder(this)
                .setTitle("Dirección de tu PC")
                .setMessage("La que muestra Cerebro al arrancar en el PC (misma Wi-Fi o Tailscale).")
                .setView(campo)
                .setCancelable(!servidor().isEmpty())
                .setPositiveButton("Conectar", (d, w) -> {
                    String u = campo.getText().toString().trim().replaceAll("/+$", "");
                    if (!u.startsWith("http")) u = "http://" + u;
                    prefs.edit().putString("servidor", u).apply();
                    web.loadUrl(u + "/");
                })
                .show();
    }

    /** Lo que llega con "Compartir": texto al cuadro de pegar, archivos directos a la bandeja. */
    private boolean recibir(Intent i) {
        if (i == null || servidor().isEmpty()) return false;
        String accion = i.getAction();
        if (!Intent.ACTION_SEND.equals(accion) && !Intent.ACTION_SEND_MULTIPLE.equals(accion)) return false;
        List<Uri> uris = new ArrayList<>();
        if (Intent.ACTION_SEND_MULTIPLE.equals(accion)) {
            ArrayList<Uri> l = i.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (l != null) uris.addAll(l);
        } else {
            Uri u = i.getParcelableExtra(Intent.EXTRA_STREAM);
            if (u != null) uris.add(u);
        }
        if (uris.isEmpty()) {
            String t = i.getStringExtra(Intent.EXTRA_TEXT);
            String asunto = i.getStringExtra(Intent.EXTRA_SUBJECT);
            String todo = (asunto != null ? asunto + "\n" : "") + (t != null ? t : "");
            try { web.loadUrl(servidor() + "/?text=" + URLEncoder.encode(todo, "UTF-8")); } catch (Exception e) { return false; }
            return true;
        }
        web.loadUrl(servidor() + "/");
        new Thread(() -> {
            int ok = 0;
            for (Uri u : uris) {
                try {
                    Envio.subir(servidor(), "/api/subir", "archivo", getContentResolver().openInputStream(u), nombre(u),
                            getContentResolver().getType(u), null);
                    ok++;
                } catch (Exception e) {
                    aviso("No se pudo enviar " + nombre(u) + ": " + e.getMessage());
                }
            }
            if (ok > 0) aviso("Enviado a Cerebro: " + ok + " archivo(s)");
        }).start();
        setIntent(new Intent());
        return true;
    }

    /** Grabaciones que no se pudieron enviar (sin Wi-Fi, PC apagado): se reintentan al abrir. */
    private void reenviarPendientes() {
        File[] f = getCacheDir().listFiles((d, n) -> n.endsWith(".m4a") && !n.startsWith("pregunta"));
        if (f == null || f.length == 0 || servidor().isEmpty() || Grabacion.activa != null) return;
        new Thread(() -> {
            for (File a : f) {
                try {
                    String receta = a.getName().startsWith("reunion") ? "reunion" : "nota_voz";
                    Envio.subir(servidor(), "/api/subir", "archivo", new FileInputStream(a), a.getName(), "audio/mp4",
                            java.util.Collections.singletonMap("receta", receta));
                    //noinspection ResultOfMethodCallIgnored
                    a.delete();
                    aviso("Grabación pendiente enviada: " + a.getName());
                } catch (Exception ignorado) { }
            }
        }).start();
    }

    private String nombre(Uri u) {
        try (Cursor c = getContentResolver().query(u, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) return c.getString(0);
        } catch (Exception ignorado) { }
        String s = u.getLastPathSegment();
        return s == null ? "compartido" : s;
    }

    private void aviso(String t) { runOnUiThread(() -> Toast.makeText(this, t, Toast.LENGTH_LONG).show()); }

    @Override
    protected void onActivityResult(int pedido, int resultado, Intent datos) {
        if (pedido == ELEGIR && eleccion != null) {
            Uri[] r = null;
            if (resultado == RESULT_OK && datos != null) {
                if (datos.getClipData() != null) {
                    r = new Uri[datos.getClipData().getItemCount()];
                    for (int k = 0; k < r.length; k++) r[k] = datos.getClipData().getItemAt(k).getUri();
                } else if (datos.getData() != null) r = new Uri[]{datos.getData()};
            }
            eleccion.onReceiveValue(r);
            eleccion = null;
            return;
        }
        super.onActivityResult(pedido, resultado, datos);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        puente.cerrar();
        web.destroy();
        super.onDestroy();
    }
}
