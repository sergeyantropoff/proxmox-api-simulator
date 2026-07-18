import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Minimal Java 11+ cookbook against HTTP :8006 using an API token.
 *
 *   javac Cookbook.java && java Cookbook
 */
public final class Cookbook {
  private static final HttpClient CLIENT = HttpClient.newHttpClient();

  public static void main(String[] args) throws Exception {
    String base = env("PVE_BASE", "https://localhost:8006/api2/json");
    String node = env("PVE_NODE", "pve01");
    String vmid = env("PVE_VMID", "114");
    String token = env("PVE_API_TOKEN", "root@pam!automation=automation-secret");
    String auth = "PVEAPIToken=" + token;

    System.out.println("version: " + data(get(base + "/version", auth)));
    String upid =
        data(
            form(
                base + "/nodes/" + node + "/qemu",
                auth,
                Map.of(
                    "vmid", vmid,
                    "name", "java-" + vmid,
                    "cores", "1",
                    "memory", "512")));
    waitTask(base, node, auth, upid);
    upid = data(form(base + "/nodes/" + node + "/qemu/" + vmid + "/status/start", auth, Map.of()));
    waitTask(base, node, auth, upid);
    System.out.println(
        "status: " + data(get(base + "/nodes/" + node + "/qemu/" + vmid + "/status/current", auth)));
    upid = data(form(base + "/nodes/" + node + "/qemu/" + vmid + "/status/stop", auth, Map.of()));
    waitTask(base, node, auth, upid);
    upid = data(delete(base + "/nodes/" + node + "/qemu/" + vmid, auth));
    waitTask(base, node, auth, upid);
    System.out.println("ok");
  }

  private static void waitTask(String base, String node, String auth, String upid)
      throws Exception {
    long deadline = System.currentTimeMillis() + 120_000;
    String encoded = URLEncoder.encode(upid, StandardCharsets.UTF_8);
    while (System.currentTimeMillis() < deadline) {
      String body = get(base + "/nodes/" + node + "/tasks/" + encoded + "/status", auth);
      if (body.contains("\"status\":\"stopped\"") || body.contains("\"status\": \"stopped\"")) {
        return;
      }
      Thread.sleep(500);
    }
    throw new IllegalStateException("timeout waiting for " + upid);
  }

  private static String env(String key, String def) {
    String value = System.getenv(key);
    return value == null || value.isBlank() ? def : value;
  }

  private static String get(String uri, String auth) throws IOException, InterruptedException {
    return send(
        HttpRequest.newBuilder(URI.create(uri))
            .timeout(Duration.ofSeconds(60))
            .header("Authorization", auth)
            .GET()
            .build());
  }

  private static String delete(String uri, String auth) throws IOException, InterruptedException {
    return send(
        HttpRequest.newBuilder(URI.create(uri))
            .timeout(Duration.ofSeconds(60))
            .header("Authorization", auth)
            .DELETE()
            .build());
  }

  private static String form(String uri, String auth, Map<String, String> fields)
      throws IOException, InterruptedException {
    String body =
        fields.entrySet().stream()
            .map(
                e ->
                    URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8)
                        + "="
                        + URLEncoder.encode(e.getValue(), StandardCharsets.UTF_8))
            .collect(Collectors.joining("&"));
    return send(
        HttpRequest.newBuilder(URI.create(uri))
            .timeout(Duration.ofSeconds(60))
            .header("Authorization", auth)
            .header("Content-Type", "application/x-www-form-urlencoded")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build());
  }

  private static String send(HttpRequest request) throws IOException, InterruptedException {
    HttpResponse<String> response = CLIENT.send(request, HttpResponse.BodyHandlers.ofString());
    if (response.statusCode() >= 300) {
      throw new IOException(response.statusCode() + ": " + response.body());
    }
    return response.body();
  }

  /** Extract Proxmox envelope data when it is a JSON string UPID. */
  private static String data(String body) {
    String marker = "\"data\":\"";
    int start = body.indexOf(marker);
    if (start >= 0) {
      start += marker.length();
      int end = body.indexOf('"', start);
      if (end > start) {
        return body.substring(start, end);
      }
    }
    return body;
  }
}
