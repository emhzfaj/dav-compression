#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
nos.py – Internet & LAN network tester (macOS friendly)
- Hanya pakai modul Python `speedtest-cli`
- Menu interaktif by default (tanpa prompt Tag)
- Progress bar:
  • Cari server (spinner → 100%)
  • Download/Upload (indeterminate bar → 100% + Mbps)
  • Ping per-paket (true progress)
- Ping (loss/jitter), macOS networkQuality & Wi‑Fi info
- iPerf3 LAN tests
- CSV + optional JSON logging
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
import threading
import itertools
from statistics import mean, pstdev

# -------- Only Python module from speedtest-cli --------
try:
    import speedtest  # provided by speedtest-cli (install in venv)
except Exception:
    speedtest = None  # handled at runtime

# ===================== UI helpers =====================

_SPINNER_FRAMES = "⠋⠙⠸⠴⠦⠇"

class Spinner:
    def __init__(self, label="Working"):
        self.label = label
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        for ch in itertools.cycle(_SPINNER_FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{self.label} {ch}")
            sys.stdout.flush()
            time.sleep(0.08)
        # clear line
        sys.stdout.write("\r" + " " * (len(self.label) + 4) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        self._t.join()

def draw_bar(prefix, pct, width=28, suffix=""):
    pct = max(0, min(100, int(pct)))
    fill = int((pct/100)*width)
    bar = "█"*fill + "░"*(width-fill)
    sys.stdout.write(f"\r{prefix} [{bar}] {pct:3d}%{('  '+suffix) if suffix else ''}")
    sys.stdout.flush()

class IndeterminateBar:
    """Animate a moving block until stop(); on stop() snap to 100%."""
    def __init__(self, prefix, width=28, period=0.07):
        self.prefix = prefix
        self.width = width
        self.period = period
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        pos = 0
        blk = max(4, self.width//6)
        while not self._stop.is_set():
            line = ["░"]*self.width
            for i in range(blk):
                line[(pos+i) % self.width] = "█"
            bar_str = "".join(line)
            sys.stdout.write(f"\r{self.prefix} [{bar_str}]")
            sys.stdout.flush()
            pos = (pos+1) % self.width
            time.sleep(self.period)

    def start(self):
        self._t.start()

    def stop_and_snap(self, suffix=""):
        self._stop.set()
        self._t.join()
        draw_bar(self.prefix, 100, self.width, suffix)
        sys.stdout.write("\n")
        sys.stdout.flush()

# ===================== Utilities =====================

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def run_cmd(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)

def is_macos():
    return platform.system() == "Darwin"

def which(binname):
    res = run_cmd(["/usr/bin/env", "which", binname])
    return res.stdout.strip() if res.returncode == 0 else None

def get_private_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception:
        return "Tidak dapat ditemukan"

def pretty_pass(b):
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

# ===================== Internet (speedtest-cli module ONLY) =====================

def do_speedtest(retries=2, pause=2):
    """
    Gunakan modul speedtest-cli saja.
    """
    if speedtest is None:
        raise RuntimeError("speedtest-cli module belum tersedia. Aktifkan venv lalu: pip install speedtest-cli")

    last_err = None
    for attempt in range(1, retries+1):
        try:
            st = speedtest.Speedtest()

            print()  # spacing
            with Spinner("🔎 Mencari server terbaik"):
                st.get_best_server()
            draw_bar("🔎 Mencari server terbaik", 100); sys.stdout.write("\n\n")

            bar = IndeterminateBar("⬇️  Mengukur download     ")
            bar.start()
            down = st.download() / 1_000_000
            bar.stop_and_snap(f"{down:.2f} Mbps")
            print()

            bar = IndeterminateBar("⬆️  Mengukur upload       ")
            bar.start()
            up = st.upload() / 1_000_000
            bar.stop_and_snap(f"{up:.2f} Mbps")
            print()

            ping = st.results.ping
            public_ip = st.results.client.get('ip')
            server = st.results.server or {}

            return {
                "download_mbps": float(down),
                "upload_mbps": float(up),
                "ping_ms": float(ping),
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
            print(f"\n⚠️ speedtest gagal (attempt {attempt}/{retries}): {e}")
            time.sleep(pause)

    raise last_err

# ===================== Ping / Jitter / Loss (per‑packet) =====================

PING_TIME_RE = re.compile(r"time[=<]([\d\.]+)\s*ms", re.I)

def resolve_ping_path():
    for p in ("/sbin/ping", "/usr/sbin/ping", "/bin/ping", "/usr/bin/ping"):
        if os.path.exists(p):
            return p
    return which("ping") or "ping"

def ping_per_packet(host, timeout=1):
    """
    Kirim 1 paket ping. Return (success(bool), rtt_ms or None).
    macOS: tanpa -W; Linux: pakai -W <seconds>. Fallback tanpa -W jika gagal.
    """
    ping_bin = resolve_ping_path()
    if is_macos():
        cmd = [ping_bin, "-c", "1", "-n", host]
    else:
        cmd = [ping_bin, "-c", "1", "-n", "-W", str(int(timeout)), host]
    res = run_cmd(cmd, check=False)
    if res.returncode != 0 and not is_macos():
        res = run_cmd([ping_bin, "-c", "1", "-n", host], check=False)

    ok = (res.returncode == 0)
    rtt = None
    m = PING_TIME_RE.search(res.stdout)
    if m:
        try:
            rtt = float(m.group(1))
        except Exception:
            pass
    return ok, rtt

def ping_stats_progress(host, count=10, timeout=1, width=28):
    """
    Ping granular per‑paket dengan progress bar.
    Return dict: loss_pct, rtt_ms{min,avg,max,stddev}
    """
    print("")  # spacing atas
    rtts, sent, recv = [], 0, 0
    for i in range(1, count+1):
        sent += 1
        ok, rtt = ping_per_packet(host, timeout=timeout)
        if ok and rtt is not None:
            recv += 1
            rtts.append(rtt)
        draw_bar(f"📡 Ping {host:<15}", i/count*100, width, f"{recv}/{sent} rx")
        time.sleep(0.05)
    sys.stdout.write("\n")  # spacing bawah
    loss = 100.0 * (1 - (recv / max(1, sent)))
    stats = {}
    if rtts:
        stats = {
            "min": min(rtts),
            "avg": mean(rtts),
            "max": max(rtts),
            "stddev": pstdev(rtts) if len(rtts) > 1 else 0.0
        }
    return {"host": host, "loss_pct": round(loss, 2), "rtt_ms": {k: round(v, 2) for k, v in stats.items()}}

# ===================== macOS: networkQuality & Wi‑Fi =====================

def _num(s):
    try:
        return float(re.findall(r"[-+]?\d*\.?\d+", s)[0])
    except Exception:
        return 0.0

def run_networkquality():
    if not is_macos():
        return None
    nq_path = which("networkQuality") or "/usr/bin/networkQuality"
    if not os.path.exists(nq_path):
        return None
    try:
        out = run_cmd([nq_path, "-v"]).stdout
        lines = out.splitlines()
        down_line = next((l for l in lines if re.search(r"Downlink", l, re.I)), "")
        up_line   = next((l for l in lines if re.search(r"Uplink", l, re.I)), "")
        resp_line = next((l for l in lines if re.search(r"Responsiveness", l, re.I)), "")
        resp_val = _num(resp_line)
        # Apple prints responsiveness in requests/s; if that looks huge, keep as 0 ms (unknown)
        return {
            "download_mbps": _num(down_line),
            "upload_mbps": _num(up_line),
            "responsiveness_rtt_ms": resp_val if resp_val < 1000 else 0.0
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
    if not thresholds or not meas:
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

# ===================== Gateway helper =====================

def find_default_gateway():
    if is_macos():
        try:
            out = run_cmd(["route", "-n", "get", "default"]).stdout
            for line in out.splitlines():
                if "gateway:" in line:
                    return line.split()[-1].strip()
        except Exception:
            pass
    else:
        try:
            out = run_cmd(["ip", "route", "show", "default"]).stdout
            m = re.search(r"default via ([0-9.]+)", out)
            if m:
                return m.group(1)
        except Exception:
            pass
    return None

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
        "ping_targets": "gateway,8.8.8.8,1.1.1.1", "ping_count": 15, "ping_timeout": 1,
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
            json_out=None, tag=PRESETS_INTERNET[preset]["tag"]
        )
        apply_internet_preset(a, preset)
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
            lan_duration=10, json_out=None, tag=PRESETS_LAN[preset]["tag"]
        )
        apply_lan_preset(a, preset)
        return a

    else:
        print("❌ Pilihan tidak valid.")
        return None

# ===================== Internet flow =====================

def internet_flow(args):
    print("🔎 Internet test dimulai...\n")
    private_ip = get_private_ip()

    st = None
    try:
        st = do_speedtest(retries=args.retries, pause=args.retry_pause)
    except Exception as e:
        print(f"❌ Speedtest gagal total: {e}")
        print("➡️  Lanjutkan dengan networkQuality/Wi‑Fi/ping saja...\n")

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
        with Spinner("⏱️  Jalankan networkQuality"):
            nq = run_networkquality()
        if nq:
            print(f"networkQuality → Down {nq['download_mbps']:.2f} Mbps | Up {nq['upload_mbps']:.2f} Mbps | Resp ~{nq['responsiveness_rtt_ms']:.0f} ms")
        else:
            print("networkQuality tidak tersedia.")

    # Wi‑Fi info
    wifi = None
    if getattr(args, "wifi_info", False):
        with Spinner("📶 Ambil info Wi‑Fi"):
            wifi = get_wifi_info()
        if wifi:
            for k, v in wifi.items():
                print(f"{k:14}: {v}")
        else:
            print("Tidak tersedia / bukan macOS / tidak terhubung via Wi‑Fi.")

    # Build ping target list (auto gateway)
    ping_results = []
    targets = []
    preset_targets = getattr(args, "ping_targets", None)
    if preset_targets:
        for h in preset_targets.split(","):
            h = h.strip()
            if not h:
                continue
            if h in {"gateway", "default", "gw", "router"}:
                gw = find_default_gateway()
                if gw:
                    targets.append(gw)
            else:
                targets.append(h)

    # Ping per‑paket per target
    if targets:
        print("\n📡 Ping multi-target (per paket)...")
        for host in targets:
            res = ping_stats_progress(host, count=args.ping_count, timeout=args.ping_timeout)
            ping_results.append(res)
            rtt = res.get("rtt_ms", {})
            print(f"   ↳ loss {res.get('loss_pct')}% | rtt min/avg/max/stddev = "
                  f"{rtt.get('min','-')}/{rtt.get('avg','-')}/{rtt.get('max','-')}/{rtt.get('stddev','-')} ms")

    # Thresholds & verdict
    thresholds = None
    keys = ["min_down", "min_up", "max_ping", "max_jitter", "max_loss"]
    if any(getattr(args, k, None) is not None for k in keys):
        thresholds = {k: getattr(args, k) for k in keys if getattr(args, k, None) is not None}

    if thresholds:
        print("\n✅/❌ Threshold checks")
        if st:
            for k, ok in verdict_internet(st, thresholds).items():
                print(f"- {k:8}: {pretty_pass(ok)}")
        if ping_results:
            for host, ok in verdict_ping(ping_results, thresholds).items():
                print(f"- ping {host:15}: {pretty_pass(ok)}")

    # CSV (zeros if no speedtest)
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

    # JSON
    if getattr(args, "json_out", None):
        out = {
            "timestamp": now_str(),
            "private_ip": get_private_ip(),
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
    with Spinner("🔁 iPerf3 running"):
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

    lan_row = [now_str(), res['server'], f"{(res['bits_per_second'] or 0)/1e9:.2f}", getattr(args, "tag", "") or ""]
    save_csv("lan_speed_history.csv", ["Timestamp","Server IP","Transfer (Gbps)","Tag"], lan_row)

    if getattr(args, "json_out", None):
        out = {"timestamp": now_str(), "lan": res, "tag": getattr(args, "tag", None)}
        save_json(args.json_out, out)

# ===================== CLI main =====================

def main():
    parser = argparse.ArgumentParser(description="Alat Tes Kecepatan Internet dan LAN (macOS friendly).")
    sub = parser.add_subparsers(dest="mode", required=False)

    # internet
    p_int = sub.add_parser("internet", help="Mode internet")
    p_int.add_argument("--preset", choices=list(PRESETS_INTERNET.keys()))
    p_int.add_argument("--retries", type=int, default=2)
    p_int.add_argument("--retry-pause", type=int, default=2)
    p_int.add_argument("--ping-targets")
    p_int.add_argument("--ping-count", type=int, default=10)
    p_int.add_argument("--ping-timeout", type=int, default=1)
    p_int.add_argument("--use-networkquality", action="store_true")
    p_int.add_argument("--wifi-info", action="store_true")
    p_int.add_argument("--min-down", type=float)
    p_int.add_argument("--min-up", type=float)
    p_int.add_argument("--max-ping", type=float)
    p_int.add_argument("--max-jitter", type=float)
    p_int.add_argument("--max-loss", type=float)
    p_int.add_argument("--json-out")
    p_int.add_argument("--tag")

    # lan
    p_lan = sub.add_parser("lan", help="Mode LAN (iPerf3)")
    p_lan.add_argument("--preset", choices=list(PRESETS_LAN.keys()))
    p_lan.add_argument("--server")
    p_lan.add_argument("--lan-parallel", type=int, default=1)
    p_lan.add_argument("--lan-reverse", action="store_true")
    p_lan.add_argument("--lan-udp", action="store_true")
    p_lan.add_argument("--lan-udp-bandwidth", default="0")
    p_lan.add_argument("--lan-duration", type=int, default=10)
    p_lan.add_argument("--json-out")
    p_lan.add_argument("--tag")

    # explicit menu
    sub.add_parser("menu", help="Menu interaktif")

    # No args → menu
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

    # Parse CLI
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