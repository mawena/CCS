"""Shell d'un serveur CCS dans un onglet de terminal du bureau : `ccs shell-distant` relaie le
terminal local (clavier, taille) et un pseudo-terminal du pont du serveur."""

import asyncio


async def relay(c, cwd, reader, write, size, resize_event=None):
    """Ouvre un terminal sur le pont et relaie jusqu'à sa fin ; renvoie son code de sortie."""
    cols, rows = size()
    loop = asyncio.get_running_loop()
    done = loop.create_future()
    box = {}

    def on_event(name, data):
        if data.get("term_id") != box.get("id"):
            return
        if name == "term.output":
            write(data.get("data", "").encode("utf-8"))
        elif name == "term.exit" and not done.done():
            done.set_result(data.get("code"))
    c.on_event = on_event
    box["id"] = (await c.call("term.open", cwd=cwd, cols=cols, rows=rows))["term_id"]

    async def pump():
        while True:
            data = await reader.read(4096)
            if not data:
                break
            await c.call("term.input", term_id=box["id"], data=data.decode("utf-8", "replace"))

    async def follow_size():
        while resize_event is not None:
            await resize_event.wait()
            resize_event.clear()
            cols, rows = size()
            await c.call("term.resize", term_id=box["id"], cols=cols, rows=rows)

    tasks = [asyncio.ensure_future(pump()), asyncio.ensure_future(follow_size())]
    try:
        code = await done
    finally:
        for t in tasks:
            t.cancel()
    return code if isinstance(code, int) else 0
