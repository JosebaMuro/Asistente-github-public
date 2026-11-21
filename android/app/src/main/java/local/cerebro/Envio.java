package local.cerebro;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.UUID;

/** Subida multipart mínima al servidor Cerebro, sin librerías. */
final class Envio {
    private Envio() {}

    static String subir(String base, String ruta, String campo, InputStream datos, String nombre,
                        String tipo, Map<String, String> extra) throws IOException {
        String limite = "----cerebro" + UUID.randomUUID();
        HttpURLConnection c = (HttpURLConnection) new URL(base + ruta).openConnection();
        c.setConnectTimeout(10000);
        c.setReadTimeout(600000); // una pregunta puede tardar si el modelo se está cargando
        c.setDoOutput(true);
        c.setChunkedStreamingMode(64 * 1024);
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + limite);
        try (OutputStream o = c.getOutputStream()) {
            if (extra != null) for (Map.Entry<String, String> e : extra.entrySet()) {
                escribir(o, "--" + limite + "\r\nContent-Disposition: form-data; name=\"" + e.getKey() + "\"\r\n\r\n" + e.getValue() + "\r\n");
            }
            escribir(o, "--" + limite + "\r\nContent-Disposition: form-data; name=\"" + campo + "\"; filename=\""
                    + nombre.replace("\"", "") + "\"\r\nContent-Type: " + (tipo == null ? "application/octet-stream" : tipo) + "\r\n\r\n");
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = datos.read(buf)) > 0) o.write(buf, 0, n);
            escribir(o, "\r\n--" + limite + "--\r\n");
        } finally {
            datos.close();
        }
        int codigo = c.getResponseCode();
        InputStream r = codigo < 400 ? c.getInputStream() : c.getErrorStream();
        String cuerpo = leer(r);
        c.disconnect();
        if (codigo >= 400) throw new IOException("HTTP " + codigo + ": " + cuerpo);
        return cuerpo;
    }

    private static void escribir(OutputStream o, String s) throws IOException {
        o.write(s.getBytes(StandardCharsets.UTF_8));
    }

    static String leer(InputStream i) throws IOException {
        if (i == null) return "";
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = i.read(buf)) > 0) b.write(buf, 0, n);
        i.close();
        return b.toString("UTF-8");
    }
}
