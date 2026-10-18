#!/usr/bin/env python
"""render.py - headless renderer for the p5.brush animation studio (Python port of render.mjs).

Usage:
  python render.py --stills=1.2,3.4 --out=out/stills
  python render.py --sheet=0.5,1,1.5 --cols=4 --w=480 --out=out/check/a.jpg
  python render.py --strip=2.0:2.5 --cols=6 --w=320 --out=out/check/strip.jpg
  python render.py --sheet=2.1 --crop=760,300,400,400 --w=600 --out=out/check/face.jpg
  python render.py --frames [--range=0:8] [--workers=2] [--fps=24] --out=out/frames
  python render.py --encode --fps=24 --audio=assets/song.mp3 --out=out/video.mp4
"""
import argparse, base64, json, os, sys, time, subprocess, shutil, glob, socket, tempfile, urllib.request
import websocket

HERE = os.path.dirname(os.path.abspath(__file__))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333


def log(*a):
    print(*a, flush=True)


def start_edge(port=PORT, width=1920, height=1080, extra=None):
    prof = os.path.join(tempfile.gettempdir(), f"mvstudio-profile-{port}")
    args = [EDGE, "--headless=new", f"--remote-debugging-port={port}", "--remote-allow-origins=*",
            f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
            "--ignore-gpu-blocklist", "--enable-gpu-rasterization", "--enable-unsafe-swiftshader", "--force_high_performance_gpu", "--enable-zero-copy",
            "--use-angle=d3d11", "--disable-renderer-backgrounding", "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows", "--autoplay-policy=no-user-gesture-required",
            f"--window-size={width},{height}", "about:blank"]
    if extra:
        args += extra
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                ws_url = json.load(r)["webSocketDebuggerUrl"]
            break
        except Exception:
            time.sleep(0.25)
    if not ws_url:
        raise RuntimeError("Edge devtools did not start")
    return p, port


class Tab:
    _id = 0

    def __init__(self, port, url=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=20) as r:
            info = json.load(r)
        self.ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=600,
                                             max_size=64 * 1024 * 1024)
        self.mid = 0
        self.target_id = info.get("id")
        Tab._id += 1
        self._cmd("Page.enable")
        self._cmd("Runtime.enable")
        if url:
            self.open(url)

    def _cmd(self, method, params=None):
        self.mid += 1
        mid = self.mid
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def eval(self, expr, await_promise=True):
        r = self._cmd("Runtime.evaluate", {"expression": expr, "awaitPromise": await_promise,
                                           "returnByValue": True, "userGesture": True})
        if r.get("exceptionDetails"):
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:2000])
        return r["result"].get("value")

    def open(self, url, wait_ready=True):
        self._cmd("Page.navigate", {"url": url})
        if wait_ready:
            for _ in range(240):
                try:
                    if self.eval("window.ready === true", await_promise=False):
                        return
                except Exception:
                    pass
                time.sleep(0.25)
            raise RuntimeError("window.ready never became true")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def data_url_to_bytes(url):
    return base64.b64decode(url[url.index(",") + 1:])


def save_data_url(url, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data_url_to_bytes(url))


def parse_times(s):
    return [float(x) for x in str(s).split(",")]


def parse_span(s):
    a, b = str(s).split(":")
    return float(a), float(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--stills")
    ap.add_argument("--sheet")
    ap.add_argument("--strip")
    ap.add_argument("--crop")
    ap.add_argument("--crop-at")
    ap.add_argument("--cols", type=int)
    ap.add_argument("--w", type=int)
    ap.add_argument("--out")
    ap.add_argument("--fps", type=float, default=24)
    ap.add_argument("--frames", action="store_true")
    ap.add_argument("--encode", action="store_true")
    ap.add_argument("--range")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--audio")
    ap.add_argument("--loop")
    ap.add_argument("--quality", type=float, default=0.94)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--keep-open", action="store_true")
    args = ap.parse_args()

    url = args.url or ("file:///" + os.path.join(HERE, "studio.html").replace("\\", "/") + "?render")

    if args.encode:
        encode(args)
        return

    proc, port = start_edge(args.port)
    tabs = []
    try:
        probe = Tab(port)
        tabs.append(probe)
        probe.open(url)
        if args.loop:
            ok = probe.eval(f"!!LOOPS[{json.dumps(args.loop)}]")
            if not ok:
                raise SystemExit(f"no loop named {args.loop}")
            probe.eval(f"window.LOOP = LOOPS[{json.dumps(args.loop)}]")
        if args.stills:
            out = args.out or os.path.join(HERE, "out", "stills")
            os.makedirs(out, exist_ok=True)
            log("GPU:", probe.eval("window.gpuInfo()"))
            for s in parse_times(args.stills):
                t0 = time.time()
                du = probe.eval(f"window.renderAt({s})")
                f = os.path.join(out, f"t{s:.2f}".replace(".", "_") + ".png")
                save_data_url(du, f)
                log(f"{f}  {int((time.time()-t0)*1000)} ms")
        elif args.sheet or args.strip:
            if args.strip:
                a, b = parse_span(args.strip)
                ts = [i / args.fps for i in range(int(round(a * args.fps)), int(round(b * args.fps)) + 1)]
            else:
                ts = parse_times(args.sheet)
            cols = args.cols or (6 if args.strip else 3)
            w = args.w or (320 if args.strip else 640)
            crop = parse_times(args.crop) if args.crop else None
            at = args.crop_at or None
            expr = f"window.renderSheet({json.dumps(ts)}, {cols}, {w}, {json.dumps(crop)}, {json.dumps(at)})"
            r = probe.eval(expr)
            out = args.out or os.path.join(HERE, "out", "sheet.jpg")
            save_data_url(r["url"], out)
            log(f"{out}  ({len(ts)} frames)  ms/frame: {' '.join(str(x) for x in r['ms'])}")
        elif args.frames:
            render_frames(args, port, url)
    finally:
        for t in tabs:
            t.close()
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def length_of(tab):
    return tab.eval("window.LOOP ? window.LOOP.len : DUR")


def render_frames(args, port, url):
    probe = Tab(port)
    probe.open(url)
    if args.loop:
        probe.eval(f"window.LOOP = LOOPS[{json.dumps(args.loop)}]")
    length = length_of(probe)
    probe.close()
    fps = args.fps
    a, b = parse_span(args.range) if args.range else (0.0, length)
    out = args.out or os.path.join(HERE, "out", "frames")
    os.makedirs(out, exist_ok=True)
    first = int(round(a * fps))
    last = min(int(round(length * fps)) - 1, int(round(b * fps)) - 1)
    todo = []
    for i in range(first, last + 1):
        f = os.path.join(out, f"f{i:05d}.jpg")
        if not os.path.exists(f) or os.path.getsize(f) < 1000:
            todo.append(i)
    log(f"{len(todo)} frames to render ({last-first+1-len(todo)} already done), {args.workers} workers, fps={fps}")
    workers = max(1, args.workers)
    tabs = []
    for _ in range(workers):
        t = Tab(port)
        t.open(url)
        if args.loop:
            t.eval(f"window.LOOP = LOOPS[{json.dumps(args.loop)}]")
        tabs.append(t)
    state = {"next": 0}
    start = time.time()
    done = 0

    def work(w):
        nonlocal done
        t = tabs[w]
        while True:
            if state["next"] >= len(todo):
                return
            i = todo[state["next"]]
            state["next"] += 1
            f = os.path.join(out, f"f{i:05d}.jpg")
            du = t.eval(f"window.renderAt({i / fps}, 'image/jpeg', {args.quality})")
            tmp = f + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data_url_to_bytes(du))
            os.replace(tmp, f)
            done += 1
            if done % 20 == 0 or done == len(todo):
                el = time.time() - start
                log(f"  {done}/{len(todo)}  {el/done*1000:.0f} ms/frame  eta {(len(todo)-done)*el/done/60:.1f} min")

    try:
        import threading
        th = [threading.Thread(target=work, args=(w,), daemon=True) for w in range(workers)]
        for x in th:
            x.start()
        for x in th:
            x.join()
    finally:
        for t in tabs:
            t.close()
    log(f"{len(todo)} frames -> {out}  ({((time.time()-start)/max(1,len(todo)))*1000:.0f} ms/frame)")


def encode(args):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = args.out or os.path.join(HERE, "out", "video.mp4")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    src = os.path.join(HERE, "out", "frames", "f%05d.jpg")
    cmd = [ff, "-y", "-loglevel", "error", "-stats", "-framerate", str(args.fps), "-i", src]
    if args.audio:
        cmd += ["-i", args.audio, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out]
    log(" ".join(cmd))
    subprocess.run(cmd, check=True)
    log("wrote " + out)


if __name__ == "__main__":
    main()


