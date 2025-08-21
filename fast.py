#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
nos.py – Internet & LAN network tester (macOS friendly)

Run with no args → interactive menu.
Also supports CLI:
  - python3 nos.py internet --preset diagnose ...
  - python3 nos.py lan --server 192.168.1.10 --preset max-tcp ...

Features:
- Internet test (prefers Ookla CLI, then speedtest-cli binary, then python module)
- Multi-target ping (loss/jitter) + thresholds verdict
- macOS networkQuality integration (capacity & responsiveness)
- macOS Wi-Fi info (RSSI/Noise/TxRate/Channel/PHY)
- LAN test via iPerf3 (parallel/reverse/UDP/duration)
- CSV logging (internet_speed_history.csv + lan_speed_history.csv)
- Optional JSON output
- Presets + Interactive menu
"""

import argparse
import csv
import datetime
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time

# Optional third-party (only used if we fall back to python module)
try:
    import speedtest as speedtest_module  # may not exist if not installed in current env
except Exception:
    speedtest_module = None  # handled later

# ===================== Utilities =====================

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_private_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception:
        return "Tidak dapat ditemukan"

def run_cmd(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)

def is_macos():
    return platform.system() == "Darwin"

def which(binname):
    res = run_cmd(["/usr/bin/env", "which", binname])
    return res.stdout.strip() if res.returncode == 0 else None

def pretty_pass(b):  # simple green/red markers
    return "✅ PASS" if b else "❌ FAIL"

# ===================== Recommendations =====================

def get_streaming_recommendation(speed_mbps):
    if speed_mbps >= 25:
        return "Sangat baik untuk streaming 4K UHD (2160p)."
    elif speed_mbps >= 8:
        return "Baik untuk streaming Full HD (1080p)."
    elif speed_mbps >= 5:
        return "Cukup untuk streaming HD (720p)."
    else:
        return "Kecepatan mungkin kurang stabil untuk streaming."

def get_gaming_recommendation(ping):
    if ping < 30:
        return "Ping sangat rendah, ideal untuk game kompetitif."
    elif ping < 60:
        return "Ping baik, lancar untuk sebagian besar game."
    else:
        return "Ping tinggi, kurang direkomendasikan."

def get_videocall_recommendation(download_mbps, upload_mbps):
    if upload_mbps >= 5 and download_mbps >= 8:
        return "Sangat baik untuk video call grup Full HD."
    elif upload_mbps >= 3 and download_mbps >= 5:
        return "Baik untuk video call personal HD."
    else:
        return "Cukup untuk video call standar."

# ===================== CSV / JSON =====================

def save_csv(filename, header, row):
    file_exists = os.path.isfile(filename)
    try:
        with open(filename, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(header)
            w.writerow(row)
        print(f"✅ Disimpan ke '{filename}'")
    except Exception as e:
        print(f"❌ Gagal simpan CSV: {e}")

def save_json(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ JSON ditulis ke '{filename}'")
    except Exception as e:
        print(f"❌ Gagal simpan JSON: {e}")

# ===================== Internet (speedtest) with fallbacks =====================

def do_speedtest(retries=2, pause=2):
    """
    Prefer CLIs (Ookla 'speedtest' then 'speedtest-cli'), fall back to
    python module if available. Return dict or raise last error.
    """
    last_err = None

    # 1) Try official Ookla CLI
    spd = which("speedtest")
    if spd:
        for attempt in range(1, retries+1):
            try:
                out = run_cmd([spd, "--accept-license", "--accept-gdpr", "-f", "json"], check=True).stdout
                j = json.loads(out)
                down = (j.get("download", {}).get("bandwidth", 0) * 8) / 1_000_000  # bytes/s → bits/s → Mbps
                up   = (j.get("upload", {}).get("bandwidth", 0) * 8) / 1_000_000
                ping = j.get("ping", {}).get("latency")
                ip   = j.get("interface", {}).get("externalIp")
                srv  = j.get("server", {}) or {}
                loc  = srv.get("location") if isinstance(srv.get("location"), dict) else {}
                return {
                    "download_mbps": float(down or 0),
                    "upload_mbps": float(up or 0),
                    "ping_ms": float(ping or 0),
                    "public_ip": ip,
                    "server": {
                        "name": srv.get("name"),
                        "country": srv.get("country"),
                        "lat": loc.get("lat"),
                        "lon": loc.get("lon"),
                    },
                }
            except Exception as e:
                last_err = e
                print(f"⚠️ speedtest (Ookla CLI) gagal (attempt {attempt}/{retries}): {e}")
                time.sleep(pause)

    # 2) Try Homebrew 'speedtest-cli' binary (sivel)
    spd_cli = which("speedtest-cli")
    if spd_cli:
        for attempt in range(1, retries+1):
            try:
                out = run_cmd([spd_cli, "--json"], check=True).stdout
                j = json.loads(out)
                return {
                    "download_mbps": float((j.get("download", 0))/1_000_000),
                    "upload_mbps": float((j.get("upload", 0))/1_000_000),
                    "ping_ms": float(j.get("ping", 0)),
                    "public_ip": j.get("client", {}).get("ip"),
                    "server": {
                        "name": j.get("server", {}).get("sponsor") or j.get("server", {}).get("name"),
                        "country": j.get("server", {}).get("country"),
                        "lat": j.get("server", {}).get("lat"),
                        "lon": j.get("server", {}).get("lon"),
                    },
                }
            except Exception as e:
                last_err = e
                print(f"⚠️ speedtest-cli (binary) gagal (attempt {attempt}/{retries}): {e}")
                time.sleep(pause)

    # 3) Fallback: python module (requires venv pip install speedtest-cli)
    if speedtest_module is not None:
        for attempt in range(1, retries+1):
            try:
                st = speedtest_module.Speedtest()
                st.get_best_server()
                down = st.download() / 1_000_000
                up = st.upload() / 1_000_000
                ping = st.results.ping
                public_ip = st.results.client.get('ip')
                server = st.results.server or {}
                return {
                    "download_mbps": down,
                    "upload_mbps": up,
                    "ping_ms": ping,
                    "public_ip": public_ip,
                    "server": {
                        "name": server.get('name'),
                        "country": server.get('country'),
                        "lat": server.get('lat'),
                        "lon": server.get('lon')
                    }
                }
            except Exception as e:
                last_err = e
                print(f"⚠️ speedtest (python module) gagal (attempt {attempt}/{retries}): {e}")
                time.sleep(pause)

    # If all paths failed
    if last_err is None:
        last_err = RuntimeError("Tidak ada mekanisme speedtest yang tersedia.")
    raise last_err

# ===================== Ping / Jitter / Loss =====================

PING_LOSS_RE = re.compile(r"(\d+(?:\.\d+)?)% packet loss")
PING_RTT_RE  = re.compile(r"= ([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+) ms")

def ping_stats(host, count=10, timeout=1):
    try:
        out = run_cmd(["ping", "-c", str(count), "-W", str(timeout), host]).stdout
        m_loss = PING_LOSS_RE.search(out)
        loss = float(m_loss.group(1)) if m_loss else None
        m_rtt = PING_RTT_RE.search(out)
        rtt = dict(zip(["min","avg","max","stddev"], map(float, m_rtt.groups()))) if m_rtt else {}
        return {"host": host, "loss_pct": loss, "rtt_ms": rtt}
    except Exception as e:
        return {"host": host, "error": str(e)}

# ===================== macOS: networkQuality & Wi-Fi =====================

def run_networkquality():
    if not is_macos():
        return None
    if not which("networkQuality"):
        return None
    try:
        out = run_cmd(["networkQuality", "-v"]).stdout
        data = {}
        for line in out.splitlines():
            if ":" in line:
                k, v = [s.strip() for s in line.split(":", 1)]
                data[k] = v
        def take_float(key):
            raw = data.get(key, "0").split()[0]
            try:
                return float(raw)
            except:
                return 0.0
        return {
            "download_mbps": take_float("Downlink Capacity"),
            "upload_mbps": take_float("Uplink Capacity"),
            "responsiveness_rtt_ms": take_float("Responsiveness")
        }
    except Exception:
        return None

def get_wifi_info():
    if not is_macos():
        return None
    airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    if not os.path.exists(airport):
        return None
    try:
        out = run_cmd([airport, "-I"]).stdout
        kv = {}
        for line in out.splitlines():
            if ":" in line:
                k, v = line.strip().split(":", 1)
                kv[k.strip()] = v.strip()
        return {
            "SSID": kv.get("SSID"),
            "BSSID": kv.get("BSSID"),
            "RSSI_dBm": kv.get("agrCtlRSSI"),
            "Noise_dBm": kv.get("agrCtlNoise"),
            "TxRate_Mbps": kv.get("lastTxRate"),
            "Channel": kv.get("channel"),
            "PHY": kv.get("op mode")
        }
    except Exception:
        return None

# ===================== iPerf3 (LAN) =====================

def iperf3_available():
    return which("iperf3") is not None

def iperf3_test(server, parallel=1, reverse=False, udp=False, udp_bw="0", duration=10):
    if not iperf3_available():
        raise RuntimeError("iperf3 tidak ditemukan. Install: brew install iperf3")
    cmd = ["iperf3", "-c", server, "-J", "-t", str(duration)]
    if parallel > 1:
        cmd += ["-P", str(parallel)]
    if reverse:
        cmd += ["-R"]
    if udp:
        cmd += ["-u"]
        if udp_bw != "0":
            cmd += ["-b", udp_bw]
    res = run_cmd(cmd, check=True).stdout
    j = json.loads(res)
    out = {"server": server, "parallel": parallel, "reverse": reverse, "udp": udp, "duration": duration}
    if udp:
        s = j["end"]["sum"]
        out.update({
            "bits_per_second": s.get("bits_per_second"),
            "jitter_ms": s.get("jitter_ms"),
            "lost_percent": s.get("lost_percent")
        })
    else:
        s = j["end"].get("sum_received") or j["end"].get("sum_sent") or {}
        out.update({"bits_per_second": s.get("bits_per_second")})
    return out

# ===================== Threshold Verdicts =====================

def verdict_internet(meas, thresholds):
    v = {}
    if not thresholds:
        return v
    if thresholds.get("min_down") is not None and meas.get("download_mbps") is not None:
        v["download"] = meas["download_mbps"] >= thresholds["min_down"]
    if thresholds.get("min_up") is not None and meas.get("upload_mbps") is not None:
        v["upload"] = meas["upload_mbps"] >= thresholds["min_up"]
    if thresholds.get("max_ping") is not None and meas.get("ping_ms") is not None:
        v["ping"] = meas["ping_ms"] <= thresholds["max_ping"]
    return v

def verdict_ping(ping_results, thresholds):
    v = {}
    if not thresholds:
        return v
    for p in ping_results:
        name = p["host"]
        ok = True
        if "max_jitter" in thresholds and p.get("rtt_ms", {}).get("stddev") is not None:
            ok = ok and (p["rtt_ms"]["stddev"] <= thresholds["max_jitter"])
        if "max_loss" in thresholds and p.get("loss_pct") is not None:
            ok = ok and (p["loss_pct"] <= thresholds["max_loss"])
        v[name] = ok
    return v

# ===================== Presets & Menu =====================

PRESETS_INTERNET = {
    "basic": {
        "use_networkquality": False, "wifi_info": False,
        "ping_targets": None, "ping_count": 10, "ping_timeout": 1,
        "min_down": None, "min_up": None, "max_ping": None, "max_jitter": None, "max_loss": None,
        "retries": 2, "retry_pause": 2, "tag": "basic", "json_out": None
    },
    "diagnose": {
        "use_networkquality": True, "wifi_info": True,
        "ping_targets": "192.168.1.1,8.8.8.8,1.1.1.1", "ping_count": 15, "ping_timeout": 1,
        "min_down": 50, "min_up": 10, "max_ping": 50, "max_jitter": 15, "max_loss": 1,
        "retries": 2, "retry_pause": 2, "tag": "diagnose", "json_out": "internet_results.json"
    },
    "wifi": {
        "use_networkquality": True, "wifi_info": True,
        "ping_targets": "8.8.8.8,1.1.1.1", "ping_count": 10, "ping_timeout": 1,
        "min_down": None, "min_up": None, "max_ping": 60, "max_jitter": 20, "max_loss": 2,
        "retries": 2, "retry_pause": 2, "tag": "wifi", "json_out": None
    },
    "fast": {
        "use_networkquality": False, "wifi_info": False,
        "ping_targets": "8.8.8.8", "ping_count": 5, "ping_timeout": 1,
        "min_down": None, "min_up": None, "max_ping": None, "max_jitter": None, "max_loss": None,
        "retries": 1, "retry_pause": 1, "tag": "fast", "json_out": None
    }
}

PRESETS_LAN = {
    "quick":     {"lan_parallel": 1, "lan_reverse": False, "lan_udp": False, "lan_udp_bandwidth": "0",    "lan_duration": 10,  "tag": "lan-quick",    "json_out": None},
    "max-tcp":   {"lan_parallel": 4, "lan_reverse": True,  "lan_udp": False, "lan_udp_bandwidth": "0",    "lan_duration": 30,  "tag": "lan-max-tcp", "json_out": "lan_results.json"},
    "udp-500M":  {"lan_parallel": 1, "lan_reverse": False, "lan_udp": True,  "lan_udp_bandwidth": "500M", "lan_duration": 30,  "tag": "lan-udp-500M","json_out": None},
    "soak-2min": {"lan_parallel": 2, "lan_reverse": True,  "lan_udp": False, "lan_udp_bandwidth": "0",    "lan_duration": 120, "tag": "lan-soak",    "json_out": None},
}

def apply_internet_preset(args, name):
    p = PRESETS_INTERNET.get(name)
    if not p:
        raise ValueError(f"Preset internet '{name}' tidak dikenal.")
    for k, v in p.items():
        setattr(args, k, v)

def apply_lan_preset(args, name):
    p = PRESETS_LAN.get(name)
    if not p:
        raise ValueError(f"Preset LAN '{name}' tidak dikenal.")
    for k, v in p.items():
        setattr(args, k, v)

def interactive_menu():
    print("\n=== Network Tester Menu ===")
    print("1) Internet → basic")
    print("2) Internet → diagnose")
    print("3) Internet → wifi")
    print("4) Internet → fast")
    print("5) LAN → quick (TCP)")
    print("6) LAN → max-tcp (parallel+reverse)")
    print("7) LAN → udp-500M (jitter/loss)")
    print("8) LAN → soak-2min")
    choice = input("\nPilih [1-8]: ").strip()

    if choice in {"1","2","3","4"}:
        preset_map = {"1":"basic","2":"diagnose","3":"wifi","4":"fast"}
        preset = preset_map[choice]
        a = argparse.Namespace(
            mode="internet",
            retries=2, retry_pause=2,
            ping_targets=None, ping_count=10, ping_timeout=1,
            use_networkquality=False, wifi_info=False,
            min_down=None, min_up=None, max_ping=None, max_jitter=None, max_loss=None,
            json_out=None, tag=None
        )
        apply_internet_preset(a, preset)
        t = input(f"Tag (enter untuk '{a.tag}'): ").strip()
        if t: a.tag = t
        return a

    elif choice in {"5","6","7","8"}:
        preset_map = {"5":"quick","6":"max-tcp","7":"udp-500M","8":"soak-2min"}
        preset = preset_map[choice]
        server = input("Masukkan IP/host iPerf3 server: ").strip()
        if not server:
            print("❌ Server wajib diisi.")
            return None
        a = argparse.Namespace(
            mode="lan",
            server=server,
            lan_parallel=1, lan_reverse=False, lan_udp=False, lan_udp_bandwidth="0",
            lan_duration=10, json_out=None, tag=None
        )
        apply_lan_preset(a, preset)
        t = input(f"Tag (enter untuk '{a.tag}'): ").strip()
        if t: a.tag = t
        return a

    else:
        print("❌ Pilihan tidak valid.")
        return None

# ===================== Internet flow (graceful on failure) =====================

def internet_flow(args):
    print("🔎 Internet test mulai...")
    private_ip = get_private_ip()

    st = None
    try:
        st = do_speedtest(retries=args.retries, pause=args.retry_pause)
    except Exception as e:
        print(f"❌ Speedtest gagal total: {e}")
        print("➡️  Lanjutkan dengan networkQuality/Wi-Fi/ping saja...\n")

    srv = (st or {}).get("server") or {}

    if st:
        print("\n--- Hasil Speedtest ---")
        print(f"IP Private   : {private_ip}")
        print(f"IP Publik    : {st.get('public_ip')}")
        print(f"Server       : {srv.get('name')}, {srv.get('country')} (lat:{srv.get('lat')} lon:{srv.get('lon')})")
        print(f"Ping         : {st['ping_ms']:.2f} ms")
        print(f"Download     : {st['download_mbps']:.2f} Mbps")
        print(f"Upload       : {st['upload_mbps']:.2f} Mbps")

        print("\n--- Rekomendasi Aktivitas ---")
        print(f"🎬 Streaming : {get_streaming_recommendation(st['download_mbps'])}")
        print(f"🎮 Gaming    : {get_gaming_recommendation(st['ping_ms'])}")
        print(f"📞 VideoCall : {get_videocall_recommendation(st['download_mbps'], st['upload_mbps'])}")

    # networkQuality
    nq = None
    if getattr(args, "use_networkquality", False):
        print("\n⏱️  Jalankan networkQuality (macOS)...")
        nq = run_networkquality()
        if nq:
            print(f"networkQuality → Down {nq['download_mbps']:.2f} Mbps | Up {nq['upload_mbps']:.2f} Mbps | Resp ~{nq['responsiveness_rtt_ms']:.0f} ms")
        else:
            print("networkQuality tidak tersedia.")

    # Wi-Fi info
    wifi = None
    if getattr(args, "wifi_info", False):
        print("\n📶 Info Wi-Fi (macOS airport)...")
        wifi = get_wifi_info()
        if wifi:
            for k, v in wifi.items():
                print(f"{k:14}: {v}")
        else:
            print("Tidak tersedia / bukan macOS / tidak terhubung via Wi-Fi.")

    # Ping targets
    ping_results = []
    if getattr(args, "ping_targets", None):
        print("\n📡 Ping multi-target...")
        for host in args.ping_targets.split(","):
            host = host.strip()
            if not host:
                continue
            p = ping_stats(host, count=args.ping_count, timeout=args.ping_timeout)
            ping_results.append(p)
            if "error" in p:
                print(f"- {host}: ERROR {p['error']}")
            else:
                rtt = p.get("rtt_ms", {})
                print(f"- {host}: loss {p.get('loss_pct')}% | rtt min/avg/max/stddev = "
                      f"{rtt.get('min','-')}/{rtt.get('avg','-')}/{rtt.get('max','-')}/{rtt.get('stddev','-')} ms")

    # Thresholds & verdict
    thresholds = None
    keys = ["min_down", "min_up", "max_ping", "max_jitter", "max_loss"]
    if any(getattr(args, k, None) is not None for k in keys):
        thresholds = {k: getattr(args, k) for k in keys if getattr(args, k, None) is not None}

    if thresholds:
        print("\n✅/❌ Threshold checks")
        if st:
            vint = verdict_internet(st, thresholds)
            for k in ["download", "upload", "ping"]:
                if k in vint:
                    print(f"- {k:8}: {pretty_pass(vint[k])}")
        if ping_results:
            vping = verdict_ping(ping_results, thresholds)
            for host, ok in vping.items():
                print(f"- ping {host:15}: {pretty_pass(ok)}")

    # CSV row always written (zeros if no speedtest)
    internet_row = [
        now_str(),
        f"{(st or {}).get('download_mbps', 0):.2f}",
        f"{(st or {}).get('upload_mbps', 0):.2f}",
        f"{(st or {}).get('ping_ms', 0):.2f}",
        srv.get('name') or "",
        srv.get('country') or "",
        getattr(args, "tag", "") or ""
    ]
    save_csv("internet_speed_history.csv",
             ["Timestamp","Download (Mbps)","Upload (Mbps)","Ping (ms)","Server Name","Server Location","Tag"],
             internet_row)

    # JSON (optional)
    if getattr(args, "json_out", None):
        out = {
            "timestamp": now_str(),
            "private_ip": private_ip,
            "internet": st,  # may be None
            "networkQuality": nq,
            "wifi": wifi,
            "ping": ping_results,
            "thresholds": thresholds,
            "tag": getattr(args, "tag", None)
        }
        save_json(args.json_out, out)

# ===================== LAN flow =====================

def lan_flow(args):
    if not getattr(args, "server", None):
        print("❌ Harus set --server <IP> untuk mode LAN.")
        sys.exit(1)

    print(f"🔎 iPerf3 test ke {args.server} (parallel={args.lan_parallel}, reverse={args.lan_reverse}, udp={args.lan_udp}, bw={args.lan_udp_bandwidth}, t={args.lan_duration}s)")
    res = iperf3_test(
        server=args.server,
        parallel=args.lan_parallel,
        reverse=args.lan_reverse,
        udp=args.lan_udp,
        udp_bw=args.lan_udp_bandwidth,
        duration=args.lan_duration
    )

    print("\n--- Hasil LAN (iPerf3) ---")
    print(f"Server     : {res['server']}")
    if res.get("udp"):
        print(f"Throughput : {res['bits_per_second']/1e9:.2f} Gbps (UDP)")
        print(f"Jitter     : {res.get('jitter_ms','-')} ms")
        print(f"Loss       : {res.get('lost_percent','-')} %")
    else:
        print(f"Throughput : {res['bits_per_second']/1e9:.2f} Gbps (TCP)")

    # CSV
    lan_row = [now_str(), res['server'], f"{(res['bits_per_second'] or 0)/1e9:.2f}", getattr(args, "tag", "") or ""]
    save_csv("lan_speed_history.csv", ["Timestamp","Server IP","Transfer (Gbps)","Tag"], lan_row)

    # JSON
    if getattr(args, "json_out", None):
        out = {"timestamp": now_str(), "lan": res, "tag": getattr(args, "tag", None)}
        save_json(args.json_out, out)

# ===================== CLI main =====================

def main():
    parser = argparse.ArgumentParser(description="Alat Tes Kecepatan Internet dan LAN (macOS friendly).")
    sub = parser.add_subparsers(dest="mode", required=False)

    # internet subcommand
    p_int = sub.add_parser("internet", help="Mode internet (speedtest + optional ping/networkQuality/Wi-Fi)")
    p_int.add_argument("--preset", choices=list(PRESETS_INTERNET.keys()),
                       help=f"Pilih preset internet: {', '.join(PRESETS_INTERNET.keys())}")
    p_int.add_argument("--retries", type=int, default=2, help="Retry speedtest jika gagal (default 2)")
    p_int.add_argument("--retry-pause", type=int, default=2, help="Jeda antar retry (detik)")
    p_int.add_argument("--ping-targets", help="Daftar host dipisah koma untuk ping (mis: 8.8.8.8,1.1.1.1,gateway)")
    p_int.add_argument("--ping-count", type=int, default=10, help="Jumlah paket ping per target (default 10)")
    p_int.add_argument("--ping-timeout", type=int, default=1, help="Timeout ping per paket (detik)")
    p_int.add_argument("--use-networkquality", action="store_true", help="Jalankan networkQuality (macOS)")
    p_int.add_argument("--wifi-info", action="store_true", help="Tampilkan info Wi-Fi (macOS)")
    p_int.add_argument("--min-down", type=float, help="Threshold minimal download (Mbps)")
    p_int.add_argument("--min-up", type=float, help="Threshold minimal upload (Mbps)")
    p_int.add_argument("--max-ping", type=float, help="Threshold maksimal ping (ms)")
    p_int.add_argument("--max-jitter", type=float, help="Threshold maksimal jitter stddev (ms)")
    p_int.add_argument("--max-loss", type=float, help="Threshold maksimal loss (%)")
    p_int.add_argument("--json-out", help="Tulis hasil lengkap ke JSON file")
    p_int.add_argument("--tag", help="Label/tag custom untuk logging")

    # lan subcommand
    p_lan = sub.add_parser("lan", help="Mode LAN (iPerf3)")
    p_lan.add_argument("--preset", choices=list(PRESETS_LAN.keys()),
                       help=f"Pilih preset LAN: {', '.join(PRESETS_LAN.keys())}")
    p_lan.add_argument("--server", help="Alamat IP/host server iPerf3")
    p_lan.add_argument("--lan-parallel", type=int, default=1, help="Jumlah parallel streams (-P)")
    p_lan.add_argument("--lan-reverse", action="store_true", help="Reverse test (-R)")
    p_lan.add_argument("--lan-udp", action="store_true", help="Gunakan UDP (-u)")
    p_lan.add_argument("--lan-udp-bandwidth", default="0", help="Target UDP bandwidth, mis: 500M / 1G (default 0)")
    p_lan.add_argument("--lan-duration", type=int, default=10, help="Durasi test (detik, default 10)")
    p_lan.add_argument("--json-out", help="Tulis hasil lengkap ke JSON file")
    p_lan.add_argument("--tag", help="Label/tag custom untuk logging")

    # explicit menu subcommand (optional)
    sub.add_parser("menu", help="Mode menu interaktif")

    # If no args → run menu immediately
    if len(sys.argv) == 1:
        picked = interactive_menu()
        if not picked:
            sys.exit(1)
        try:
            if picked.mode == "internet":
                internet_flow(picked)
            else:
                lan_flow(picked)
        except KeyboardInterrupt:
            print("\nDibatalkan oleh user.")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            sys.exit(1)
        return

    # Otherwise parse CLI normally
    args, _ = parser.parse_known_args()

    if args.mode == "menu":
        picked = interactive_menu()
        if not picked:
            sys.exit(1)
        try:
            if picked.mode == "internet":
                internet_flow(picked)
            else:
                lan_flow(picked)
        except KeyboardInterrupt:
            print("\nDibatalkan oleh user.")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            sys.exit(1)
        return

    # Defaults / presets
    if args.mode == "internet":
        if getattr(args, "preset", None):
            apply_internet_preset(args, args.preset)
        # ensure attrs exist even without presets
        for k, v in dict(
            retries=2, retry_pause=2, ping_targets=None, ping_count=10, ping_timeout=1,
            use_networkquality=False, wifi_info=False,
            min_down=None, min_up=None, max_ping=None, max_jitter=None, max_loss=None,
            json_out=None, tag=None
        ).items():
            if not hasattr(args, k):
                setattr(args, k, v)
        try:
            internet_flow(args)
        except KeyboardInterrupt:
            print("\nDibatalkan oleh user.")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            sys.exit(1)

    elif args.mode == "lan":
        if getattr(args, "preset", None):
            apply_lan_preset(args, args.preset)
        # defaults
        for k, v in dict(
            server=None, lan_parallel=1, lan_reverse=False, lan_udp=False,
            lan_udp_bandwidth="0", lan_duration=10, json_out=None, tag=None
        ).items():
            if not hasattr(args, k):
                setattr(args, k, v)
        try:
            if not args.server:
                print("❌ Harus set --server <IP> untuk mode LAN (atau pilih via menu).")
                sys.exit(1)
            lan_flow(args)
        except KeyboardInterrupt:
            print("\nDibatalkan oleh user.")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            sys.exit(1)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()