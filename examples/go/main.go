package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func main() {
	base := strings.TrimRight(env("PVE_BASE", "http://localhost:8006/api2/json"), "/")
	node := env("PVE_NODE", "pve01")
	vmid := env("PVE_VMID", "113")
	token := env("PVE_API_TOKEN", "root@pam!automation=automation-secret")
	auth := "PVEAPIToken=" + token

	fmt.Printf("version: %v\n", call(base+"/version", "GET", auth, nil))
	upid := asString(call(base+"/nodes/"+node+"/qemu", "POST", auth, url.Values{
		"vmid":   {vmid},
		"name":   {"go-" + vmid},
		"cores":  {"1"},
		"memory": {"512"},
	}))
	wait(base, node, auth, upid)
	upid = asString(call(base+"/nodes/"+node+"/qemu/"+vmid+"/status/start", "POST", auth, nil))
	wait(base, node, auth, upid)
	fmt.Printf("status: %v\n", call(base+"/nodes/"+node+"/qemu/"+vmid+"/status/current", "GET", auth, nil))
	upid = asString(call(base+"/nodes/"+node+"/qemu/"+vmid+"/status/stop", "POST", auth, nil))
	wait(base, node, auth, upid)
	upid = asString(call(base+"/nodes/"+node+"/qemu/"+vmid, "DELETE", auth, nil))
	wait(base, node, auth, upid)
	fmt.Println("ok")
}

func wait(base, node, auth, upid string) {
	deadline := time.Now().Add(2 * time.Minute)
	for time.Now().Before(deadline) {
		status := call(base+"/nodes/"+node+"/tasks/"+url.PathEscape(upid)+"/status", "GET", auth, nil)
		if m, ok := status.(map[string]any); ok {
			if s, _ := m["status"].(string); s == "stopped" {
				return
			}
		}
		time.Sleep(500 * time.Millisecond)
	}
	panic("timeout waiting for " + upid)
}

func call(u, method, auth string, values url.Values) any {
	var body io.Reader
	if values != nil {
		body = strings.NewReader(values.Encode())
	}
	req, err := http.NewRequest(method, u, body)
	if err != nil {
		panic(err)
	}
	req.Header.Set("Authorization", auth)
	if values != nil {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		panic(fmt.Sprintf("%s %s: %s", method, u, b))
	}
	var envelope struct {
		Data any `json:"data"`
	}
	if err := json.Unmarshal(b, &envelope); err != nil {
		panic(err)
	}
	return envelope.Data
}

func asString(v any) string {
	s, ok := v.(string)
	if !ok {
		panic(fmt.Sprintf("expected string UPID, got %#v", v))
	}
	return s
}
