# safe_prove: "this wedgie, this key, just now", for a site that gates something on owning a wedgie
# (wedgie.dev/telegram). Loaded only for a safe_prove request, then dropped.
#
#   {"type":"safe_prove","text":"Join Telegram","code":".."} -> the screen asks "Prove it" with the text; on a real A:
#   {"type":"safe_proof","text","code","x","y","r","s","cert","fr","fs"}  or {"type":"refused"}
#
# Two signatures, both checked by the site:
#   r, s    the Safe key (KEY2) over sha256("wedgie prove\0" + sha256(text "\n" code)): the site's fresh code, after a press.
#   fr, fs  the chip's factory key over sha256("wedgie safe key\0" + X + Y): this key lives in this chip. X, Y are the key
#           the app read from the chip and checked at start, never from the computer. cert: the chip's Infineon
#           certificate for the factory key (it chains to Infineon's roots), so one chip is one wedgie.
# What each key signs can't be anything else: the Safe key's preimage is 45 bytes (a Safe signature's is 69 or
# more), the factory key's 80 (the firmware's chip check signs 100 random bytes of its own).
import hashlib, binascii

TEXT_MAX = 24
CODE_MAX = 200


def ok_text(s):
    return isinstance(s, str) and 0 < len(s) <= TEXT_MAX and all(32 <= ord(c) < 127 for c in s)


def prove(S, mid, text, code):
    """S: the safe module (its key, screen, sign)."""
    W = S.W
    if S.state != "ok":
        W.send({"id": mid, "type": "error", "error": "no key yet: make one in Safe Signer first"})
        return
    if S.key.get("chip") == "ATECC608":
        W.send({"id": mid, "type": "error", "error": "needs a Trust M chip"})
        return
    if not ok_text(text) or not isinstance(code, str) or not 0 < len(code) <= CODE_MAX:
        W.send({"id": mid, "type": "error", "error": "bad text or code"})
        return
    k = S.L.Keys(physical=True)
    k.pressed()
    if not S._screen("Prove it", [S.GAP, (text, S.INK, S.BIG)], "sign", k):
        S.note = "said no"
        W.send({"id": mid, "type": "refused"})
        return
    S.ui.progress("Signing", "in the chip", False)
    inner = hashlib.sha256(text.encode() + b"\n" + code.encode()).digest()
    r, s = S.sign(hashlib.sha256(b"wedgie prove\x00" + inner).digest())
    xy = binascii.unhexlify(S.key["x"][2:]) + binascii.unhexlify(S.key["y"][2:])
    import optiga
    try:
        c = optiga.Chip()
        cert = c.read(optiga.CERT)
        fr, fs = c.sign(optiga.FACTORY_KEY, hashlib.sha256(b"wedgie safe key\x00" + xy).digest())
    finally:
        S._unload()
    S.note = "proved"
    W.send({"id": mid, "type": "safe_proof", "text": text, "code": code, "x": S.key["x"], "y": S.key["y"],
            "r": "0x%064x" % r, "s": "0x%064x" % s, "cert": binascii.hexlify(cert).decode(),
            "fr": "0x%064x" % fr, "fs": "0x%064x" % fs})
