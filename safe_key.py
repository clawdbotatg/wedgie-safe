# Safe Signer's key in a Trust M: made once, locked for good. Loaded only at start and when the key is
# made, then dropped.
#
# The chip is the only truth. It keeps the private key (KEY2) and its public key (DATA[11]: MAGIC + X + Y;
# a Trust M hands a public key out only when it makes the key). Once made, both are locked: their
# lifecycle goes to operational (0x07), which closes their "LcsO < 0x07" change rules for good. Nothing,
# no app, no computer, no one, can replace the key, change the copy, or unlock them after that. Tried on a
# real Trust M (2026-10-15): a new key, a write, an unlock, a new use or read rule all refused; it still
# signs. Other apps keep their keys in KEY3 and KEY4 (trustm.md).
#
# Every start the chip signs a fresh digest and the copy has to check it: a copy that doesn't is no key.
import gc, hashlib, binascii
import ui

MAGIC = b"wsafe1"
LOCKED = b"\x07"
CHIP = "OPTIGA Trust M"


def hx(b):
    return "0x" + binascii.hexlify(b).decode()


def _signs(c, optiga, pub):
    """The key in KEY2 is the one whose public key is pub (65 bytes, 04 X Y): checked by the chip."""
    h = hashlib.sha256(c.random(32)).digest()
    r, s = c.sign(optiga.KEY2, h)
    return c.verify(h, r, s, pub)


def _locked(c, oid):
    return c.metadata(oid).get(0xC0) == LOCKED


def _lock(c, optiga):
    """Both locked for good (the copy first: a key is never locked without its public key kept)."""
    for oid in (optiga.DATA[11], optiga.KEY2):
        if not _locked(c, oid):
            c.set_metadata(oid, {0xC0: LOCKED})
        if not _locked(c, oid):
            raise OSError("the chip didn't lock")


def _key(pub):
    return {"x": hx(pub[1:33]), "y": hx(pub[33:65]), "chip": CHIP}


def start(saved):
    """What the chip holds, as (state, key):
        "ok", key       the key, locked, its copy checked
        "none", None    no key yet: the person makes one (A)
        "lock", key     a key from before locking (safe-12 and older, its public key only in the save):
                        the person locks it, or says no and makes their own
        "swap", None    a locked key that isn't Safe Signer's (or a copy that doesn't match): this chip
                        can't be used, swap it
    Raises when no Trust M answers. The caller drops optiga after (safe._unload)."""
    import optiga
    try:
        c = optiga.Chip()
        locked = _locked(c, optiga.KEY2)
        b = c.read(optiga.DATA[11])
        if b[:len(MAGIC)] == MAGIC:
            pub = b"\x04" + b[len(MAGIC):len(MAGIC) + 64]
            if not _signs(c, optiga, pub):  # a copy of some other key: fixable only while unlocked
                return ("swap" if locked or _locked(c, optiga.DATA[11]) else "none"), None
            _lock(c, optiga)            # a make cut off before its lock (unplugged): finish it
            return "ok", _key(pub)
        if saved and saved.get("chip") != "ATECC608":
            pub = b"\x04" + binascii.unhexlify(saved["x"][2:]) + binascii.unhexlify(saved["y"][2:])
            if _signs(c, optiga, pub):
                return "lock", _key(pub)
        return ("swap" if locked else "none"), None
    finally:
        gc.collect()


def lock(key):
    """Keep this key for good: its public key into the chip, then both locked. Checked first."""
    import optiga
    try:
        c = optiga.Chip()
        pub = b"\x04" + binascii.unhexlify(key["x"][2:]) + binascii.unhexlify(key["y"][2:])
        if not _signs(c, optiga, pub):
            raise OSError("that key isn't in the chip")
        c.write(optiga.DATA[11], MAGIC + pub[1:], erase=True)
        _lock(c, optiga)
    finally:
        gc.collect()


def make():
    """The person's own key: made in the chip (replacing an unlocked one), kept, locked for good."""
    import optiga
    ui.progress("Making your key", "in the chip", False)
    try:
        c = optiga.Chip()
        if _locked(c, optiga.KEY2):
            raise OSError("this chip's key is locked: swap the chip")
        pub = c.genkey(optiga.KEY2)             # 65 bytes: 04 X Y
        c.write(optiga.DATA[11], MAGIC + pub[1:], erase=True)
        if not _signs(c, optiga, pub):
            raise OSError("the new key didn't check")
        _lock(c, optiga)
        return _key(pub)
    finally:
        gc.collect()
