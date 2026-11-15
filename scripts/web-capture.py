#!/usr/bin/env python3
"""Essai de la version web dans Chrome sans écran (développement seulement).

Ouvre une page, exécute des étapes JavaScript (`--js "…"`, attente par `--wait ms`) puis
enregistre une capture. Passe par le protocole de débogage de Chrome (aucun module en plus).
Exemple : web-capture.py http://127.0.0.1:8421/#/sessions --width 375 --js "…" --wait 1500 --out a.png
"""

import argparse
import asyncio
import base64
import itertools
import json
import shutil
import subprocess
import tempfile
import urllib.request

import aiohttp

PORT = 9333


async def run(args):
    global PORT
    PORT = args.cdp_port
    profile = tempfile.mkdtemp(prefix="ccs-capture-")
    chrome = subprocess.Popen([shutil.which("google-chrome") or "chromium", "--headless=new", "--disable-gpu",
                               "--no-first-run", f"--user-data-dir={profile}", f"--remote-debugging-port={PORT}",
                               "--hide-scrollbars", f"--window-size={args.width},{args.height}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                await asyncio.sleep(0.1)
        ids = itertools.count(1)
        async with aiohttp.ClientSession() as s, s.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
            async def cmd(method, **params):
                i = next(ids)
                await ws.send_json({"id": i, "method": method, "params": params})
                async for msg in ws:
                    data = json.loads(msg.data)
                    if data.get("id") == i:
                        return data.get("result", {})
            await cmd("Emulation.setDeviceMetricsOverride", width=args.width, height=args.height,
                      deviceScaleFactor=1, mobile=args.width < 720)
            await cmd("Page.enable")
            await cmd("Page.navigate", url=args.url)
            await asyncio.sleep(args.first_wait / 1000)
            for step in args.steps:
                kind, value = step
                if kind == "js":
                    r = await cmd("Runtime.evaluate", expression=value, awaitPromise=True, returnByValue=True)
                    if r.get("exceptionDetails"):
                        print("erreur JS :", r["exceptionDetails"].get("text"), r["exceptionDetails"].get("exception", {}).get("description", "")[:300])
                    elif r.get("result", {}).get("value") is not None:
                        print("→", r["result"]["value"])
                else:
                    await asyncio.sleep(int(value) / 1000)
            shot = await cmd("Page.captureScreenshot", format="png")
            with open(args.out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            print("capture :", args.out)
    finally:
        chrome.terminate()
        chrome.wait(10)
        shutil.rmtree(profile, ignore_errors=True)


class Step(argparse.Action):
    def __call__(self, parser, ns, value, option):
        ns.steps.append(("js" if option == "--js" else "wait", value))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--width", type=int, default=375)
    p.add_argument("--height", type=int, default=780)
    p.add_argument("--first-wait", type=int, default=1500)
    p.add_argument("--cdp-port", type=int, default=PORT, help="port de débogage de Chrome (captures en parallèle)")
    p.add_argument("--out", default="capture.png")
    p.add_argument("--js", action=Step, dest="steps", default=[])
    p.add_argument("--wait", action=Step, dest="steps")
    asyncio.run(run(p.parse_args()))
